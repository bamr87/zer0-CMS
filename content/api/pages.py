"""The studio's content endpoints: sites, pages, revisions and publishing.

    GET   /api/v2/sites/                                  the sites a person can work in
    GET   /api/v2/content/types/                          every page type, for filters
    GET   /api/v2/content/pages/                          pages across sites, any status, filtered and paginated
    POST  /api/v2/content/pages/                          a new page under a parent, as a draft
    GET   /api/v2/content/pages/<id>/                     the latest revision: fields, blocks, Markdown, status
    PATCH /api/v2/content/pages/<id>/                     save a draft revision (never publishes)
    GET   /api/v2/content/pages/<id>/types/               the page types the person may create under it
    POST  /api/v2/content/pages/<id>/publish/             publish the latest revision now
    POST  /api/v2/content/pages/<id>/unpublish/
    POST  /api/v2/content/pages/<id>/schedule/            publish the latest revision at `go_live_at`
    POST  /api/v2/content/pages/<id>/unschedule/
    GET   /api/v2/content/pages/<id>/revisions/           newest first
    GET   /api/v2/content/pages/<id>/revisions/compare/   two revisions side by side, for a diff
    POST  /api/v2/content/pages/<id>/revisions/<rev>/revert/   a new draft with that revision's content

Views validate, call `cms.services` and serialize (api/serializers.py). They
serve people only: an agent changes content through the tool registry and
the accept flow, never through these (content/AGENTS.md). A session request
needs the CSRF token, page access follows Wagtail's page permissions, and
every failure is the envelope (ops/errors.py).
"""

from contextlib import contextmanager
from datetime import datetime
from functools import cache

import django_filters
from django.apps import apps
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import models
from django.db.models import Q
from django.urls import reverse
from django.utils.text import capfirst
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from wagtail.models import Page, Site, get_page_models

from cms import services
from importers.markdown import from_blocks
from ops.errors import Conflict, Forbidden, Invalid, NotFound
from ops.openapi import ERROR_RESPONSES
from suggestions.services import pending_for

from .serializers import (
    PageCreateSerializer,
    PageDetailSerializer,
    PageSummarySerializer,
    PageTypeSerializer,
    PageUpdateSerializer,
    RevisionCompareSerializer,
    RevisionSerializer,
    ScheduleSerializer,
    SiteSerializer,
)

SEO = {"slug", "seo_title", "search_description", "ai_summary", "ai_keywords"}
SETTINGS = {"agent_policy"}


class IsPerson(BasePermission):
    """Signed in, and not an agent principal."""

    message = "this endpoint is for people; an agent changes content through the tool registry"

    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and not user.username.startswith("agent:"))


class StudioPagination(PageNumberPagination):
    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 100


def _details(error: ValidationError) -> list[dict]:
    found = error.message_dict if hasattr(error, "error_dict") else {None: error.messages}
    return [{"field": field, "code": "invalid", "message": m} for field, messages in found.items() for m in messages]


@contextmanager
def service_errors():
    """A service's exceptions as the envelope's: 403, 422 with details, 409."""
    try:
        yield
    except PermissionDenied as e:
        raise Forbidden(str(e) or "forbidden") from e
    except ValidationError as e:
        raise Invalid("validation failed", details=_details(e)) from e
    except services.StaleRevision as e:
        raise Conflict(str(e)) from e


def _valid(serializer_class, request) -> dict:
    serializer = serializer_class(data=request.data)
    serializer.is_valid(raise_exception=True)
    return serializer.validated_data


def _page(request, pk):
    if not services.visible_pages(request.user).filter(pk=pk).exists():
        raise NotFound(f"no page {pk}")
    return Page.objects.get(pk=pk).specific


# ── reading a page ─────────────────────────────────────────────────────────


def status_of(page) -> str:
    """One word for where a page stands; `STATUS_FILTERS` selects the same sets."""
    if page.expired and not page.live:
        return "expired"
    if page.approved_schedule:
        return "scheduled"
    if not page.live:
        return "draft"
    return "changed" if page.has_unpublished_changes else "live"


STATUS_FILTERS = {
    "draft": Q(live=False, expired=False, _approved_schedule=False),
    "live": Q(live=True, has_unpublished_changes=False, _approved_schedule=False),
    "changed": Q(live=True, has_unpublished_changes=True, _approved_schedule=False),
    "scheduled": Q(_approved_schedule=True),
    "expired": Q(live=False, expired=True),
}


def summary(page) -> dict:
    model = page.specific_class or type(page)
    return {
        "id": page.pk,
        "title": page.get_admin_display_title(),
        "slug": page.slug,
        "type": model._meta.label,
        "type_label": capfirst(model._meta.verbose_name),
        "status": status_of(page),
        "live": page.live,
        "has_unpublished_changes": page.has_unpublished_changes,
        "locked": page.locked,
        "url_path": page.url_path,
        "depth": page.depth,
        "children": page.numchild,
        "go_live_at": page.go_live_at,
        "latest_revision_created_at": page.latest_revision_created_at,
        "last_published_at": page.last_published_at,
    }


def read_fields(page) -> dict:
    """The editor fields' values, as JSON: tags as names, relations as id strings."""
    out = {}
    for name in services.editable_fields(type(page)):
        field = page._meta.get_field(name)
        if name == "tags":
            out[name] = sorted(t.name for t in page.tags.all())
        elif field.many_to_many:
            out[name] = sorted(str(o.pk) for o in getattr(page, name).all())
        else:
            value = getattr(page, name)
            out[name] = value.isoformat() if isinstance(value, datetime) else value
    return out


@cache
def _spec(model, name) -> dict:
    field = model._meta.get_field(name)
    choices = [{"value": str(v), "label": str(label)} for v, label in (field.choices or [])]
    if name in ("tags", "ai_keywords"):
        kind = "tags"
    elif field.many_to_many:
        kind = "multichoice"
    elif choices:
        kind = "choice"
    elif isinstance(field, models.DateTimeField):
        kind = "datetime"
    elif isinstance(field, models.IntegerField):
        kind = "integer"
    elif isinstance(field, models.TextField):
        kind = "textarea"
    else:
        kind = "text"
    return {
        "name": name,
        "label": capfirst(str(field.verbose_name)),
        "group": "seo" if name in SEO else "settings" if name in SETTINGS else "content",
        "kind": kind,
        "required": not field.blank,
        "help_text": str(field.help_text or ""),
        "max_length": getattr(field, "max_length", None),
        "choices": choices,
    }


def field_specs(model) -> list[dict]:
    specs = []
    for name in services.editable_fields(model):
        spec = _spec(model, name)
        if spec["kind"] == "multichoice":  # a relation's choices are rows, read per request
            related = model._meta.get_field(name).related_model
            spec = {**spec, "choices": [{"value": str(o.pk), "label": str(o)} for o in related.objects.all()]}
        specs.append(spec)
    return specs


def _revision_ref(revision):
    if revision is None:
        return None
    return {"id": revision.pk, "created_at": revision.created_at, "user": str(revision.user) if revision.user else None}


def detail(page, user) -> dict:
    draft = page.get_latest_revision_as_object()
    perms = page.permissions_for_user(user)
    parent = page.get_parent()
    site = page.get_site()
    body = list(draft.body.get_prep_value())
    return {
        **summary(page),
        "title": draft.title,
        "slug": draft.slug,
        "parent": {"id": parent.pk, "title": parent.get_admin_display_title()} if parent and parent.depth > 1 else None,
        "site_id": site.pk if site else None,
        "expire_at": draft.expire_at,
        "first_published_at": page.first_published_at,
        "latest_revision": _revision_ref(page.get_latest_revision()),
        "live_revision_id": page.live_revision_id,
        "fields": read_fields(draft),
        "field_specs": field_specs(type(page)),
        "body": body,
        "markdown": from_blocks(body, leading=""),
        "permissions": {
            "edit": perms.can_edit(),
            "publish": perms.can_publish(),
            "unpublish": perms.can_unpublish(),
            "add_subpage": perms.can_add_subpage(),
            "delete": perms.can_delete(),
        },
        "pending_suggestions": pending_for(page).count(),
        "preview_url": reverse("wagtailadmin_pages:view_draft", args=[page.pk]),
        "live_url": page.get_url() if page.live else None,
    }


def _detail_response(request, pk, code=status.HTTP_200_OK):
    page = _page(request, pk)
    return Response(PageDetailSerializer(detail(page, request.user)).data, status=code)


# ── sites ──────────────────────────────────────────────────────────────────


@extend_schema(operation_id="sites_list", responses={200: SiteSerializer(many=True), **ERROR_RESPONSES})
@api_view(["GET"])
@permission_classes([IsPerson])
def sites(request):
    rows = Site.objects.filter(root_page__in=services.visible_pages(request.user)).order_by("site_name", "hostname")
    data = [
        {
            "id": s.pk,
            "name": s.site_name or s.hostname,
            "hostname": s.hostname,
            "port": s.port,
            "is_default": s.is_default_site,
            "root_page_id": s.root_page_id,
        }
        for s in rows
    ]
    return Response(SiteSerializer(data, many=True).data)


# ── pages ──────────────────────────────────────────────────────────────────


def page_type_choices():
    return [(m._meta.label, capfirst(m._meta.verbose_name)) for m in get_page_models() if m is not Page]


class PageFilter(django_filters.FilterSet):
    site = django_filters.NumberFilter(method="by_site", help_text="A site id: the pages of that site.")
    parent = django_filters.NumberFilter(method="by_parent", help_text="A page id: its children.")
    type = django_filters.ChoiceFilter(choices=page_type_choices, method="by_type")
    status = django_filters.ChoiceFilter(choices=[(s, s) for s in STATUS_FILTERS], method="by_status")
    q = django_filters.CharFilter(method="by_text", help_text="Text in the title or the slug.")
    can_have_children = django_filters.BooleanFilter(method="by_children", help_text="Only pages that take children.")

    # The `value` type hints are what the OpenAPI document reads for each parameter.
    def by_site(self, qs, name, value: int):
        site = Site.objects.filter(pk=value).select_related("root_page").first()
        return qs.descendant_of(site.root_page, inclusive=True) if site else qs.none()

    def by_parent(self, qs, name, value: int):
        parent = Page.objects.filter(pk=value).first()
        return qs.child_of(parent) if parent else qs.none()

    def by_type(self, qs, name, value: str):
        return qs.type(apps.get_model(value))

    def by_status(self, qs, name, value: str):
        return qs.filter(STATUS_FILTERS[value])

    def by_text(self, qs, name, value: str):
        return qs.filter(Q(title__icontains=value) | Q(draft_title__icontains=value) | Q(slug__icontains=value))

    def by_children(self, qs, name, value: bool):
        parents = [m for m in get_page_models() if m is not Page and m.creatable_subpage_models()]
        return qs.type(*parents) if value else qs.not_type(*parents)


class PageList(generics.ListAPIView):
    permission_classes = [IsPerson]
    serializer_class = PageSummarySerializer
    pagination_class = StudioPagination
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = PageFilter
    ordering_fields = ["title", "latest_revision_created_at", "last_published_at", "path"]
    ordering = ["-latest_revision_created_at", "path"]

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return Page.objects.none()
        return services.visible_pages(self.request.user).select_related("content_type").annotate_approved_schedule()

    @extend_schema(operation_id="content_pages_list", summary="Pages across sites, any status")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        rows = self.paginate_queryset(self.filter_queryset(self.get_queryset()))
        return self.get_paginated_response(PageSummarySerializer([summary(p) for p in rows], many=True).data)

    @extend_schema(
        operation_id="content_pages_create",
        summary="A new page under a parent, as a draft revision",
        request=PageCreateSerializer,
        responses={201: PageDetailSerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        data = _valid(PageCreateSerializer, request)
        parent = _page(request, data["parent"])
        try:
            model = apps.get_model(data["type"])
        except (LookupError, ValueError) as e:
            raise Invalid("unknown page type", details=[{"field": "type", "code": "invalid", "message": str(e)}]) from e
        with service_errors():
            page = services.create_draft(parent, model, request.user, fields=data["fields"], body=data.get("body"))
        return _detail_response(request, page.pk, status.HTTP_201_CREATED)


@extend_schema(
    methods=["GET"],
    operation_id="content_pages_retrieve",
    summary="A page's latest revision",
    responses={200: PageDetailSerializer, **ERROR_RESPONSES},
)
@extend_schema(
    methods=["PATCH"],
    operation_id="content_pages_save",
    summary="Save a draft revision (never publishes)",
    request=PageUpdateSerializer,
    responses={200: PageDetailSerializer, **ERROR_RESPONSES},
)
@api_view(["GET", "PATCH"])
@permission_classes([IsPerson])
def page_detail(request, pk):
    if request.method == "PATCH":
        data = _valid(PageUpdateSerializer, request)
        page = _page(request, pk)
        with service_errors():
            services.save_changes(
                page,
                request.user,
                fields=data.get("fields") or {},
                body=data.get("body"),
                base_revision_id=data.get("base_revision_id"),
            )
    return _detail_response(request, pk)


@extend_schema(
    operation_id="content_types_list",
    summary="Every page type, for filters",
    responses={200: PageTypeSerializer(many=True), **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def all_types(request):
    data = [{"type": label, "label": name} for label, name in page_type_choices()]
    return Response(PageTypeSerializer(data, many=True).data)


@extend_schema(
    operation_id="content_pages_types",
    summary="The page types the caller may create under this page",
    responses={200: PageTypeSerializer(many=True), **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def page_types(request, pk):
    parent = _page(request, pk)
    found = services.creatable_types(parent, request.user)
    data = [{"type": m._meta.label, "label": capfirst(m._meta.verbose_name)} for m in found]
    return Response(PageTypeSerializer(data, many=True).data)


def _action(operation_id, summary_text, request_serializer=None):
    return extend_schema(
        operation_id=operation_id,
        summary=summary_text,
        request=request_serializer,
        responses={200: PageDetailSerializer, **ERROR_RESPONSES},
    )


@_action("content_pages_publish", "Publish the latest revision now")
@api_view(["POST"])
@permission_classes([IsPerson])
def publish(request, pk):
    page = _page(request, pk)
    with service_errors():
        services.publish_now(page, request.user)
    return _detail_response(request, pk)


@_action("content_pages_unpublish", "Take the page down")
@api_view(["POST"])
@permission_classes([IsPerson])
def unpublish(request, pk):
    page = _page(request, pk)
    with service_errors():
        services.unpublish(page, request.user)
    return _detail_response(request, pk)


@_action("content_pages_schedule", "Publish the latest revision at `go_live_at`", ScheduleSerializer)
@api_view(["POST"])
@permission_classes([IsPerson])
def schedule(request, pk):
    data = _valid(ScheduleSerializer, request)
    page = _page(request, pk)
    with service_errors():
        services.schedule(page, request.user, data["go_live_at"], data.get("expire_at"))
    return _detail_response(request, pk)


@_action("content_pages_unschedule", "Cancel a scheduled publish")
@api_view(["POST"])
@permission_classes([IsPerson])
def unschedule(request, pk):
    page = _page(request, pk)
    with service_errors():
        services.unschedule(page, request.user)
    return _detail_response(request, pk)


# ── revisions ──────────────────────────────────────────────────────────────


class RevisionList(generics.ListAPIView):
    permission_classes = [IsPerson]
    serializer_class = RevisionSerializer
    pagination_class = StudioPagination

    @extend_schema(operation_id="content_pages_revisions", summary="A page's revisions, newest first")
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)

    def list(self, request, pk):
        page = _page(request, pk)
        rows = self.paginate_queryset(page.revisions.select_related("user").order_by("-created_at", "-id"))
        data = [
            {
                **_revision_ref(r),
                "approved_go_live_at": r.approved_go_live_at,
                "is_live": r.pk == page.live_revision_id,
                "is_latest": r.pk == page.latest_revision_id,
            }
            for r in rows
        ]
        return self.get_paginated_response(RevisionSerializer(data, many=True).data)


def _snapshot(revision) -> dict:
    obj = revision.as_object()
    body = list(obj.body.get_prep_value())
    return {
        **_revision_ref(revision),
        "fields": read_fields(obj),
        "body": body,
        "markdown": from_blocks(body, leading=""),
    }


@extend_schema(
    operation_id="content_pages_revisions_compare",
    summary="Two revisions side by side, for a diff",
    parameters=[
        OpenApiParameter("a", int, required=True, description="The older revision's id."),
        OpenApiParameter("b", int, required=True, description="The newer revision's id."),
    ],
    responses={200: RevisionCompareSerializer, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsPerson])
def compare(request, pk):
    page = _page(request, pk)
    found = {}
    for side in ("a", "b"):
        raw = request.query_params.get(side, "")
        revision = page.revisions.filter(pk=raw).first() if raw.isdigit() else None
        if revision is None:
            raise NotFound(f"page {pk} has no revision {raw!r}")
        found[side] = _snapshot(revision)
    a, b = found["a"], found["b"]
    changed = [name for name in a["fields"] if a["fields"][name] != b["fields"].get(name)]
    strip = lambda blocks: [(x["type"], x["value"]) for x in blocks]  # noqa: E731 — ids are not content
    if strip(a["body"]) != strip(b["body"]):
        changed.append("body")
    return Response(RevisionCompareSerializer({"a": a, "b": b, "changed": changed}).data)


@_action("content_pages_revisions_revert", "A new draft revision with an old revision's content")
@api_view(["POST"])
@permission_classes([IsPerson])
def revert(request, pk, revision_id):
    page = _page(request, pk)
    revision = page.revisions.filter(pk=revision_id).first()
    if revision is None:
        raise NotFound(f"page {pk} has no revision {revision_id}")
    with service_errors():
        services.revert(page, revision, request.user)
    return _detail_response(request, pk)
