"""HTTP surfaces: the GraphQL view, the REST endpoints and the health check.

**GraphQL.** Grapple's view is CSRF-exempt, which is right for a token client
and wrong for a browser session: a page elsewhere could post a mutation with
the editor's cookie. `ContentGraphQLView` authenticates a bearer token itself
(an agent user), and enforces Django's CSRF check on any POST that is
authenticated by session instead — DRF's rule.

**REST.** `/api/v2/agent-runs/` creates, lists, reads and streams (SSE) runs;
`/api/v2/agents/<slug>/runs` is the note's per-agent alias (§7);
`/api/v2/graph/{neighbors,path,related,search}/` read the graph;
`/api/v2/suggestions/` lists, accepts and rejects; `/api/v2/tools/` lists the
registry. Each view calls the same service functions as GraphQL and the admin.
"""

import json
import time

from django.db import connection, transaction
from django.http import JsonResponse, StreamingHttpResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from graphene_django.views import GraphQLView
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
from suggestions.models import Suggestion
from suggestions.services import SuggestionError, accept, can_decide, pending_for, reject

from .access import may_request_run
from .graphql import may_read_run


def healthz(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        database = "ok"
    except Exception as e:  # noqa: BLE001 — a health check reports the failure instead of raising it
        return JsonResponse({"status": "error", "database": f"{type(e).__name__}"}, status=503)
    return JsonResponse({"status": "ok", "database": database})


class _CSRFCheck(CsrfViewMiddleware):
    def _reject(self, request, reason):
        return reason


@method_decorator(csrf_exempt, name="dispatch")
class ContentGraphQLView(GraphQLView):
    def dispatch(self, request, *args, **kwargs):
        raw = bearer(request.headers.get("Authorization"))
        if raw is not None:
            token = AgentToken.authenticate(raw)
            if token is None:
                return JsonResponse({"errors": [{"message": "unknown, revoked or inactive agent token"}]}, status=401)
            request.user = token.user
            request.agent_token = token
        elif request.method == "POST" and request.user.is_authenticated:
            check = _CSRFCheck(lambda r: None)
            check.process_request(request)
            reason = check.process_view(request, None, (), {})
            if reason:
                return JsonResponse({"errors": [{"message": f"CSRF failed: {reason}"}]}, status=403)
        return super().dispatch(request, *args, **kwargs)


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
        return Response({"error": f"no agent {slug}"}, status=status.HTTP_404_NOT_FOUND)
    page = None
    if request.data.get("page_id") is not None:
        found = Page.objects.filter(pk=request.data["page_id"]).first()
        if found is None:
            return Response({"error": f"no page {request.data['page_id']}"}, status=status.HTTP_404_NOT_FOUND)
        page = found.specific
    allowed, reason = may_request_run(request.user, definition, page)
    if not allowed:
        return Response({"error": reason}, status=status.HTTP_403_FORBIDDEN)
    try:
        run = start_run(
            definition, trigger="rest", target=page, input=request.data.get("input") or {}, user=request.user
        )
    except RunRefused as e:
        return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)
    return Response(run_json(run), status=status.HTTP_201_CREATED)


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


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def agent_runs_for(request, slug):
    return _create_run(request, slug)


def _readable_run(request, pk):
    run = AgentRun.objects.select_related("agent", "target_ct").filter(pk=pk).first()
    return run if run is not None and may_read_run(request.user, run) else None


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_run(request, pk):
    run = _readable_run(request, pk)
    if run is None:
        return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
    return Response(run_json(run, steps=True))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def agent_run_stream(request, pk):
    """Server-sent events: each step as it lands, then the final status."""
    run = _readable_run(request, pk)
    if run is None:
        return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
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
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    return Response({"neighbors": [n for n in found if _public(n["node"])]})


def _public(node: str) -> bool:
    if not node.startswith("page:"):
        return True
    return Page.objects.live().filter(pk=int(node.split(":")[1])).exists()


@api_view(["GET"])
@permission_classes([AllowAny])
def graph_path(request):
    try:
        found = graph.path(request.query_params.get("a", ""), request.query_params.get("b", ""))
    except graph.GraphError as e:
        return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
    if found is not None and not all(_public(n) for n in found):
        found = None
    return Response({"path": found})


@api_view(["GET"])
@permission_classes([AllowAny])
def graph_related(request, page_id):
    page = Page.objects.live().filter(pk=page_id).first()
    if page is None:
        return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
    first = min(int(request.query_params.get("first", 5)), 20)
    return Response(
        {"results": _hits(graph.related(page.specific, first=first, kind=request.query_params.get("kind")))}
    )


@api_view(["GET"])
@permission_classes([AllowAny])
def graph_search(request):
    query = request.query_params.get("q", "").strip()
    if not query:
        return Response({"error": "q is required"}, status=status.HTTP_400_BAD_REQUEST)
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


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def suggestions(request):
    page = Page.objects.filter(pk=request.query_params.get("page") or 0).first()
    if page is None or not can_decide(request.user, page.specific):
        return Response({"results": []})
    return Response({"results": [suggestion_json(s) for s in pending_for(page.specific)]})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def suggestion_decide(request, pk, decision):
    suggestion = Suggestion.objects.filter(pk=pk).first()
    if suggestion is None:
        return Response({"error": "not found"}, status=status.HTTP_404_NOT_FOUND)
    try:
        with transaction.atomic():
            if decision == "accept":
                extra = Suggestion.objects.filter(pk__in=request.data.get("with", []))
                result = accept([suggestion, *extra], request.user)
                return Response({"accepted": True, "revision_id": result.pk if isinstance(result, Revision) else None})
            reject(suggestion, request.user, reason=request.data.get("reason", ""))
            return Response({"rejected": True})
    except SuggestionError as e:
        return Response({"error": str(e)}, status=status.HTTP_409_CONFLICT)


# ── the registry ───────────────────────────────────────────────────────────


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
