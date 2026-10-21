"""HTTP surfaces: the GraphQL view and the REST endpoints.

**GraphQL.** Grapple's view is CSRF-exempt, which is right for a token client
and wrong for a browser session: a page elsewhere could post a mutation with
the editor's cookie. `ContentGraphQLView` authenticates a bearer token itself
(an agent user), and enforces Django's CSRF check on any POST that is
authenticated by session instead — DRF's rule. Its `format_error` keeps
GraphQL's own `errors` array and adds the platform's `code` and `request_id`
in `extensions`; a resolver crash is reported as `internal.error` with the
traceback in the log, never in the response.

**REST.** `/api/v2/agent-runs/` creates, lists, reads and streams (SSE) runs;
`/api/v2/agents/<slug>/runs` is the note's per-agent alias (§7);
`/api/v2/graph/{neighbors,path,related,search}/` read the graph;
`/api/v2/suggestions/` lists, accepts and rejects; `/api/v2/tools/` lists the
registry. Each view calls the same service functions as GraphQL and the admin,
and every failure is raised (`ops.errors`) so the one envelope answers it.
"""

import json
import logging
import time

from django.db import transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from graphene_django.views import GraphQLView
from graphql import GraphQLError
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from wagtail.models import Page, Revision

from agents.auth import bearer
from agents.models import AgentDefinition, AgentRun, AgentToken
from agents.registry import ToolContext, registry
from agents.runner import RunRefused, start_run
from graph import services as graph
from ops.context import current_request_id
from ops.errors import ApiError, Conflict, Forbidden, Invalid, NotFound
from ops.openapi import ERROR_RESPONSES
from suggestions.models import Suggestion
from suggestions.services import SuggestionError, accept, can_decide, pending_for, reject

from .access import may_request_run
from .graphql import may_read_run

log = logging.getLogger("ops.graphql")


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return reason


def _graphql_error(message, code, status_code):
    extensions = {"code": code, "request_id": current_request_id()}
    return JsonResponse({"errors": [{"message": message, "extensions": extensions}]}, status=status_code)


@method_decorator(csrf_exempt, name="dispatch")
class ContentGraphQLView(GraphQLView):
    def dispatch(self, request, *args, **kwargs):
        raw = bearer(request.headers.get("Authorization"))
        if raw is not None:
            token = AgentToken.authenticate(raw)
            if token is None:
                return _graphql_error("unknown, revoked or inactive agent token", "auth.invalid_token", 401)
            request.user = token.user
            request.agent_token = token
        elif request.method == "POST" and request.user.is_authenticated:
            check = _CSRFCheck(lambda r: None)
            check.process_request(request)
            reason = check.process_view(request, None, (), {})
            if reason:
                return _graphql_error(f"CSRF failed: {reason}", "auth.csrf_failed", 403)
        return super().dispatch(request, *args, **kwargs)

    @staticmethod
    def format_error(error):
        """GraphQL's error shape plus `extensions.code` and `extensions.request_id`.

        A parse or validation error (no original exception) is `graphql.invalid`;
        an error a resolver raised on purpose keeps its message and any code it
        set; anything else crashed, and only the log learns why.
        """
        original = getattr(error, "original_error", None)
        if not isinstance(error, GraphQLError):
            original, error = error, None
        if isinstance(original, ApiError):
            code, formatted = original.code, error.formatted
        elif isinstance(original, GraphQLError):
            code, formatted = (original.extensions or {}).get("code", "graphql.error"), error.formatted
        elif original is None and error is not None:
            code, formatted = "graphql.invalid", error.formatted
        else:
            log.error("graphql resolver failed", exc_info=(type(original), original, original.__traceback__))
            code = "internal.error"
            formatted = {**(error.formatted if error is not None else {}), "message": "internal error"}
        extensions = {**(formatted.get("extensions") or {}), "code": code, "request_id": current_request_id()}
        return {**formatted, "extensions": extensions}


# ── agent runs ─────────────────────────────────────────────────────────────


def run_json(run: AgentRun, steps=False) -> dict:
    data = {
        "id": run.pk,
        "agent": run.agent.slug,
        "status": run.status,
        "trigger": run.trigger,
        "target": {"type": run.target_ct.model if run.target_ct else None, "id": run.target_id},
        "input": run.input,
        "output": run.output,
        "error": run.error,
        "cost_usd": str(run.cost_usd),
        "tokens": run.tokens,
        "trace_id": run.trace_id,
        "schema_version": run.schema_version,
        "created_at": run.created_at.isoformat(),
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "links": {"self": f"/api/v2/agent-runs/{run.pk}/", "stream": f"/api/v2/agent-runs/{run.pk}/stream/"},
    }
    if steps:
        data["steps"] = [step_json(s) for s in run.steps.all()]
    return data


def step_json(s) -> dict:
    return {
        "idx": s.idx,
        "kind": s.kind,
        "name": s.name,
        "args": s.args,
        "result": s.result,
        "error": s.error,
        "latency_ms": s.latency_ms,
        "tokens": s.tokens,
    }


def _create_run(request, slug):
    definition = AgentDefinition.objects.filter(slug=slug).first()
    if definition is None:
        raise NotFound(f"no agent {slug}")
    page = None
    if request.data.get("page_id") is not None:
        found = Page.objects.filter(pk=request.data["page_id"]).first()
        if found is None:
            raise NotFound(f"no page {request.data['page_id']}")
        page = found.specific
    allowed, reason = may_request_run(request.user, definition, page)
    if not allowed:
        raise Forbidden(reason)
    try:
        run = start_run(
            definition, trigger="rest", target=page, input=request.data.get("input") or {}, user=request.user
        )
    except RunRefused as e:
        raise Conflict(str(e)) from e
    return Response(run_json(run), status=status.HTTP_201_CREATED)


@extend_schema(
    methods=["GET"],
    operation_id="agent_runs_list",
    summary="The newest 50 runs the caller may see",
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@extend_schema(
    methods=["POST"],
    operation_id="agent_runs_create",
    summary="Start a run of `agent` on `page_id` with `input`",
    request=OpenApiTypes.OBJECT,
    responses={201: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET", "POST"])
@permission_classes([IsAuthenticated])
def agent_runs(request):
    if request.method == "POST":
        return _create_run(request, request.data.get("agent", ""))
    user = request.user
    qs = AgentRun.objects.select_related("agent", "target_ct")
    if not user.is_superuser:
        qs = (
            qs.filter(agent__slug=user.username[6:])
            if user.username.startswith("agent:")
            else qs.filter(started_by=user)
        )
    return Response({"results": [run_json(r) for r in qs[:50]]})


@extend_schema(
    summary="Start a run of one agent",
    request=OpenApiTypes.OBJECT,
    responses={201: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_runs_for(request, slug):
    return _create_run(request, slug)


def _readable_run(request, pk):
    run = AgentRun.objects.select_related("agent", "target_ct").filter(pk=pk).first()
    return run if run is not None and may_read_run(request.user, run) else None


@extend_schema(
    operation_id="agent_runs_retrieve",
    summary="One run with its steps",
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_run(request, pk):
    run = _readable_run(request, pk)
    if run is None:
        raise NotFound("not found")
    return Response(run_json(run, steps=True))


@extend_schema(
    summary="A run's steps as server-sent events",
    parameters=[
        OpenApiParameter("timeout", OpenApiTypes.FLOAT, description="Seconds to keep the stream open (max 300).")
    ],
    responses={(200, "text/event-stream"): OpenApiTypes.STR, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_run_stream(request, pk):
    """Server-sent events: each step as it lands, then the final status."""
    run = _readable_run(request, pk)
    if run is None:
        raise NotFound("not found")
    timeout = min(float(request.query_params.get("timeout", 60)), 300)

    def events():
        sent = -1
        deadline = time.monotonic() + timeout
        while True:
            current = AgentRun.objects.get(pk=run.pk)
            for step in current.steps.filter(idx__gt=sent).order_by("idx"):
                sent = step.idx
                yield f"event: step\ndata: {json.dumps(step_json(step), default=str)}\n\n"
            if current.is_final or time.monotonic() > deadline:
                yield f"event: status\ndata: {json.dumps({'id': current.pk, 'status': current.status, 'error': current.error})}\n\n"
                yield "event: end\ndata: {}\n\n"
                return
            time.sleep(0.5)

    response = StreamingHttpResponse(events(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


# ── graph ──────────────────────────────────────────────────────────────────


def _hits(hits):
    return [
        {
            "page_id": h.page.pk,
            "title": h.page.title,
            "type": h.page._meta.label,
            "url_path": h.page.url_path,
            "score": h.score,
            "reasons": h.reasons,
        }
        for h in hits
    ]


@extend_schema(
    summary="A node's neighbours",
    parameters=[
        OpenApiParameter("node", OpenApiTypes.STR, required=True, description="`page:<id>` or `entity:<id>`."),
        OpenApiParameter("rel", OpenApiTypes.STR, description="Only edges of this relation."),
        OpenApiParameter("depth", OpenApiTypes.INT, description="1 or 2 hops."),
    ],
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def graph_neighbors(request):
    try:
        found = graph.neighbors(
            request.query_params.get("node", ""),
            rel=request.query_params.get("rel") or None,
            depth=int(request.query_params.get("depth", 1)),
        )
    except (graph.GraphError, ValueError) as e:
        raise Invalid(str(e)) from e
    return Response({"neighbors": [n for n in found if _public(n["node"])]})


def _public(node: str) -> bool:
    if not node.startswith("page:"):
        return True
    return Page.objects.live().filter(pk=int(node.split(":")[1])).exists()


@extend_schema(
    summary="The shortest path between two nodes",
    parameters=[
        OpenApiParameter("a", OpenApiTypes.STR, required=True),
        OpenApiParameter("b", OpenApiTypes.STR, required=True),
    ],
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def graph_path(request):
    try:
        found = graph.path(request.query_params.get("a", ""), request.query_params.get("b", ""))
    except graph.GraphError as e:
        raise Invalid(str(e)) from e
    if found is not None and not all(_public(n) for n in found):
        found = None
    return Response({"path": found})


@extend_schema(
    summary="Pages related to one page",
    parameters=[
        OpenApiParameter("first", OpenApiTypes.INT, description="How many, up to 20."),
        OpenApiParameter("kind", OpenApiTypes.STR, description="`structural`, `semantic` or `behavioral`."),
    ],
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def graph_related(request, page_id):
    page = Page.objects.live().filter(pk=page_id).first()
    if page is None:
        raise NotFound("not found")
    first = min(int(request.query_params.get("first", 5)), 20)
    return Response(
        {"results": _hits(graph.related(page.specific, first=first, kind=request.query_params.get("kind")))}
    )


@extend_schema(
    summary="GraphRAG search",
    parameters=[
        OpenApiParameter("q", OpenApiTypes.STR, required=True),
        OpenApiParameter("first", OpenApiTypes.INT, description="How many, up to 20."),
        OpenApiParameter("hops", OpenApiTypes.INT, description="Graph expansion, 1 or 2."),
    ],
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def graph_search(request):
    query = request.query_params.get("q", "").strip()
    if not query:
        raise Invalid("q is required", details=[{"field": "q", "code": "required", "message": "q is required"}])
    first = min(int(request.query_params.get("first", 5)), 20)
    return Response(
        {"results": _hits(graph.graph_rag(query, first=first, hops=int(request.query_params.get("hops", 1))))}
    )


# ── suggestions ────────────────────────────────────────────────────────────


def suggestion_json(s: Suggestion) -> dict:
    return {
        "id": s.pk,
        "op": s.op,
        "block_id": s.block_id,
        "field": s.field,
        "payload": s.payload,
        "rationale": s.rationale,
        "status": s.status,
        "agent": s.agent.slug if s.agent else None,
        "run_id": s.run_id,
    }


@extend_schema(
    summary="Pending suggestions on a page the caller may decide",
    parameters=[OpenApiParameter("page", OpenApiTypes.INT, required=True)],
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def suggestions(request):
    page = Page.objects.filter(pk=request.query_params.get("page") or 0).first()
    if page is None or not can_decide(request.user, page.specific):
        return Response({"results": []})
    return Response({"results": [suggestion_json(s) for s in pending_for(page.specific)]})


@extend_schema(
    summary="Accept (with `with: [ids]` as one revision) or reject (with `reason`) a suggestion",
    request=OpenApiTypes.OBJECT,
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def suggestion_decide(request, pk, decision):
    suggestion = Suggestion.objects.filter(pk=pk).first()
    if suggestion is None:
        raise NotFound("not found")
    try:
        with transaction.atomic():
            if decision == "accept":
                extra = Suggestion.objects.filter(pk__in=request.data.get("with", []))
                result = accept([suggestion, *extra], request.user)
                return Response({"accepted": True, "revision_id": result.pk if isinstance(result, Revision) else None})
            reject(suggestion, request.user, reason=request.data.get("reason", ""))
            return Response({"rejected": True})
    except SuggestionError as e:
        raise Conflict(str(e)) from e


# ── the registry ───────────────────────────────────────────────────────────


@extend_schema(
    summary="The tools the caller may use",
    description="An agent token sees its agent's tools; a person sees the whole registry.",
    responses={200: OpenApiTypes.OBJECT, **ERROR_RESPONSES},
)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def tools(request):
    token = request.auth if isinstance(request.auth, AgentToken) else None
    if request.user.username.startswith("agent:"):
        definition = AgentDefinition.objects.filter(slug=request.user.username[6:]).first()
        listed = (
            registry.for_context(ToolContext(user=request.user, agent=definition, token=token)) if definition else []
        )
    else:
        listed = registry.all()
    return Response({"tools": [{**t.spec(), "effect": t.effect, "perms": list(t.perms)} for t in listed]})
