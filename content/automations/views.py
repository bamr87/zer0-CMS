"""`/api/v2/automations/`: automations over REST (automations/README.md).

    /                       list (filters enabled, visibility, kind; `site`), create — paused, its secret shown once
    <id>/                   one automation with its last run; PATCH; DELETE
    <id>/enable/            start it (checked again first); <id>/disable/ pauses it (its owner, or staff)
    <id>/test/              fire it now with a sample payload, paused or not: a real run (202)
    <id>/dry-run/           what it would do with a sample payload, doing nothing
    <id>/export/            the automation as a YAML document; import/ makes a new one from such a document
    <id>/rotate-secret/     a new secret, shown once
    <id>/webhook/           a webhook trigger's endpoint: no session or token — its HMAC signature is the credential
    condition/              a condition tried against a sample payload, as the editor types it
    options/                the events, stages and agents to pick from, and a sample payload per trigger
    runs/                   the runs of the person's own automations — every one, for staff — (filters automation,
                            status, trigger), by cursor, newest first; runs/<id>/ one run with its payload and each
                            action's outcome: what an automation heard, it heard as its owner

Thin views: validate, call automations/services.py, serialize. People only (`IsPerson`): an agent fires a named hook
through the tool registry instead. Rows come from `visible_to` alone, so one the person cannot see is a 404; an
automation runs as its owner, so changing, enabling, testing or re-keying it is its owner's (or a superuser's) — 403
for anyone else — while staff may pause one. Every failure is the error envelope.
"""

from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status, viewsets
from rest_framework.decorators import action, api_view, authentication_classes, permission_classes
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ai.views import IDEMPOTENCY, CanEdit, OwnedViewSet, idempotent
from api.pages import IsPerson
from ops.errors import NotFound
from ops.openapi import ERROR_RESPONSES

from . import serializers as s
from . import services, spec
from .models import Automation, AutomationRun

UUID = "[0-9a-fA-F-]{36}"


def valid(serializer_class, request) -> dict:
    body = serializer_class(data=request.data, context={"request": request})
    body.is_valid(raise_exception=True)
    return body.validated_data


class AutomationFilter(filters.FilterSet):
    kind = filters.ChoiceFilter(
        choices=[(k, k) for k in spec.TRIGGERS], method="by_kind", help_text="Only automations this kind fires."
    )

    class Meta:
        model = Automation
        fields = ["enabled", "visibility", "kind"]

    def by_kind(self, rows, name, value):
        return rows.filter(trigger__kind=value)


@extend_schema_view(
    create=extend_schema(summary="Create an automation — paused until enabled; its secret is in this answer only"),
    partial_update=extend_schema(summary="Change an automation (its owner's): it keeps running or stays paused"),
)
class AutomationViewSet(OwnedViewSet):
    queryset = Automation.objects.select_related("owner", "last_run")
    serializer_class = s.AutomationSerializer
    permission_classes = [IsPerson, CanEdit]
    filterset_class = AutomationFilter
    ordering_fields = ["name", "created_at", "updated_at"]
    lookup_value_regex = UUID
    http_method_names = ["get", "post", "patch", "delete"]
    open_actions = ("disable",)  # staff may pause anyone's: the service decides

    def _out(self, automation, code=status.HTTP_200_OK):
        return Response(s.AutomationSerializer(automation, context=self.get_serializer_context()).data, status=code)

    @extend_schema(
        summary="Enable it: checked again, then it runs",
        request=None,
        responses={200: s.AutomationSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    def enable(self, request, public_id=None):
        return self._out(services.enable(self.get_object(), user=request.user))

    @extend_schema(
        summary="Pause it (its owner, or staff)",
        request=None,
        responses={200: s.AutomationSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    def disable(self, request, public_id=None):
        return self._out(services.disable(self.get_object(), user=request.user))

    @extend_schema(
        summary="Fire it now with a sample payload, paused or not — a real run, followed in its runs",
        request=s.AutomationPayloadSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.AutomationRunSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def test(self, request, public_id=None):
        run = services.test(
            self.get_object(), valid(s.AutomationPayloadSerializer, request)["payload"], user=request.user
        )
        return Response(s.AutomationRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="What it would do with a sample payload — the condition's verdict, each action rendered — doing nothing",
        request=s.AutomationPayloadSerializer,
        responses={200: s.AutomationDryRunSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"], url_path="dry-run")
    def dry_run(self, request, public_id=None):
        automation = services.changing(self.get_object(), request.user)
        return Response(services.dry_run(automation, valid(s.AutomationPayloadSerializer, request)["payload"]))

    @extend_schema(
        summary="The automation as a YAML document", responses={200: s.AutomationYamlSerializer, **ERROR_RESPONSES}
    )
    @action(detail=True, methods=["get"])
    def export(self, request, public_id=None):
        automation = self.get_object()
        return Response({"name": automation.name, "yaml": services.export_yaml(automation)})

    @extend_schema(
        summary="A new automation from a YAML document — yours, private, paused, with a secret of its own",
        request=s.AutomationImportSerializer,
        responses={201: s.AutomationSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"], url_path="import")
    def import_document(self, request):
        automation = services.import_yaml(valid(s.AutomationImportSerializer, request)["yaml"], user=request.user)
        return self._out(automation, status.HTTP_201_CREATED)

    @extend_schema(
        summary="A new secret for its webhooks, shown this once",
        request=None,
        responses={200: s.AutomationSecretSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"], url_path="rotate-secret")
    def rotate_secret(self, request, public_id=None):
        return Response({"secret": services.rotate_secret(self.get_object(), user=request.user)})

    @extend_schema(
        summary="A condition tried against a sample payload",
        request=s.AutomationConditionSerializer,
        responses={200: s.AutomationVerdictSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"], pagination_class=None, filter_backends=[])
    def condition(self, request):
        body = valid(s.AutomationConditionSerializer, request)
        return Response(spec.evaluate(body["condition"], body["payload"]))

    @extend_schema(
        summary="What an automation may pick from, and a sample payload per trigger",
        responses={200: s.AutomationOptionsSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["get"], pagination_class=None, filter_backends=[])
    def options(self, request):
        return Response(services.options())


@extend_schema(
    summary="A webhook trigger: fire the automation (no session or token: the request is signed with its secret)",
    request=OpenApiTypes.OBJECT,
    parameters=[
        OpenApiParameter(
            "X-Zer0-Signature-256",
            OpenApiTypes.STR,
            OpenApiParameter.HEADER,
            description="`sha256=` and the hex HMAC-SHA256 of the raw body with the automation's secret "
            "(GitHub's `X-Hub-Signature-256` is read the same way).",
        ),
        OpenApiParameter(
            "X-Zer0-Delivery",
            OpenApiTypes.STR,
            OpenApiParameter.HEADER,
            description="A delivery's id (or GitHub's `X-GitHub-Delivery`): sent again, it gets the run it made.",
        ),
    ],
    responses={202: s.AutomationWebhookAcceptedSerializer, **ERROR_RESPONSES},
    auth=[],
)
@api_view(["POST"])
@authentication_classes([])
@permission_classes([AllowAny])
def webhook(request, public_id):
    automation = Automation.objects.filter(public_id=public_id, trigger__kind="webhook").first()
    if automation is None:
        raise NotFound("no automation has a webhook here")
    run = services.receive_webhook(automation, request.body, request.headers)
    return Response({"run": run.public_id, "status": run.status}, status=status.HTTP_202_ACCEPTED)


class Newest(CursorPagination):
    ordering = "-created_at"
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


class AutomationRunFilter(filters.FilterSet):
    automation = filters.UUIDFilter(field_name="automation__public_id")

    class Meta:
        model = AutomationRun
        fields = ["automation", "status", "trigger"]


@extend_schema_view(
    list=extend_schema(summary="Runs of your automations (staff: everyone's), newest first"),
    retrieve=extend_schema(summary="One run: its payload, the condition's verdict, each action's outcome"),
)
class AutomationRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = AutomationRun.objects.select_related("automation")
    serializer_class = s.AutomationRunSerializer
    permission_classes = [IsPerson]
    lookup_field = "public_id"
    lookup_value_regex = UUID
    pagination_class = Newest
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = AutomationRunFilter

    def get_queryset(self):
        return self.queryset.visible_to(self.request.user)
