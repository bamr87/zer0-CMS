"""`/api/v2/aieo/`: AIEO in the platform over REST (aieo/README.md).

    score/                          a heuristic score of a text, at once (nothing recorded)
    audits/                         list (filters kind, status, page, url, batch; site), audit a text, a page, a URL or
                                    a site (202: a run reads, scores and, when asked, evaluates it)
    audits/<id>/                    one audit with its whole result; PATCH who sees it; DELETE
    audits/<id>/report/             its report, Markdown and HTML (AIEO's per-site report)
    audits/<id>/screenshot/         the visual audit's screenshot (PNG)
    audits/batch/                   audit a list of sites together (202)
    audits/summary/                 the summary report of a batch or a site's audits
    patterns/                       the pattern library (everyone reads; `aieo.change_pattern` changes it);
                                    <name>/apply/: apply a pattern to a page (suggestions) or a text (a draft), 202
    rewrites/                       optimize, expand, scrub or rewrite a page (suggestions) or a text (a draft), 202
    agents/                         the AIEO assistants; run/: one of the ten agents on a text or a page, 202
    citations/queries/              CRUD; <id>/check/: ask every engine now (202, a run per engine)
    citations/checks/               every answer (filters query, engine, cited)
    citations/share/                share of voice per engine, and by week
    connectors/                     a site's GA4, Search Console and DataForSEO connections (credential write-only);
                                    <id>/sync/ (202: a worker fetches), <id>/data/ (the last rows)
    priorities/?site=               the ranked update queue and quick wins
    context/<site>/                 the site's brand context the agents read (GET, PUT)
    lifecycle/?site=                where the site's content stands, stage by stage

Thin views: validate, call aieo/services.py, serialize. People only (`IsPerson`): an agent works through the tool
registry (aieo/tools.py). Rows come from `visible_to` alone. What reaches the network or a model answers 202 and
honours an `Idempotency-Key`; what makes the platform reach the web is throttled per person like the research
library's fetches. Every failure is the error envelope.
"""

from django.core.files.storage import default_storage
from django.http import FileResponse
from django.utils import timezone
from django_filters import rest_framework as filters
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.pagination import CursorPagination
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.response import Response
from rest_framework.views import APIView
from wagtail.models import Site

from ai.models import Assistant
from ai.serializers import RunRefSerializer
from ai.services import stable_id
from ai.views import IDEMPOTENCY, CanEdit, OwnedViewSet, accepted, idempotent, page_or_404
from api.pages import IsPerson
from ops.errors import Invalid, NotFound
from ops.openapi import ERROR_RESPONSES
from research.views import FetchThrottle

from . import prompts, reports, services
from . import serializers as s
from .models import Audit, BrandContext, CitationCheck, CitationQuery, Connector, Pattern

SITE = OpenApiParameter("site", OpenApiTypes.INT, description="A Wagtail site's id.")


def valid(serializer_class, request) -> dict:
    body = serializer_class(data=request.data, context={"request": request})
    body.is_valid(raise_exception=True)
    return body.validated_data


def site_param(request, *, required=False):
    raw = request.query_params.get("site")
    if not raw:
        if required:
            raise Invalid("name the site (?site=<id>)")
        return None
    site = Site.objects.filter(pk=raw).first() if str(raw).isdigit() else None
    if site is None:
        raise NotFound(f"no site {raw}")
    return site


class Newest(CursorPagination):
    ordering = "-created_at"
    page_size = 50
    page_size_query_param = "page_size"
    max_page_size = 200


@extend_schema(
    summary="Score a text at once with AIEO's heuristics (nothing recorded)",
    request=s.AieoScoreInputSerializer,
    responses={200: s.AieoScoreSerializer, **ERROR_RESPONSES},
)
class ScoreView(APIView):
    permission_classes = [IsPerson]

    def post(self, request):
        body = valid(s.AieoScoreInputSerializer, request)
        result = services.quick_score(body["content"], body["format"], site=body.get("site"), user=request.user)
        return Response(s.AieoScoreSerializer(result).data)


# ── audits ─────────────────────────────────────────────────────────────────


class AuditFilter(filters.FilterSet):
    page = filters.NumberFilter(field_name="page_id")

    class Meta:
        model = Audit
        fields = ["kind", "status", "page", "url", "batch"]


@extend_schema_view(
    list=extend_schema(summary="Audits, newest first (without their whole result)", parameters=[SITE]),
    retrieve=extend_schema(summary="One audit, with its whole result"),
    partial_update=extend_schema(summary="Share an audit: its site and who sees it"),
)
class AuditViewSet(OwnedViewSet):
    queryset = Audit.objects.select_related("owner", "page", "run")
    permission_classes = [IsPerson, CanEdit]
    pagination_class = Newest
    filterset_class = AuditFilter
    ordering = ["-created_at"]
    http_method_names = ["get", "post", "patch", "delete"]

    def get_serializer_class(self):
        return s.AieoAuditListSerializer if self.action == "list" else s.AieoAuditSerializer

    def get_throttles(self):
        data = self.request.data if self.request.method == "POST" else {}
        fetches = self.action == "batch" or (isinstance(data, dict) and data.get("kind") in (Audit.URL, Audit.SITE))
        return [*super().get_throttles(), FetchThrottle()] if fetches else super().get_throttles()

    @extend_schema(
        summary="Audit a text, a page, a URL or a site (202: a run does it, followed on its stream)",
        request=s.AieoAuditCreateSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.AieoAuditAcceptedSerializer, **ERROR_RESPONSES},
    )
    @idempotent
    def create(self, request):
        body = valid(s.AieoAuditCreateSerializer, request)
        page = page_or_404(body.pop("page_id", None))
        row = services.audit(request.user, page=page, origin="studio", **body)
        out = s.AieoAuditSerializer(row, context=self.get_serializer_context()).data
        return accepted(audit=out, run=RunRefSerializer(row.run).data)

    @extend_schema(
        summary="Audit a list of sites together, one run each (202)",
        request=s.AieoBatchInputSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.AieoBatchSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"])
    @idempotent
    def batch(self, request):
        body = valid(s.AieoBatchInputSerializer, request)
        made = services.batch_audit(request.user, body.pop("urls"), origin="studio", **body)
        listed = s.AieoAuditListSerializer(made, many=True, context=self.get_serializer_context()).data
        return Response({"batch": made[0].batch, "audits": listed}, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="The audit's report, as AIEO wrote it (Markdown and HTML)", responses={200: s.AieoReportSerializer}
    )
    @action(detail=True, methods=["get"])
    def report(self, request, public_id=None):
        row = self.get_object()
        if row.status != Audit.READY:
            raise Invalid(f"the audit is {row.status}: a report is of a finished audit")
        data = reports.data_of(row)
        text = reports.site_report(data, timezone.localtime())
        return Response({"filename": f"{data['_name']}.md", "markdown": text, "html": reports.html(text)})

    @extend_schema(
        summary="The summary report of a batch, or of the audits of a site (?batch= or ?site=)",
        parameters=[SITE, OpenApiParameter("batch", OpenApiTypes.STR)],
        responses={200: s.AieoReportSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["get"])
    def summary(self, request):
        rows = (
            Audit.objects.visible_to(request.user)
            .filter(kind__in=(Audit.URL, Audit.SITE))
            .exclude(status__in=(Audit.PENDING, Audit.RUNNING))
        )
        if request.query_params.get("batch"):
            rows = rows.filter(batch=request.query_params["batch"])
        elif (site := site_param(request)) is not None:
            rows = rows.filter(site=site)
        else:
            raise Invalid("name a batch (?batch=) or a site (?site=)")
        latest = {}
        for row in rows.order_by("-created_at")[:500]:
            latest.setdefault(row.url, row)  # each site's newest audit
        if not latest:
            raise NotFound("no finished audits there")
        data = sorted((reports.data_of(row) for row in latest.values()), key=lambda d: d["_name"])
        text = reports.summary_report(data, timezone.localtime())
        return Response({"filename": "REPORT.md", "markdown": text, "html": reports.html(text)})

    @extend_schema(
        summary="The visual audit's screenshot",
        responses={(200, "image/png"): OpenApiResponse(OpenApiTypes.BINARY), **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["get"])
    def screenshot(self, request, public_id=None):
        row = self.get_object()
        if not row.screenshot or not default_storage.exists(row.screenshot):
            raise NotFound("this audit has no screenshot")
        return FileResponse(default_storage.open(row.screenshot, "rb"), content_type="image/png")


# ── patterns ───────────────────────────────────────────────────────────────


class ChangesPatterns(BasePermission):
    """Everyone signed in reads the library; `aieo.<action>_pattern` changes it (superusers have every permission)."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS or view.action == "apply":
            return True
        verb = {"POST": "add", "DELETE": "delete"}.get(request.method, "change")
        return request.user.has_perm(f"aieo.{verb}_pattern")


@extend_schema_view(
    list=extend_schema(summary="The pattern library"),
    create=extend_schema(summary="Add a pattern (aieo.add_pattern)"),
    partial_update=extend_schema(summary="Change a pattern: its weight, maximum, criteria (aieo.change_pattern)"),
    destroy=extend_schema(summary="Remove a pattern (aieo.delete_pattern); a bundled one is switched off instead"),
)
class PatternViewSet(viewsets.ModelViewSet):
    queryset = Pattern.objects.all()
    serializer_class = s.AieoPatternSerializer
    permission_classes = [IsPerson, ChangesPatterns]
    lookup_field = "name"
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def perform_destroy(self, instance):
        if instance.bundled:
            raise Invalid("a bundled pattern is switched off (enabled: false), not removed")
        instance.delete()

    @extend_schema(
        summary="Apply the pattern: on a page, its rewrite arrives as suggestions; on a text, a draft (202)",
        request=s.AieoApplyPatternSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.AieoRunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def apply(self, request, name=None):
        body = valid(s.AieoApplyPatternSerializer, request)
        page = page_or_404(body.get("page_id"))
        run = services.rewrite(
            request.user,
            mode="pattern",
            page=page,
            content=body["content"],
            pattern=self.get_object(),
            style=body["style"],
        )
        return accepted(run=RunRefSerializer(run).data)


# ── rewrites and agents ────────────────────────────────────────────────────


@extend_schema(
    summary="Optimize, expand, scrub or rewrite: on a page as suggestions, on a text as a draft (202)",
    request=s.AieoRewriteInputSerializer,
    parameters=[IDEMPOTENCY],
    responses={202: s.AieoRunAcceptedSerializer, **ERROR_RESPONSES},
)
class RewriteView(APIView):
    permission_classes = [IsPerson]

    @idempotent
    def post(self, request):
        body = valid(s.AieoRewriteInputSerializer, request)
        run = services.rewrite(
            request.user,
            mode=body["mode"],
            page=page_or_404(body.get("page_id")),
            content=body["content"],
            pattern=body.get("pattern"),
            style=body["style"],
        )
        return accepted(run=RunRefSerializer(run).data)


GROUPS = {
    services.EVALUATOR: "evaluator",
    services.OPTIMIZER: "rewriter",
    services.SCRUBBER: "rewriter",
    services.REWRITER: "rewriter",
    services.PROBE: "probe",
}


class AgentViewSet(viewsets.ViewSet):
    permission_classes = [IsPerson]

    @extend_schema(
        summary="AIEO's assistants: the ten agents, the evaluator, the rewriters and writers",
        responses={200: s.AieoAgentSerializer(many=True)},
    )
    def list(self, request):
        found = []
        for spec in prompts.ASSISTANTS:
            row = (
                Assistant.objects.visible_to(request.user)
                .filter(public_id=stable_id("bundled-assistant", spec.key))
                .first()
            )
            if row is None:
                continue
            group = "agent" if spec.key in prompts.AGENTS else GROUPS.get(spec.key, "writer")
            found.append(
                {
                    "key": spec.key,
                    "id": row.public_id,
                    "name": row.name,
                    "description": row.description,
                    "group": group,
                    "structured": row.output_schema_id is not None,
                }
            )
        return Response(s.AieoAgentSerializer(found, many=True).data)

    @extend_schema(
        summary="Run one of the AIEO agents on a text or a page, with the site's context (202)",
        request=s.AieoAgentRunInputSerializer,
        parameters=[IDEMPOTENCY],
        responses={202: s.AieoRunAcceptedSerializer, **ERROR_RESPONSES},
    )
    @action(detail=False, methods=["post"])
    @idempotent
    def run(self, request):
        body = valid(s.AieoAgentRunInputSerializer, request)
        run = services.run_agent(
            request.user,
            body["agent"],
            content=body["content"],
            page=page_or_404(body.get("page_id")),
            site=body.get("site"),
            inputs=body["inputs"],
        )
        return accepted(run=RunRefSerializer(run).data)


# ── citations ──────────────────────────────────────────────────────────────


@extend_schema_view(list=extend_schema(summary="Tracked questions", parameters=[SITE]))
class CitationQueryViewSet(OwnedViewSet):
    queryset = CitationQuery.objects.select_related("owner")
    serializer_class = s.AieoCitationQuerySerializer
    permission_classes = [IsPerson, CanEdit]
    filterset_fields = ["active", "domain"]
    open_actions = ("check",)
    http_method_names = ["get", "post", "patch", "delete"]

    def perform_create(self, serializer):
        row = serializer.save(owner=self.request.user)
        if row.interval_days and row.active:
            row.next_check_at = timezone.now()
            row.save(update_fields=["next_check_at"])

    @extend_schema(
        summary="Ask every engine the question now: a check and a run per engine (202)",
        request=None,
        parameters=[IDEMPOTENCY],
        responses={202: s.AieoCitationChecksSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    @idempotent
    def check(self, request, public_id=None):
        made = services.check_citations(self.get_object(), user=request.user)
        return Response(
            {"checks": s.AieoCitationCheckSerializer(made, many=True).data}, status=status.HTTP_202_ACCEPTED
        )


class CheckFilter(filters.FilterSet):
    query = filters.UUIDFilter(field_name="query__public_id")

    class Meta:
        model = CitationCheck
        fields = ["query", "engine", "cited", "status"]


@extend_schema_view(list=extend_schema(summary="Every engine's answers, newest first", parameters=[SITE]))
class CitationCheckViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = s.AieoCitationCheckSerializer
    permission_classes = [IsPerson]
    lookup_field = "public_id"
    filterset_class = CheckFilter
    filter_backends = [filters.DjangoFilterBackend]

    class Pages(CursorPagination):
        ordering = "-checked_at"
        page_size = 50
        page_size_query_param = "page_size"
        max_page_size = 200

    pagination_class = Pages

    def get_queryset(self):
        site = site_param(self.request) if self.action == "list" else None
        return CitationCheck.objects.visible_to(self.request.user, site).select_related("query", "run")


@extend_schema(
    summary="Share of voice: per engine, how often its answers cited the domain, and by week",
    parameters=[SITE, OpenApiParameter("days", OpenApiTypes.INT, description="How far back (default 90).")],
    responses={200: s.AieoShareOfVoiceSerializer, **ERROR_RESPONSES},
)
class ShareView(APIView):
    permission_classes = [IsPerson]

    def get(self, request):
        days = request.query_params.get("days", "90")
        if not days.isdigit() or not 1 <= int(days) <= 730:
            raise Invalid("days is a number of days, 1 to 730")
        return Response(services.share_of_voice(request.user, site=site_param(request), days=int(days)))


# ── connectors ─────────────────────────────────────────────────────────────


class ConnectorPermission(BasePermission):
    def has_object_permission(self, request, view, obj):
        return request.method in SAFE_METHODS or obj.can_edit(request.user)


@extend_schema_view(
    list=extend_schema(summary="The connectors of the sites you edit", parameters=[SITE]),
    create=extend_schema(summary="Connect a site to GA4, Search Console or DataForSEO (aieo.change_connector)"),
)
class ConnectorViewSet(viewsets.ModelViewSet):
    serializer_class = s.AieoConnectorSerializer
    permission_classes = [IsPerson, ConnectorPermission]
    lookup_field = "public_id"
    pagination_class = None
    http_method_names = ["get", "post", "patch", "delete"]

    def get_queryset(self):
        return Connector.objects.visible_to(self.request.user, site_param(self.request)).select_related("site")

    def perform_create(self, serializer):
        data = serializer.validated_data
        row = services.connector_for(data["site"], data["kind"], user=self.request.user)
        self._save(serializer, row)

    def perform_update(self, serializer):
        self._save(serializer, serializer.instance)

    def _save(self, serializer, row):
        data = dict(serializer.validated_data)
        if "site" in data and data["site"] != row.site or data.get("kind", row.kind) != row.kind:
            raise Invalid("a connector stays with its site and kind")
        credential = data.pop("credential", None)
        for key in ("enabled", "options"):
            if key in data:
                setattr(row, key, data[key])
        if credential is not None:
            row.set_credential(credential)
        row.save()
        serializer.instance = row

    @extend_schema(
        summary="Fetch the connector's report now, in a worker (202)",
        request=None,
        responses={202: s.AieoConnectorSerializer, **ERROR_RESPONSES},
    )
    @action(detail=True, methods=["post"])
    def sync(self, request, public_id=None):
        row = services.sync(self.get_object(), user=request.user)
        return Response(self.get_serializer(row).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="The rows the last sync fetched", responses={200: s.AieoConnectorDataSerializer, **ERROR_RESPONSES}
    )
    @action(detail=True, methods=["get"])
    def data(self, request, public_id=None):
        last = self.get_object().snapshots.first()
        if last is None:
            raise NotFound("the connector has not synced yet")
        return Response({"report": last.report, "fetched_at": last.fetched_at, "rows": last.rows})


# ── priorities, context, lifecycle ─────────────────────────────────────────


@extend_schema(
    summary="The ranked content-update queue and quick wins, from Search Console's last rows",
    parameters=[SITE],
    responses={200: s.AieoPrioritiesSerializer, **ERROR_RESPONSES},
)
class PrioritiesView(APIView):
    permission_classes = [IsPerson]

    def get(self, request):
        found = services.priorities(request.user, site_param(request, required=True))
        return Response(s.AieoPrioritiesSerializer(found).data)


@extend_schema_view(
    get=extend_schema(
        summary="A site's brand context, which the AIEO agents read", responses={200: s.AieoBrandContextSerializer}
    ),
    put=extend_schema(
        summary="Change a site's brand context (its editors)",
        request=s.AieoBrandContextSerializer,
        responses={200: s.AieoBrandContextSerializer},
    ),
)
class ContextView(APIView):
    permission_classes = [IsPerson]

    def _context(self, request, site_id):
        site = Site.objects.filter(pk=site_id).first()
        if site is None:
            raise NotFound(f"no site {site_id}")
        return BrandContext.for_site(services.editor_of(request.user, site))

    def get(self, request, site_id):
        return Response(s.AieoBrandContextSerializer(self._context(request, site_id)).data)

    def put(self, request, site_id):
        row = self._context(request, site_id)
        body = s.AieoBrandContextSerializer(row, data=request.data, partial=True)
        body.is_valid(raise_exception=True)
        body.save()
        return Response(body.data)


@extend_schema(
    summary="Where a site's content stands in AIEO's lifecycle, stage by stage",
    parameters=[SITE],
    responses={200: s.AieoLifecycleSerializer, **ERROR_RESPONSES},
)
class LifecycleView(APIView):
    permission_classes = [IsPerson]

    def get(self, request):
        site = services.editor_of(request.user, site_param(request, required=True))
        return Response(services.lifecycle(request.user, site))
