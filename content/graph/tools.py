"""The graph tools (`graph.*`). Reading is free; an agent's edge is written
directly only when its confidence clears `GRAPH_EDGE_AUTO_THRESHOLD` *and* the
policy allows writing (`draft` or above, on agent and page); otherwise it
becomes a Suggestion an editor decides (note §5)."""

from agents.registry import ToolError, obj, tool
from cms.models import POLICY_DRAFT, POLICY_ORDER
from suggestions.models import Suggestion
from suggestions.services import SuggestionError, propose

from . import services
from .models import AGENT_RELS

NODE = {
    "type": "string",
    "pattern": "^(page|entity|image):[0-9]+$",
    "description": "page:<id>, entity:<id> or image:<id>",
}


def _hit(h):
    return {
        "page_id": h.page.pk,
        "title": h.page.title,
        "type": h.page._meta.label,
        "url_path": h.page.url_path,
        "score": h.score,
        "reasons": h.reasons,
    }


@tool(
    "graph.neighbors",
    effect="read",
    description="Nodes one or two hops from a node, with the relation, direction and source of each edge.",
    input_schema=obj(
        {"node": NODE, "rel": {"type": "string"}, "depth": {"type": "integer", "minimum": 1, "maximum": 2}},
        required=["node"],
    ),
)
def neighbors(ctx, node, rel=None, depth=1):
    try:
        return {"neighbors": services.neighbors(node, rel=rel, depth=depth)}
    except services.GraphError as e:
        raise ToolError("invalid_args", str(e)) from e


@tool(
    "graph.path",
    effect="read",
    description="The shortest chain of edges between two nodes (up to four hops), or null.",
    input_schema=obj({"a": NODE, "b": NODE}, required=["a", "b"]),
)
def path(ctx, a, b):
    try:
        return {"path": services.path(a, b)}
    except services.GraphError as e:
        raise ToolError("invalid_args", str(e)) from e


@tool(
    "graph.search",
    effect="read",
    description="Semantic search over live pages, expanded along the graph and reranked (GraphRAG).",
    input_schema=obj(
        {
            "query": {"type": "string", "minLength": 1},
            "first": {"type": "integer", "minimum": 1, "maximum": 20},
            "hops": {"type": "integer", "minimum": 1, "maximum": 2},
        },
        required=["query"],
    ),
    rate="120/m",
)
def search(ctx, query, first=5, hops=1):
    return {"results": [_hit(h) for h in services.graph_rag(query, first=first, hops=hops)]}


@tool(
    "graph.related",
    effect="read",
    description="Pages related to a page: similar by content, linked, or sharing a topic.",
    input_schema=obj(
        {
            "page_id": {"type": "integer"},
            "first": {"type": "integer", "minimum": 1, "maximum": 20},
            "kind": {"type": "string", "enum": ["similar", "structural", "behavioral"]},
        },
        required=["page_id"],
    ),
    page_arg="page_id",
)
def related(ctx, page_id, first=5, kind=None):
    from wagtail.models import Page

    page = Page.objects.get(pk=page_id).specific
    return {"results": [_hit(h) for h in services.related(page, first=first, kind=kind)]}


@tool(
    "graph.upsert_edge",
    effect="propose",
    description=(
        f"Propose an edge from a page to another node: one of {', '.join(AGENT_RELS)}, with a confidence from 0 to 1. "
        "A confident edge under a draft-or-higher policy is written; anything else becomes a Suggestion."
    ),
    input_schema=obj(
        {
            "page_id": {"type": "integer"},
            "rel": {"type": "string", "enum": AGENT_RELS},
            "dst": NODE,
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "rationale": {"type": "string", "minLength": 1},
        },
        required=["page_id", "rel", "dst", "confidence", "rationale"],
    ),
    perms=["wagtailcore.change_page"],
    page_arg="page_id",
)
def upsert_edge(ctx, page_id, rel, dst, confidence, rationale):
    from wagtail.models import Page

    page = Page.objects.get(pk=page_id).specific
    payload = {"rel": rel, "dst": dst, "confidence": confidence}
    policy = page.effective_policy(ctx.policy) if hasattr(page, "effective_policy") else ctx.policy
    try:
        if confidence >= services.threshold() and POLICY_ORDER.index(policy) >= POLICY_ORDER.index(POLICY_DRAFT):
            edge = services.upsert_edge(page, payload, source="agent", run=ctx.run)
            return {"written": True, "edge_id": edge.pk}
        s = propose(
            target=page,
            op=Suggestion.EDGE,
            user=ctx.user,
            run=ctx.run,
            agent=ctx.agent,
            payload=payload,
            rationale=rationale,
        )
    except (services.GraphError, SuggestionError) as e:
        raise ToolError("invalid_args", str(e)) from e
    return {"written": False, "suggestion_id": s.pk}
