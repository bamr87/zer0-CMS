"""`/api/v2/ai/`: the AI content layer over REST (ADR 0006 decision 7).

Thin views: each validates, calls one function in `ai/services.py` and
serializes. Rows come from `visible_to(user, site)` only, so a row the
requester may not see is a 404; changing one is its owner's or staff's (a
403); running a visible assistant or pipeline is anyone's who can see it, and
so is applying a brief an agent asked for; configuring providers needs the
`ai.change_providerconfig` permission. Anything that reaches a model answers `202`
with the agent run, followed on `/api/v2/agent-runs/<id>/stream/`, and honours
an `Idempotency-Key` (a repeat within a day replays the first answer). Every
failure is the platform's error envelope (ops/errors.py).
"""

import functools
import hashlib
import json
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.filters import OrderingFilter
from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAdminUser, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page, Site

from ops.errors import Conflict, Invalid, NotFound
from ops.openapi import ERROR_RESPONSES

from . import serializers as s
from . import services
from .models import (
    Assistant,
    Brief,
    Conversation,
    IdempotencyKey,
    Message,
    ModelEntry,
    OutputSchema,
    Pipeline,
    ProviderConfig,
)

IDEMPOTENCY = OpenApiParameter(
    "Idempotency-Key",
    OpenApiTypes.STR,
    OpenApiParameter.HEADER,
    description="Send the same key again (within a day, same request) to get the first answer instead of a new run.",
)
SITE = OpenApiParameter(
    "site", OpenApiTypes.INT, description="Only rows of this Wagtail site and rows that belong to no site."
)


def idempotent(view):
    """Replay the stored answer to a repeated `Idempotency-Key`; a key reused
    with a different request is a conflict."""

    @functools.wraps(view)
    def wrapper(self, request, *args, **kwargs):
        key = request.headers.get("Idempotency-Key")
        if not key:
            return view(self, request, *args, **kwargs)
        if len(key) > 255:
            raise Invalid("Idempotency-Key is at most 255 characters")
        scope = f"{request.method} {request.path}"
        digest = hashlib.sha256(json.dumps(request.data, sort_keys=True, default=str).encode()).hexdigest()
        since = timezone.now() - timedelta(days=1)
        seen = IdempotencyKey.objects.filter(user=request.user, key=key, scope=scope, created_at__gte=since).first()
        if seen is not None:
            if seen.request_hash != digest:
                raise Conflict("this Idempotency-Key was sent with a different request", code="request.idempotency")
            return Response(seen.response, status=seen.status_code, headers={"Idempotent-Replayed": "true"})
        response = view(self, request, *args, **kwargs)
        if 200 <= response.status_code < 300:
            try:
                with transaction.atomic():
                    IdempotencyKey.objects.filter(created_at__lt=since).delete()
                    IdempotencyKey.objects.create(
                        user=request.user,
                        key=key,
                        scope=scope,
                        request_hash=digest,
                        status_code=response.status_code,
                        response=response.data,
                    )
            except IntegrityError as e:
                # The same key raced in: this request's work is rolled back with the error.
                raise Conflict("a request with this Idempotency-Key is in progress", code="request.idempotency") from e
        return response

    return wrapper


def accepted(**body) -> Response:
    return Response(body, status=status.HTTP_202_ACCEPTED)


def page_or_404(page_id):
    if page_id is None:
        return None
    page = Page.objects.filter(pk=page_id).first()
    if page is None:
        raise NotFound(f"no page {page_id}")
    return page.specific


class Paged(PageNumberPagination):
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class BySeq(CursorPagination):
    ordering = "seq"
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class CanEdit(BasePermission):
    """A visible row is readable (and, for `open_actions`, runnable — the
    service decides the rest); changing it is its owner's or staff's."""

    def has_object_permission(self, request, view, obj):
        if request.method in SAFE_METHODS or view.action in getattr(view, "open_actions", ()):
            return True
        return obj.can_edit(request.user)


class ConfiguresProviders(BasePermission):
    """Provider configuration: a person granted `ai.change_providerconfig` (superusers have every permission)."""

    def has_permission(self, request, view):
        return request.user.has_perm("ai.change_providerconfig")


@extend_schema_view(list=extend_schema(parameters=[SITE]))
class OwnedViewSet(viewsets.ModelViewSet):
    lookup_field = "public_id"
    permission_classes = [IsAuthenticated, CanEdit]
    pagination_class = Paged
    filter_backends = [filters.DjangoFilterBackend, OrderingFilter]
    ordering_fields = ["created_at", "updated_at"]
    open_actions: tuple[str, ...] = ()

    def get_queryset(self):
        site = None
        if self.action == "list" and self.request.query_params.get("site"):
            site = Site.objects.filter(pk=self.request.query_params["site"]).first()
            if site is None:
                return self.queryset.none()
        return self.queryset.visible_to(self.request.user, site)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    def perform_destroy(self, instance):
        try:
            instance.delete()
        except ProtectedError as e:
            raise Conflict(f"{instance} is in use: {', '.join(str(o) for o in e.protected_objects)}") from e


# ── providers and models ───────────────────────────────────────────────────


class ProviderFilter(filters.FilterSet):
    class Meta:
        model = ProviderConfig
        fields = ["enabled", "is_default"]


@extend_schema_view(
    list=extend_schema(summary="Providers (every adapter in the registry); configuration for those who configure them"),
    retrieve=extend_schema(summary="One provider"),
    update=extend_schema(summary="Configure a provider; the credential is write-only, and a new base URL drops it"),
    partial_update=extend_schema(
        summary="Configure a provider; the credential is write-only, and a new base URL drops it"
    ),
)
class ProviderViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet
):
    queryset = ProviderConfig.objects.all()
    serializer_class = s.ProviderSerializer
    lookup_field = "public_id"
    pagination_class = Paged
    filter_backends = [filters.DjangoFilterBackend, OrderingFilter]
    filterset_class = ProviderFilter
    ordering_fields = ["slug", "updated_at"]

    def get_permissions(self):
        reading = self.action in ("list", "retrieve")
        return [IsAuthenticated()] if reading else [IsAuthenticated(), ConfiguresProviders()]

    def get_queryset(self):
        return ProviderConfig.objects.visible_to(self.request.user)

    @extend_schema(
        summary="Check a provider's health: a one-word completion, as a run",
        request=None,
        parameters=[IDEMPOTENCY],
        responses={202: s.RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def test(self, request, public_id=None):
        return accepted(run=s.RunRefSerializer(services.check_health(self.get_object(), user=request.user)).data)

    @extend_schema(
        summary="Sync the provider's models into the catalog, as a run",
        request=None,
        parameters=[IDEMPOTENCY],
        responses={202: s.RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"], url_path="sync-models")
    @idempotent
    def sync_models(self, request, public_id=None):
        return accepted(run=s.RunRefSerializer(services.sync_models(self.get_object(), user=request.user)).data)

    @extend_schema(
        summary="Make this the default provider",
        request=None,
        responses={200: s.ProviderSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, public_id=None):
        row = services.set_default(self.get_object())
        return Response(s.ProviderSerializer(row, context=self.get_serializer_context()).data)


class ModelFilter(filters.FilterSet):
    provider = filters.CharFilter(field_name="provider__slug", help_text="A provider's slug.")

    class Meta:
        model = ModelEntry
        fields = ["provider", "active"]


@extend_schema_view(list=extend_schema(summary="The model catalog"), retrieve=extend_schema(summary="One model"))
class ModelEntryViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ModelEntry.objects.select_related("provider")
    serializer_class = s.ModelEntrySerializer
    lookup_field = "public_id"
    pagination_class = Paged
    filter_backends = [filters.DjangoFilterBackend, OrderingFilter]
    filterset_class = ModelFilter
    ordering_fields = ["model_id", "synced_at"]

    def get_queryset(self):
        return self.queryset.visible_to(self.request.user)


# ── output schemas, assistants, pipelines ──────────────────────────────────


@extend_schema_view(
    create=extend_schema(summary="Create a schema — or import one: post the document `export/` returned")
)
class OutputSchemaViewSet(OwnedViewSet):
    queryset = OutputSchema.objects.select_related("owner")
    serializer_class = s.OutputSchemaSerializer
    filterset_fields = ["visibility", "bundled"]
    ordering_fields = ["name", "created_at", "updated_at"]

    @extend_schema(summary="Export a schema with its render template", responses={200: s.OutputSchemaExportSerializer})
    @action(detail=True, methods=["get"])
    def export(self, request, public_id=None):
        return Response(s.OutputSchemaExportSerializer(self.get_object()).data)

    @extend_schema(
        summary="Create the bundled schemas and assistant that do not exist yet (staff)",
        request=None,
        responses={200: s.BundledImportSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"], url_path="import-bundled", permission_classes=[IsAdminUser])
    def import_bundled(self, request):
        found = services.import_bundled()
        return Response(
            {
                "schemas": [row.public_id for row in found["schemas"]],
                "assistants": [row.public_id for row in found["assistants"]],
            }
        )


class AssistantFilter(filters.FilterSet):
    provider = filters.CharFilter(field_name="provider__slug")
    output_schema = filters.UUIDFilter(field_name="output_schema__public_id")

    class Meta:
        model = Assistant
        fields = ["visibility", "provider", "output_schema"]


class AssistantViewSet(OwnedViewSet):
    queryset = Assistant.objects.select_related("owner", "provider", "model", "output_schema")
    serializer_class = s.AssistantSerializer
    filterset_class = AssistantFilter
    ordering_fields = ["name", "created_at", "updated_at"]
    open_actions = ("run",)

    @extend_schema(
        summary="Run the assistant on a prompt; follow the run for its answer",
        request=s.RunAssistantSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def run(self, request, public_id=None):
        body = s.RunAssistantSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = services.run_assistant(
            self.get_object(),
            user=request.user,
            prompt=body.validated_data["prompt"],
            page=page_or_404(body.validated_data.get("page_id")),
        )
        return accepted(run=s.RunRefSerializer(run).data)

    @extend_schema(summary="The assistant as a portable document", responses={200: s.AssistantDocumentSerializer})
    @action(detail=True, methods=["get"])
    def export(self, request, public_id=None):
        return Response(services.export_assistant(self.get_object()))

    @extend_schema(
        summary="A new private assistant (and its output schema) from an exported document",
        request=s.AssistantDocumentSerializer,
        responses={201: s.AssistantSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"], url_path="import")
    def import_document(self, request):
        body = s.AssistantDocumentSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        assistant = services.import_assistant(body.validated_data, user=request.user)
        return Response(s.AssistantSerializer(assistant, context=self.get_serializer_context()).data, status=201)


class PipelineViewSet(OwnedViewSet):
    queryset = Pipeline.objects.select_related("owner").prefetch_related("steps__assistant")
    serializer_class = s.PipelineSerializer
    filterset_fields = ["visibility"]
    ordering_fields = ["name", "created_at", "updated_at"]
    open_actions = ("run",)

    @extend_schema(
        summary="Run the pipeline: a parent run with one child run per step",
        request=s.RunPipelineSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def run(self, request, public_id=None):
        body = s.RunPipelineSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = services.run_pipeline(
            self.get_object(),
            user=request.user,
            prompt=body.validated_data["prompt"],
            page=page_or_404(body.validated_data.get("page_id")),
        )
        return accepted(run=s.RunRefSerializer(run).data)


# ── briefs ─────────────────────────────────────────────────────────────────


class BriefFilter(filters.FilterSet):
    assistant = filters.UUIDFilter(field_name="assistant__public_id")
    conversation = filters.UUIDFilter(field_name="conversation__public_id")

    class Meta:
        model = Brief
        fields = ["status", "visibility", "assistant", "conversation"]


class BriefViewSet(OwnedViewSet):
    queryset = Brief.objects.select_related(
        "owner", "assistant", "pipeline", "output_schema", "conversation", "source_message", "run"
    )
    serializer_class = s.BriefSerializer
    filterset_class = BriefFilter
    ordering_fields = ["created_at", "updated_at", "status"]
    open_actions = ("apply",)  # the service lets the owner, staff, or anyone shown an agent's brief apply it

    @extend_schema(
        summary="Generate: a structured result, rendered, then its metadata — as a run",
        request=None,
        parameters=[IDEMPOTENCY],
        responses={202: s.BriefRunSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def generate(self, request, public_id=None):
        brief = self.get_object()
        run = services.generate_brief(brief, user=request.user)
        return accepted(
            brief=s.BriefSerializer(brief, context=self.get_serializer_context()).data, run=s.RunRefSerializer(run).data
        )

    @extend_schema(
        summary="Apply a ready brief (yours, or one an agent asked for): a draft page, its text as suggestions to "
        "accept (never published)",
        request=s.ApplyBriefSerializer,
        responses={201: s.AppliedBriefSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    def apply(self, request, public_id=None):
        body = s.ApplyBriefSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        brief = self.get_object()
        page, suggestions = services.apply_brief(
            brief,
            user=request.user,
            parent=page_or_404(body.validated_data.get("parent")),
            page_type=body.validated_data.get("page_type", ""),
        )
        brief.refresh_from_db()
        return Response(
            {
                "brief": s.BriefSerializer(brief, context=self.get_serializer_context()).data,
                "page_id": page.pk,
                "suggestions": [suggestion.pk for suggestion in suggestions],
            },
            status=status.HTTP_201_CREATED,
        )


# ── conversations and messages ─────────────────────────────────────────────


class ConversationFilter(filters.FilterSet):
    assistant = filters.UUIDFilter(field_name="assistant__public_id")
    page_id = filters.NumberFilter(field_name="page", help_text="Conversations about this page.")

    class Meta:
        model = Conversation
        fields = ["visibility", "assistant", "page_id"]


class ConversationViewSet(OwnedViewSet):
    queryset = Conversation.objects.select_related("owner", "assistant", "pipeline")
    serializer_class = s.ConversationSerializer
    filterset_class = ConversationFilter
    ordering_fields = ["created_at", "updated_at", "title"]

    def _assistant(self, public_id):
        if public_id is None:
            return None
        found = Assistant.objects.visible_to(self.request.user).filter(public_id=public_id).first()
        if found is None:
            raise NotFound(f"no assistant {public_id}")
        return found

    def perform_create(self, serializer):
        brief = serializer.validated_data.pop("from_brief", None)
        conversation = serializer.save(owner=self.request.user)
        if brief is not None:
            services.converse_about(conversation, brief, link=brief.can_edit(self.request.user))

    @extend_schema(
        methods=["GET"],
        summary="The conversation's messages, oldest first (cursor-paginated)",
        parameters=[
            OpenApiParameter("role", OpenApiTypes.STR, enum=[r for r, _ in Message.ROLES]),
            OpenApiParameter("status", OpenApiTypes.STR, enum=[st for st, _ in Message.STATUSES]),
        ],
        responses={200: s.MessageSerializer(many=True), **ERROR_RESPONSES},
    )
    @extend_schema(
        methods=["POST"],
        summary="Post a message; with an assistant its reply is queued as a run",
        request=s.PostMessageSerializer,
        parameters=[IDEMPOTENCY],
        responses={201: s.MessagePostedSerializer, 202: s.MessagePostedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get", "post"], pagination_class=BySeq, filter_backends=[])
    def messages(self, request, public_id=None):
        conversation = self.get_object()
        if request.method == "POST":
            return self._post(request, conversation)
        messages = conversation.messages.select_related("assistant", "run", "conversation")
        for field in ("role", "status"):
            if request.query_params.get(field):
                messages = messages.filter(**{field: request.query_params[field]})
        page = self.paginate_queryset(messages)
        return self.get_paginated_response(
            s.MessageSerializer(page, many=True, context=self.get_serializer_context()).data
        )

    @idempotent
    def _post(self, request, conversation):
        body = s.PostMessageSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        message, answer, run = services.post_message(
            conversation,
            user=request.user,
            text=body.validated_data["text"],
            assistant=self._assistant(body.validated_data.get("assistant")),
            answer=body.validated_data["answer"],
        )
        context = self.get_serializer_context()
        data = {
            "message": s.MessageSerializer(message, context=context).data,
            "reply": s.MessageSerializer(answer, context=context).data if answer else None,
            "run": s.RunRefSerializer(run).data if run else None,
        }
        return Response(data, status=status.HTTP_202_ACCEPTED if run else status.HTTP_201_CREATED)

    @extend_schema(
        summary="Run a pipeline on the conversation: each step replies in turn",
        request=s.RunPipelineSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.RunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"], url_path="run-pipeline")
    @idempotent
    def run_pipeline(self, request, public_id=None):
        conversation = self.get_object()
        if conversation.pipeline is None:
            raise Invalid("the conversation has no pipeline")
        body = s.RunPipelineSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        run = services.run_pipeline(
            conversation.pipeline,
            user=request.user,
            prompt=body.validated_data["prompt"],
            conversation=conversation,
        )
        return accepted(run=s.RunRefSerializer(run).data)


@extend_schema_view(
    retrieve=extend_schema(summary="One message"),
    partial_update=extend_schema(summary="Assign the assistant that answers a re-run"),
    destroy=extend_schema(summary="Delete a message from its conversation"),
)
class MessageViewSet(
    mixins.RetrieveModelMixin, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    queryset = Message.objects.select_related("conversation", "assistant", "run")
    serializer_class = s.MessageSerializer
    lookup_field = "public_id"
    permission_classes = [IsAuthenticated, CanEdit]
    http_method_names = ["get", "patch", "post", "delete"]

    def get_queryset(self):
        return self.queryset.visible_to(self.request.user)

    @extend_schema(
        summary="Ask again: a new reply from the message's assistant (or another)",
        request=s.RerunSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.MessageRunSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def rerun(self, request, public_id=None):
        body = s.RerunSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        assistant = None
        if body.validated_data.get("assistant"):
            assistant = (
                Assistant.objects.visible_to(request.user).filter(public_id=body.validated_data["assistant"]).first()
            )
            if assistant is None:
                raise NotFound(f"no assistant {body.validated_data['assistant']}")
        answer, run = services.rerun(self.get_object(), user=request.user, assistant=assistant)
        context = self.get_serializer_context()
        return accepted(message=s.MessageSerializer(answer, context=context).data, run=s.RunRefSerializer(run).data)

    @extend_schema(
        summary="Promote a message to a brief (201) or a draft (202: the metadata step is queued)",
        request=s.PromoteSerializer,
        parameters=[IDEMPOTENCY],
        responses={201: s.BriefRunSerializer, 202: s.BriefRunSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def promote(self, request, public_id=None):
        body = s.PromoteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        brief, run = services.promote(
            self.get_object(),
            user=request.user,
            to=body.validated_data["to"],
            parent=page_or_404(body.validated_data.get("parent")),
            page_type=body.validated_data.get("page_type", ""),
        )
        data = {
            "brief": s.BriefSerializer(brief, context=self.get_serializer_context()).data,
            "run": s.RunRefSerializer(run).data if run else None,
        }
        return Response(data, status=status.HTTP_202_ACCEPTED if run else status.HTTP_201_CREATED)
