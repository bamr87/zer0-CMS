"""`/api/v2/newsroom/`: the newsroom over REST (TARGET.md § The newsroom).

Thin views: each validates, calls `newsroom.services` and serializes. They
serve people (`IsPerson`); rows come from `visible_to(user, site)` only, so a
row someone may not see is a 404. The story budget and the editorial calendar
are the story list's filters (status, desk, assignee, slot and deadline
ranges). A move the newsroom workflow refuses is a 409 that says which moves
it allows; a page right the person lacks is a 403 from `cms.services`. Asking
the AI answers `202` with the run (followed on `/api/v2/agent-runs/<id>/stream/`)
and honours an `Idempotency-Key`. The three subscription endpoints are public,
for a site's own forms; the links in the email open `subscription_page`, which
changes nothing until its button is pressed.
"""

from django.contrib.auth import get_user_model
from django.db.models import ProtectedError, Q
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import SAFE_METHODS, AllowAny, BasePermission
from rest_framework.response import Response
from wagtail.models import Site

from ai.serializers import RunAcceptedSerializer, RunRefSerializer
from ai.views import IDEMPOTENCY, idempotent
from api.pages import IsPerson, service_errors
from ops.errors import ApiError, Conflict, Forbidden, Invalid, NotFound
from ops.openapi import ERROR_RESPONSES

from . import serializers as s
from . import services
from .models import Author, Desk, Front, Issue, Newsletter, Story

User = get_user_model()
SITE = OpenApiParameter("site", OpenApiTypes.INT, description="Only this Wagtail site's rows.")


class Paged(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class Scoped(viewsets.ModelViewSet):
    """A site-scoped newsroom table: rows by public id, `visible_to` only."""

    lookup_field = "public_id"
    permission_classes = [IsPerson]
    pagination_class = Paged
    filter_backends = [filters.DjangoFilterBackend, OrderingFilter]
    http_method_names = ["get", "post", "patch", "delete"]  # a change is a PATCH

    def get_queryset(self):
        site = None
        if value := self.request.query_params.get("site"):
            if not value.isdigit():
                raise Invalid("site is a site's id", details=[{"field": "site", "code": "invalid", "message": value}])
            site = Site.objects.filter(pk=value).first()
            if site is None:
                return self.queryset.none()
        return self.queryset.visible_to(self.request.user, site)

    def curate(self, site):
        if not services.can_manage(site, self.request.user):
            raise Forbidden("the site's desk editors curate its fronts and newsletters")

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as e:
            raise Conflict(f"{instance} is in use: {len(e.protected_objects)} row(s) refer to it") from e


# ── desks ──────────────────────────────────────────────────────────────────


class ManagesDesks(BasePermission):
    """Reading a desk is anyone's who works on its site; setting one up is a Django permission."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        verb = {"POST": "add", "DELETE": "delete"}.get(request.method, "change")
        return request.user.has_perm(f"newsroom.{verb}_desk")


@extend_schema_view(
    list=extend_schema(summary="The desks of the sites a person works on", parameters=[SITE]),
    create=extend_schema(request=s.writable(s.DeskSerializer)),
)
class DeskViewSet(Scoped):
    queryset = Desk.objects.select_related("site", "section", "assistant", "pipeline").prefetch_related(
        "editors", "copy_editors"
    )
    serializer_class = s.DeskSerializer
    permission_classes = [IsPerson, ManagesDesks]
    ordering_fields = ["name", "created_at"]

    @extend_schema(
        summary="The people a desk's stories may be assigned to", responses={200: s.PersonSerializer(many=True)}
    )
    @action(detail=True, methods=["get"], pagination_class=None, filter_backends=[])
    def people(self, request, public_id=None):
        desk = self.get_object()
        people = User.objects.filter(is_active=True).exclude(username__startswith="agent:").order_by("username")
        return Response(s.PersonSerializer([u for u in people if services.works_on(desk, u)], many=True).data)


# ── stories: the budget, the calendar, the workflow ────────────────────────


class StoryFilter(filters.FilterSet):
    desk = filters.UUIDFilter(field_name="desk__public_id")
    site = filters.NumberFilter(field_name="desk__site")
    status = filters.MultipleChoiceFilter(choices=Story.Status.choices, help_text="One or more statuses.")
    assignee = filters.CharFilter(method="by_assignee", help_text="A person's id, or `me`.")
    my_desks = filters.BooleanFilter(method="by_my_desks", help_text="Stories of the desks the requester edits.")
    slot_after = filters.DateFilter(field_name="slot_date", lookup_expr="gte")
    slot_before = filters.DateFilter(field_name="slot_date", lookup_expr="lte")
    deadline_after = filters.DateTimeFilter(field_name="deadline", lookup_expr="gte")
    deadline_before = filters.DateTimeFilter(field_name="deadline", lookup_expr="lte")
    q = filters.CharFilter(field_name="headline", lookup_expr="icontains")

    class Meta:
        model = Story
        fields = ["desk", "site", "status", "assignee", "my_desks", "priority", "breaking"]

    def by_assignee(self, queryset, name, value):
        if value == "me":
            return queryset.filter(assignee=self.request.user)
        return queryset.filter(assignee_id=value) if value.isdigit() else queryset.none()

    def by_my_desks(self, queryset, name, value):
        mine = Q(desk__editors=self.request.user) | Q(desk__copy_editors=self.request.user)
        return queryset.filter(mine).distinct() if value else queryset


def _person(pk):
    person = User.objects.filter(pk=pk, is_active=True).first() if pk is not None else None
    if pk is not None and person is None:
        raise Invalid("no such person", details=[{"field": "assignee", "code": "invalid", "message": "unknown"}])
    return person


@extend_schema_view(
    list=extend_schema(summary="The story budget and the calendar: stories, filtered", parameters=[SITE]),
    create=extend_schema(
        summary="Pitch a story — by hand, or from a wire or feed item (`source`)",
        request=s.writable(s.StorySerializer),
    ),
    destroy=extend_schema(summary="Spike a pitch (only a pitch, by the desk's editors)"),
)
class StoryViewSet(Scoped):
    queryset = Story.objects.select_related("desk__site", "assignee", "page", "brief").prefetch_related(
        "byline_rows__author"
    )
    serializer_class = s.StorySerializer
    filterset_class = StoryFilter
    ordering_fields = ["priority", "deadline", "slot_date", "created_at", "updated_at", "page__first_published_at"]

    def get_serializer_class(self):
        return s.StoryDetailSerializer if self.action == "retrieve" else s.StorySerializer

    def panel(self, story):
        story = self.get_queryset().get(pk=story.pk)
        return s.StoryDetailSerializer(story, context=self.get_serializer_context()).data

    def perform_create(self, serializer):
        data = dict(serializer.validated_data)
        source = data.pop("source", None)
        serializer.instance = services.pitch(
            data.pop("desk"),
            user=self.request.user,
            item=services.WireItem(**source) if source else None,
            bylines=data.pop("byline_ids", None),
            **data,
        )

    def perform_update(self, serializer):
        data = dict(serializer.validated_data)
        data.pop("desk", None)
        if data.pop("source", None) is not None:
            raise Invalid("a story's wire item is set when it is pitched")
        serializer.instance = services.update(
            serializer.instance, user=self.request.user, bylines=data.pop("byline_ids", None), **data
        )

    def perform_destroy(self, instance):
        services.spike(instance, user=self.request.user)

    @extend_schema(
        summary="Move a story through the newsroom workflow (the budget board's drag)",
        request=s.MoveSerializer,
        responses={200: s.StoryDetailSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    def move(self, request, public_id=None):
        body = s.MoveSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        with service_errors():
            story = services.move(
                self.get_object(),
                data["status"],
                user=request.user,
                assignee=_person(data.get("assignee")),
                comment=data.get("comment", ""),
                reason=data.get("reason", ""),
                go_live_at=data.get("go_live_at"),
                text=data.get("text", ""),
            )
        return Response(self.panel(story))

    @extend_schema(
        summary="Assign (or reassign) a story; a pitch becomes assigned",
        request=s.AssignSerializer,
        responses={200: s.StoryDetailSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    def assign(self, request, public_id=None):
        body = s.AssignSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        story = services.assign(
            self.get_object(),
            _person(body.validated_data["assignee"]),
            user=request.user,
            note=body.validated_data.get("note", ""),
        )
        return Response(self.panel(story))

    @extend_schema(
        summary="Ask the AI: a pitch from the wire item, a draft from the pitch, headlines, or a correction note",
        request=s.AskAISerializer,
        parameters=[IDEMPOTENCY],
        responses={202: RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def ai(self, request, public_id=None):
        body = s.AskAISerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = services.ask_ai(
            self.get_object(), body.validated_data["kind"], user=request.user, text=body.validated_data.get("text", "")
        )
        return Response({"run": RunRefSerializer(run).data}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="The AI draft becomes the story's page: a draft whose text arrives as suggestions",
        request=None,
        responses={201: s.AppliedDraftSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"], url_path="apply-draft")
    def apply_draft(self, request, public_id=None):
        with service_errors():
            page, suggestions = services.apply_draft(self.get_object(), user=request.user)
        story = self.get_object()
        return Response(
            {"story": self.panel(story), "page_id": page.pk, "suggestions": [x.pk for x in suggestions]},
            status=status.HTTP_201_CREATED,
        )


# ── authors ────────────────────────────────────────────────────────────────


class WritesAuthors(BasePermission):
    def has_permission(self, request, view):
        return request.method in SAFE_METHODS or services.edits_a_desk(request.user)


@extend_schema_view(
    list=extend_schema(
        summary="The authors of the stories a person may see, and those no story carries yet", parameters=[SITE]
    ),
    retrieve=extend_schema(summary="An author page: the author and their published stories"),
    create=extend_schema(request=s.writable(s.AuthorSerializer)),
    destroy=extend_schema(summary="Delete an author no story carries"),
)
class AuthorViewSet(Scoped):
    """Bylines' authors: seen by the people of the sites their stories are on (and, unused, by every desk),
    changed by the desk editors of every one of those sites."""

    queryset = Author.objects.all()
    serializer_class = s.AuthorSerializer
    permission_classes = [IsPerson, WritesAuthors]
    filterset_fields = {"name": ["icontains"]}
    ordering_fields = ["name", "created_at"]

    def get_serializer_class(self):
        return s.AuthorPageSerializer if self.action == "retrieve" else s.AuthorSerializer

    def changes(self, author):
        if not services.may_change_author(author, self.request.user):
            raise Forbidden("an author is changed by the desk editors of every site their bylines are on")

    def perform_update(self, serializer):
        self.changes(serializer.instance)
        serializer.save()

    def perform_destroy(self, instance):
        self.changes(instance)
        if instance.stories.exists():
            raise Conflict("the author has bylines: take them off those stories first")
        super().perform_destroy(instance)


# ── fronts ─────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="Home and section fronts", parameters=[SITE]),
    create=extend_schema(request=s.writable(s.FrontSerializer)),
)
class FrontViewSet(Scoped):
    queryset = Front.objects.select_related("site", "desk").prefetch_related("slots__story", "slots__desk")
    serializer_class = s.FrontSerializer
    ordering_fields = ["name", "created_at"]

    def perform_create(self, serializer):
        self.curate(serializer.validated_data["site"])
        serializer.save()

    def perform_update(self, serializer):
        self.curate(serializer.instance.site)
        self.curate(serializer.validated_data.get("site", serializer.instance.site))
        serializer.save()

    def perform_destroy(self, instance):
        self.curate(instance.site)
        super().perform_destroy(instance)

    @extend_schema(
        summary="The front as a reader sees it: each slot's story, pinned or filled by its rule",
        responses={200: s.ResolvedSlotSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], pagination_class=None, filter_backends=[])
    def stories(self, request, public_id=None):
        resolved = [
            {"position": slot.position, "rule": slot.rule, "story": story}
            for slot, story in services.front_stories(self.get_object())
        ]
        return Response(s.ResolvedSlotSerializer(resolved, many=True).data)


# ── newsletters ────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="Newsletters, with their subscriber counts", parameters=[SITE]),
    create=extend_schema(request=s.writable(s.NewsletterSerializer)),
)
class NewsletterViewSet(Scoped):
    queryset = Newsletter.objects.select_related("site")
    serializer_class = s.NewsletterSerializer
    ordering_fields = ["name", "created_at"]

    def perform_create(self, serializer):
        self.curate(serializer.validated_data["site"])
        serializer.save()

    def perform_update(self, serializer):
        self.curate(serializer.instance.site)
        self.curate(serializer.validated_data.get("site", serializer.instance.site))
        serializer.save()

    def perform_destroy(self, instance):
        self.curate(instance.site)
        super().perform_destroy(instance)


class IssueFilter(filters.FilterSet):
    newsletter = filters.UUIDFilter(field_name="newsletter__public_id")

    class Meta:
        model = Issue
        fields = ["newsletter", "status"]


@extend_schema_view(
    create=extend_schema(summary="Compose an issue from stories", request=s.writable(s.IssueSerializer))
)
class IssueViewSet(Scoped):
    queryset = Issue.objects.select_related("newsletter__site")
    serializer_class = s.IssueSerializer
    filterset_class = IssueFilter
    ordering_fields = ["created_at", "sent_at"]

    def _save(self, serializer, newsletter):
        self.curate(newsletter.site)
        stories = serializer.validated_data.pop("story_ids", None)
        issue = serializer.save(**({} if serializer.instance else {"created_by": self.request.user}))
        if stories is not None:
            services.set_issue_stories(issue, stories)

    def perform_create(self, serializer):
        self._save(serializer, serializer.validated_data["newsletter"])

    def perform_update(self, serializer):
        if serializer.instance.status not in (Issue.Status.DRAFT, Issue.Status.FAILED):
            raise Conflict("an issue being sent, or sent, is not changed")
        self._save(serializer, serializer.instance.newsletter)  # it stays on its newsletter (the serializer)

    def perform_destroy(self, instance):
        self.curate(instance.newsletter.site)
        super().perform_destroy(instance)

    @extend_schema(summary="The issue as it is sent: subject, text and HTML", responses={200: s.IssuePreviewSerializer})
    @action(detail=True, methods=["get"])
    def preview(self, request, public_id=None):
        content = services.render_issue(self.get_object())
        return Response(s.IssuePreviewSerializer(content).data)

    @extend_schema(
        summary="Send the issue to the confirmed subscribers, as a job",
        request=None,
        parameters=[IDEMPOTENCY],
        responses={202: s.IssueSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def send(self, request, public_id=None):
        issue = services.send_issue(self.get_object(), user=request.user)
        return Response(s.IssueSerializer(issue, context=self.get_serializer_context()).data, status=202)


# ── subscriptions: public, for a site's forms and the email's links ────────


def _subscription(subscriber) -> Response:
    return Response(s.SubscriptionSerializer(subscriber).data)


@extend_schema(
    summary="Subscribe an address: a confirmation link is emailed to it (the same answer either way)",
    request=s.SubscribeSerializer,
    responses={202: s.SubscriptionSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def subscribe(request, public_id):
    newsletter = Newsletter.objects.filter(public_id=public_id).first()
    if newsletter is None:
        raise NotFound("no such newsletter")
    body = s.SubscribeSerializer(data=request.data)
    body.is_valid(raise_exception=True)
    services.subscribe(newsletter, body.validated_data["email"])
    return Response({"status": "pending", "newsletter": newsletter.name}, status=status.HTTP_202_ACCEPTED)


def _token(request) -> str:
    return request.query_params.get("token") or str(request.data.get("token") or "")


TOKEN = OpenApiParameter("token", OpenApiTypes.STR, description="The token from the emailed link.")


@extend_schema(
    summary="Confirm a subscription with the token from its emailed link (only while it waits to confirm)",
    parameters=[TOKEN],
    request=s.TokenSerializer,
    responses={200: s.SubscriptionSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def confirm(request):
    return _subscription(services.confirm(_token(request)))


@extend_schema(
    summary="Unsubscribe with the token from an issue's link",
    parameters=[TOKEN],
    request=s.TokenSerializer,
    responses={200: s.SubscriptionSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def unsubscribe(request):
    return _subscription(services.unsubscribe(_token(request)))


# The token in the link is the authority here, and a mail client's one-click unsubscribe (RFC 8058) posts
# without a CSRF token: what CSRF protects against — a request forged without the secret — cannot act.
@csrf_exempt
@require_http_methods(["GET", "POST"])
def subscription_page(request, action):
    """The page a newsletter email's link opens (`/newsletters/confirm/`, `/newsletters/unsubscribe/`, and the
    `List-Unsubscribe` header's). A GET only says what the link does, with a button that does it — so a mail
    scanner or a link prefetcher that fetches every link changes nothing; a POST — the button, or a mail
    client's one-click unsubscribe — does it."""
    token = request.GET.get("token", "")
    context = {"action": action, "token": token, "done": request.method == "POST"}
    try:
        if request.method == "POST":
            context["subscriber"] = (services.confirm if action == "confirm" else services.unsubscribe)(token)
        else:
            context["subscriber"] = services.subscription_for(token, action)
    except ApiError as e:
        return render(request, "newsroom/subscription.html", {**context, "error": e.message}, status=e.status)
    return render(request, "newsroom/subscription.html", context)
