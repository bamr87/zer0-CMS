"""`/api/v2/distribution/`: channels, the queue, the ledger and statistics over
REST, for the studio's Distribution area and the extension.

Thin views: each validates, calls `distribution.services` and serializes. They
serve people (`IsPerson`); rows come from `visible_to` only, so a row someone
may not see is a 404. Whatever reaches the network — publishing, exchanging an
OAuth code, checking a credential, reading statistics — answers `202` and runs
on the worker; the studio follows the row. A refusal is the envelope: 403 for a
right the person lacks, 409 with every blocker for a post that may not go now.
"""

import time

from django.conf import settings
from django.db import transaction
from django.db.models import Prefetch
from django.http import HttpResponseRedirect
from django.urls import reverse
from django_filters import rest_framework as filters
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from wagtail.models import Page

from api.pages import IsPerson, service_errors
from ops.errors import Conflict, Forbidden, Invalid, NotFound
from ops.openapi import ERROR_RESPONSES

from . import serializers as s
from . import services
from .linkedin import oauth
from .models import LEDGER_STATES, Channel, DistributionPost, LedgerEntry, Statistic
from .tasks import check_channel, ingest_statistics

SESSION_KEY = "distribution_oauth"


class Paged(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


def redirect_uri(request) -> str:
    return settings.LINKEDIN_REDIRECT_URI or request.build_absolute_uri(reverse("distribution-linkedin-callback"))


# ── channels ────────────────────────────────────────────────────────────────


@extend_schema_view(
    list=extend_schema(summary="The channels of the sites a person works on"),
    create=extend_schema(
        summary="Set up a channel (people who manage channels)",
        responses={201: s.DistributionChannelSerializer, **ERROR_RESPONSES},
    ),
)
class DistributionChannelViewSet(viewsets.ModelViewSet):
    lookup_field = "public_id"
    permission_classes = [IsPerson]
    serializer_class = s.DistributionChannelSerializer
    pagination_class = Paged
    filter_backends = [filters.DjangoFilterBackend]
    filterset_fields = ["site", "kind"]
    http_method_names = ["get", "post", "patch", "delete"]
    queryset = Channel.objects.select_related("site", "newsletter")

    def get_queryset(self):
        return self.queryset.visible_to(self.request.user)

    def perform_create(self, serializer):
        with service_errors():
            serializer.save()

    def perform_update(self, serializer):
        with service_errors():
            serializer.save()

    def perform_destroy(self, channel):
        if not services.may_manage(self.request.user):
            raise Forbidden("removing a channel needs the right to manage channels")
        if channel.ledger.exclude(urn="").exists():
            raise Conflict(
                "this channel has published posts, and its ledger is what keeps them from going twice: disconnect it instead"
            )
        channel.delete()

    @extend_schema(
        request=None,
        responses={200: s.DistributionConnectSerializer, **ERROR_RESPONSES},
        summary="Start connecting a LinkedIn account: the consent URL for its owner (state + PKCE)",
    )
    @action(detail=True, methods=["post"])
    def connect(self, request, public_id=None):
        channel = self.get_object()
        with service_errors():
            started = services.start_connect(channel, request.user, redirect_uri(request))
        waiting = request.session.get(SESSION_KEY, {})
        waiting = {k: v for k, v in waiting.items() if time.time() - v["at"] < oauth.STATE_TTL}
        waiting[started["state"]] = {"channel": channel.pk, "verifier": started["verifier"], "at": time.time()}
        request.session[SESSION_KEY] = waiting
        return Response({"url": started["url"]})

    @extend_schema(
        request=None,
        responses={200: s.DistributionChannelSerializer, **ERROR_RESPONSES},
        summary="Forget the channel's credential here (and disarm it)",
    )
    @action(detail=True, methods=["post"])
    def disconnect(self, request, public_id=None):
        with service_errors():
            channel = services.disconnect(self.get_object(), request.user)
        return Response(self.get_serializer(channel).data)

    @extend_schema(
        request=None,
        responses={202: s.DistributionChannelSerializer, **ERROR_RESPONSES},
        summary="Ask the target whether the credential works (on the worker); follow the channel",
    )
    @action(detail=True, methods=["post"])
    def check(self, request, public_id=None):
        channel = self.get_object()
        transaction.on_commit(lambda: check_channel.delay(channel.pk))
        return Response(self.get_serializer(channel).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        request=None,
        responses={202: None, **ERROR_RESPONSES},
        summary="Read the channel's post statistics now (on the worker)",
    )
    @action(detail=True, methods=["post"])
    def statistics(self, request, public_id=None):
        channel = self.get_object()
        transaction.on_commit(lambda: ingest_statistics.delay(channel.pk))
        return Response(status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        methods=["get"],
        request=None,
        responses={200: s.DistributionLedgerFileSerializer, **ERROR_RESPONSES},
        summary="The channel's ledger as the file every lane reads and writes",
    )
    @extend_schema(
        methods=["post"],
        request=s.DistributionLedgerFileSerializer,
        responses={200: s.DistributionLedgerImportSerializer, **ERROR_RESPONSES},
        summary="Read a ledger file in (the extension's or a site's CI): what it published is never published again",
    )
    @action(detail=True, methods=["get", "post"], url_path="ledger-file")
    def ledger_file(self, request, public_id=None):
        channel = self.get_object()
        if request.method == "GET":
            return Response(
                {"filename": f"{channel.kind}-{channel.public_id}.json", "content": services.ledger_file(channel)}
            )
        body = s.DistributionLedgerFileSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with service_errors():
            counts = services.import_ledger(channel, request.user, body.validated_data["content"])
        return Response(counts)


@extend_schema(
    request=None,
    responses={302: None, **ERROR_RESPONSES},
    summary="Where LinkedIn returns the account's owner; the code is exchanged on the worker",
)
@api_view(["GET"])
@permission_classes([IsPerson])
def linkedin_callback(request):
    state = request.query_params.get("state", "")
    waiting = request.session.get(SESSION_KEY, {})
    saved = waiting.pop(state, None) if state else None
    request.session[SESSION_KEY] = waiting  # a state is single-use
    if saved is None or time.time() - saved["at"] > oauth.STATE_TTL:
        raise Forbidden("this connection was not started here, or it expired: start it again from the channel")
    channel = Channel.objects.visible_to(request.user).filter(pk=saved["channel"]).first()
    if channel is None:
        raise NotFound("no such channel")
    target = f"/studio/distribution/channels/{channel.public_id}"
    if request.query_params.get("error"):
        reason = request.query_params.get("error_description") or request.query_params["error"]
        Channel.objects.filter(pk=channel.pk).update(last_error=f"LinkedIn: {reason}"[:1000])
        return HttpResponseRedirect(target)
    with service_errors():
        services.finish_connect(
            channel,
            code=request.query_params.get("code", ""),
            verifier=saved["verifier"],
            redirect_uri=redirect_uri(request),
        )
    return HttpResponseRedirect(f"{target}?connecting=1")


# ── posts: the queue ────────────────────────────────────────────────────────


class PostFilter(filters.FilterSet):
    channel = filters.UUIDFilter(field_name="channel__public_id")
    site = filters.NumberFilter(field_name="channel__site")
    status = filters.MultipleChoiceFilter(choices=DistributionPost.Status.choices, help_text="One or more statuses.")
    page = filters.NumberFilter(field_name="page_id")
    story = filters.UUIDFilter(field_name="story__public_id")

    class Meta:
        model = DistributionPost
        fields = ["channel", "site", "status", "page", "story"]


@extend_schema_view(
    list=extend_schema(summary="The queue: posts of the channels a person may see"),
    retrieve=extend_schema(summary="A post, with every blocker it meets now and LinkedIn's exact payload"),
    create=extend_schema(
        summary="Compose a post of a page or a story for a channel (a draft)",
        request=s.DistributionComposeSerializer,
        responses={201: s.DistributionPostDetailSerializer, **ERROR_RESPONSES},
    ),
    partial_update=extend_schema(
        summary="Change a post's text; an approved one goes back to draft",
        request=s.DistributionPostEditSerializer,
        responses={200: s.DistributionPostDetailSerializer, **ERROR_RESPONSES},
    ),
)
class DistributionPostViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    lookup_field = "public_id"
    permission_classes = [IsPerson]
    pagination_class = Paged
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = PostFilter
    http_method_names = ["get", "post", "patch", "delete"]
    queryset = DistributionPost.objects.select_related("channel", "page", "story", "created_by", "approved_by")

    def get_queryset(self):
        return self.queryset.visible_to(self.request.user)

    def get_serializer_class(self):
        return s.DistributionPostSerializer if self.action == "list" else s.DistributionPostDetailSerializer

    def respond(self, post, code=status.HTTP_200_OK):
        return Response(
            s.DistributionPostDetailSerializer(post, context=self.get_serializer_context()).data, status=code
        )

    def create(self, request, *args, **kwargs):
        body = s.DistributionComposeSerializer(data=request.data, context=self.get_serializer_context())
        body.is_valid(raise_exception=True)
        data = body.validated_data
        page = None
        if data.get("page") is not None:
            page = Page.objects.filter(pk=data["page"]).first()
            if page is None:
                raise Invalid("no such page", details=[{"field": "page", "code": "invalid", "message": "unknown"}])
        with service_errors():
            post = services.compose(
                data["channel"],
                user=request.user,
                page=page,
                story=data.get("story"),
                kind=data["kind"],
                commentary=data.get("commentary"),
                title=data.get("title"),
                description=data.get("description"),
            )
        return self.respond(post, status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        body = s.DistributionPostEditSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with service_errors():
            post = services.edit(self.get_object(), request.user, **body.validated_data)
        return self.respond(post)

    def perform_destroy(self, post):
        if post.status not in (DistributionPost.Status.DRAFT, DistributionPost.Status.REJECTED):
            raise Conflict(f"a {post.status} post stays in the record; only a draft or a rejected post is deleted")
        if not services.may_compose(post, self.request.user):
            raise Forbidden("you may not edit this page, so you may not delete its posts")
        post.delete()

    @extend_schema(
        request=None,
        responses={200: s.DistributionPostDetailSerializer, **ERROR_RESPONSES},
        summary="Approve a draft (a person who may publish its page); the brand guard's errors block it",
    )
    @action(detail=True, methods=["post"])
    def approve(self, request, public_id=None):
        with service_errors():
            return self.respond(services.approve(self.get_object(), request.user))

    @extend_schema(
        request=s.DistributionRejectSerializer,
        responses={200: s.DistributionPostDetailSerializer, **ERROR_RESPONSES},
        summary="Reject a post, with a reason",
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, public_id=None):
        body = s.DistributionRejectSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with service_errors():
            return self.respond(services.reject(self.get_object(), request.user, body.validated_data.get("reason", "")))

    @extend_schema(
        request=s.DistributionPublishSerializer,
        responses={202: s.DistributionPostDetailSerializer, **ERROR_RESPONSES},
        summary="Publish an approved post: 202, the worker sends it; 409 with every blocker when it may not go",
    )
    @action(detail=True, methods=["post"])
    def publish(self, request, public_id=None):
        body = s.DistributionPublishSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with service_errors():
            post = services.request_publish(self.get_object(), request.user, force=body.validated_data["force"])
        return self.respond(post, status.HTTP_202_ACCEPTED)

    @extend_schema(
        request=s.DistributionRecordSerializer,
        responses={200: s.DistributionPostDetailSerializer, **ERROR_RESPONSES},
        summary="Record a post a person found at the target (after an unconfirmed attempt, or made by hand)",
    )
    @action(detail=True, methods=["post"])
    def record(self, request, public_id=None):
        body = s.DistributionRecordSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        with service_errors():
            return self.respond(services.record_by_hand(self.get_object(), request.user, body.validated_data["urn"]))


# ── the ledger, with its statistics ─────────────────────────────────────────


class LedgerFilter(filters.FilterSet):
    channel = filters.UUIDFilter(field_name="channel__public_id")
    site = filters.NumberFilter(field_name="channel__site")
    state = filters.ChoiceFilter(choices=LEDGER_STATES)

    class Meta:
        model = LedgerEntry
        fields = ["channel", "site", "state"]


@extend_schema_view(
    list=extend_schema(
        summary="What has been published, keyed by canonical URL, with the latest statistics",
        parameters=[OpenApiParameter("ordering", OpenApiTypes.STR, description="-posted_at (default) or posted_at")],
    )
)
class DistributionLedgerViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsPerson]
    serializer_class = s.DistributionLedgerEntrySerializer
    pagination_class = Paged
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = LedgerFilter

    def get_queryset(self):
        rows = LedgerEntry.objects.filter(channel__in=Channel.objects.visible_to(self.request.user))
        order = "posted_at" if self.request.query_params.get("ordering") == "posted_at" else "-posted_at"
        return (
            rows.select_related("channel", "post")
            .prefetch_related(Prefetch("statistics", queryset=Statistic.objects.order_by("-day")))
            .order_by(order, "-id")
        )
