"""AIEO's tools (`aieo.*`) in the one registry (agents/registry.py), and AIEO's MCP tool names (`aieo_*`) kept as
aliases, so an agent, an MCP client and the APIs reach AIEO under the same checks.

The canonical tools score a text, list and read the pattern library, read an audit, and run the analyzers at once
(`read`); auditing a URL, a site or a page, rewriting a text, applying a pattern, running an AIEO agent and writing
a research brief queue a run whose result someone reviews, and return it to follow (`propose`). An agent never asks
for suggestions on a page — the platform's rule (`ai.services.check_page`): it rewrites a text, or proposes with
`content.propose_edit` itself.

AIEO's own MCP server had 28 tools. Each one with a platform counterpart is registered again under its AIEO name,
as an alias of that tool — the same function, input schema, effect and checks (`ALIASES`): the scorer, the URL and
site audits, the patterns, the analyzers, priorities, the rewriters, research and writing briefs, and the old file
workspace's list, read and write as `content.search`, `content.get_page` and `content.propose_edit` (a write is a
proposal). Two named one agent, so they are thin tools of their own over `aieo.run_agent`. Not here: WordPress
publishing (distribution, PLAN G5) and the PRD-lineage tools, which the platform does not have. The `aieo` agent
definition lists them all, so `manage.py agent_token aieo` gives an MCP client AIEO's tools.
"""

import dataclasses
import uuid

from wagtail.models import Page, Site

import ai.tools  # noqa: F401 — registers ai.generate_brief, aliased below
import cms.tools  # noqa: F401 — registers content.*, aliased below
from agents.registry import ToolError, obj, registry, tool
from ops.errors import ApiError
from research.services import research_brief

from . import analyzers, parser, services
from .models import Audit, Pattern, library
from .prompts import AGENTS

UUID = {"type": "string", "format": "uuid"}
CONTENT = {"type": "string", "minLength": 1, "maxLength": services.MAX_TEXT}  # read in a run, in a worker
NOW = {"type": "string", "minLength": 1, "maxLength": services.NOW_MAX}  # scored at once, inside the call
FORMAT = {"type": "string", "enum": ["markdown", "html"], "default": "markdown"}
METHOD = {"type": "string", "enum": ["heuristic", "ai"], "default": "ai"}
URL = {"type": "string", "minLength": 1, "maxLength": 2000}
CODES = {403: "permission_denied", 404: "not_found", 409: "policy", 429: "rate_limited"}


def _refused(e: ApiError) -> ToolError:
    return ToolError(CODES.get(e.status, "invalid_args"), e.message)


def _run(run) -> dict:
    return {"run_id": str(run.public_id), "status": run.status, "stream": run.links["stream"]}


def _audit(row: Audit) -> dict:
    return {"audit": str(row.public_id), **_run(row.run)}


def _page(page_id):
    page = Page.objects.filter(pk=page_id).first() if page_id is not None else None
    if page_id is not None and page is None:
        raise ToolError("not_found", f"no page {page_id}")
    return page


def _calling(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except ApiError as e:
        raise _refused(e) from e


# ── scoring at once ────────────────────────────────────────────────────────


@tool(
    "aieo.score_text",
    effect="read",
    description=(
        "Score content (Markdown or HTML) for AI citability with AIEO's heuristics: a 0-100 score and grade, each "
        "pattern's score with evidence and a recommendation, the gaps, anti-pattern penalties and the five "
        "dimensions (aieo, seo, readability, humanity, cro). Nothing is recorded. A text longer than "
        f"{services.NOW_MAX} characters is audited instead (aieo.audit_text)."
    ),
    input_schema=obj({"content": NOW, "format": FORMAT}, required=["content"]),
    rate="120/m",
)
def score_text(ctx, content, format="markdown"):
    return _calling(services.quick_score, content, format)


def _analysis(key: str, about: str):
    def analyze(ctx, content):
        return parser_result(content)[key]

    tool(
        f"aieo.{key}",
        effect="read",
        description=f"{about} of the content (Markdown), as AIEO's analyzers compute it.",
        input_schema=obj({"content": NOW}, required=["content"]),
        rate="120/m",
    )(analyze)


def parser_result(content: str) -> dict:
    return services.quick_score(content, "markdown")


_analysis("readability", "Readability: reading ease, grade level, sentence length, passive voice")
_analysis("keyword_analysis", "Keyword density, the terms it leans on, topic clusters and stuffing risk")
_analysis("search_intent", "The search intent (informational, navigational, transactional, commercial)")


@tool(
    "aieo.landing_audit",
    effect="read",
    description="The landing-page CRO score of copy: above the fold, calls to action and trust signals, as AIEO.",
    input_schema=obj({"content": NOW}, required=["content"]),
    rate="120/m",
)
def landing_audit(ctx, content):
    return analyzers.landing_page(parser.parse(content)["text"])


# ── the pattern library ────────────────────────────────────────────────────


def _pattern_json(p: Pattern, body=False) -> dict:
    data = {
        "name": p.name,
        "display_name": p.display_name,
        "category": p.category,
        "description": p.description,
        "weight": p.weight,
        "max_score": p.max_score,
        "citation_boost": {"min": p.boost_min, "max": p.boost_max},
        "enabled": p.enabled,
    }
    return {**data, "body": p.body} if body else data


@tool(
    "aieo.list_patterns",
    effect="read",
    description="The AIEO pattern library: each pattern's name, category, weight, maximum and citation boost.",
    input_schema=obj({}),
)
def list_patterns(ctx):
    return {"patterns": [_pattern_json(p) for p in Pattern.objects.all()]}


@tool(
    "aieo.get_pattern",
    effect="read",
    description="One AIEO pattern in full: its scoring criteria, examples and context notes.",
    input_schema=obj({"pattern_name": {"type": "string", "minLength": 1}}, required=["pattern_name"]),
)
def get_pattern(ctx, pattern_name):
    found = Pattern.objects.filter(name=pattern_name).first()
    if found is None:
        raise ToolError(
            "not_found", f"no pattern {pattern_name!r}; there are {', '.join(p['name'] for p in library())}"
        )
    return _pattern_json(found, body=True)


# ── audits ─────────────────────────────────────────────────────────────────


@tool(
    "aieo.audit_text",
    effect="propose",
    description=(
        "Audit a text (Markdown or HTML) of any length for AI citability, in a run: scored by a model's evaluation "
        "with the heuristics as the fallback (method ai) or the heuristics alone. Returns the audit and the run to "
        "follow; read it with aieo.get_audit."
    ),
    input_schema=obj({"content": CONTENT, "format": FORMAT, "method": METHOD}, required=["content"]),
    rate="30/m",
)
def audit_text(ctx, content, format="markdown", method="ai"):
    row = _calling(
        services.audit,
        ctx.user,
        kind=Audit.TEXT,
        content=content,
        format=format,
        method=method,
        origin="mcp",
        trigger=ctx.trigger,
    )
    return _audit(row)


@tool(
    "aieo.audit_url",
    effect="propose",
    description=(
        "Audit a web page for AI citability: it is fetched (robots.txt honoured) and scored, by a model's "
        "evaluation with the heuristics as the fallback (method ai) or the heuristics alone. Returns the audit "
        "and the run to follow; read it with aieo.get_audit."
    ),
    input_schema=obj({"url": URL, "method": METHOD, "visual": {"type": "boolean"}}, required=["url"]),
    rate="30/m",
)
def audit_url(ctx, url, method="ai", visual=False):
    row = _calling(
        services.audit,
        ctx.user,
        kind=Audit.URL,
        url=url,
        method=method,
        visual=visual,
        origin="mcp",
        trigger=ctx.trigger,
    )
    return _audit(row)


@tool(
    "aieo.audit_site",
    effect="propose",
    description=(
        "Crawl a site (sitemap, feed, then links; robots.txt honoured) and score every page it reads, with a link "
        "map of its hubs and orphans. Returns the audit and the run to follow; read it with aieo.get_audit."
    ),
    input_schema=obj(
        {"url": URL, "max_pages": {"type": "integer", "minimum": 1, "maximum": 200}, "method": METHOD},
        required=["url"],
    ),
    rate="10/m",
)
def audit_site(ctx, url, max_pages=25, method="heuristic"):
    row = _calling(
        services.audit,
        ctx.user,
        kind=Audit.SITE,
        url=url,
        max_pages=max_pages,
        method=method,
        origin="mcp",
        trigger=ctx.trigger,
    )
    return _audit(row)


@tool(
    "aieo.audit_page",
    effect="propose",
    description="Audit a page's latest revision for AI citability. Returns the audit and the run to follow.",
    input_schema=obj({"page_id": {"type": "integer"}, "method": METHOD}, required=["page_id"]),
    perms=["wagtailcore.change_page"],
    page_arg="page_id",
    rate="30/m",
)
def audit_page(ctx, page_id, method="ai"):
    row = _calling(
        services.audit, ctx.user, kind=Audit.PAGE, page=_page(page_id), method=method, origin="mcp", trigger=ctx.trigger
    )
    return _audit(row)


@tool(
    "aieo.get_audit",
    effect="read",
    description=(
        "An audit you made: its status, score, grade, patterns, gaps and dimensions; for a site, its pages, how they "
        "were found and its link map."
    ),
    input_schema=obj({"audit": UUID}, required=["audit"]),
)
def get_audit(ctx, audit):
    try:
        key = uuid.UUID(str(audit))
    except ValueError as e:
        raise ToolError("invalid_args", f"{audit!r} is not a uuid") from e
    row = Audit.objects.visible_to(ctx.user).filter(public_id=key).first()
    if row is None:
        raise ToolError("not_found", f"no audit {audit}")
    result = row.result or {}
    keep = ("pattern_scores", "gaps", "anti_pattern_penalties", "dimensions", "overall_assessment", "site", "fallback")
    return {
        "audit": str(row.public_id),
        "kind": row.kind,
        "status": row.status,
        "error": row.error,
        "target": row.target,
        "score": row.score,
        "grade": row.grade,
        "scoring_method": row.scoring_method,
        **{key: result[key] for key in keep if key in result},
        "pages": row.pages,
    }


# ── rewrites and agents ────────────────────────────────────────────────────


def _rewrite(ctx, mode, content, pattern=None, style="preserve"):
    return _run(_calling(services.rewrite, ctx.user, mode=mode, content=content, pattern=pattern, style=style))


@tool(
    "aieo.optimize",
    effect="propose",
    description=(
        "Rewrite a text to raise its citability score — the gaps an audit finds, fixed (expand also adds depth: "
        "definitions, an FAQ, comparisons). The rewrite is the run's output, a draft for a person to read."
    ),
    input_schema=obj(
        {
            "content": CONTENT,
            "style": {"type": "string", "enum": ["preserve", "aggressive"]},
            "expand": {"type": "boolean"},
        },
        required=["content"],
    ),
    rate="30/m",
)
def optimize(ctx, content, style="preserve", expand=False):
    return _rewrite(ctx, "expand" if expand else "optimize", content, style=style)


@tool(
    "aieo.scrub",
    effect="propose",
    description="Remove AI-writing tells from a text (repetitive openings, filler, em-dashes); the run's output.",
    input_schema=obj({"content": CONTENT}, required=["content"]),
    rate="30/m",
)
def scrub(ctx, content):
    return _rewrite(ctx, "scrub", content)


@tool(
    "aieo.apply_pattern",
    effect="propose",
    description="Rewrite a text to apply one pattern of the library; the rewrite is the run's output.",
    input_schema=obj(
        {"pattern_name": {"type": "string", "minLength": 1}, "content": CONTENT}, required=["pattern_name", "content"]
    ),
    rate="30/m",
)
def apply_pattern(ctx, pattern_name, content):
    pattern = Pattern.objects.filter(name=pattern_name).first()
    if pattern is None:
        raise ToolError("not_found", f"no pattern {pattern_name!r}")
    return _rewrite(ctx, "pattern", content, pattern=pattern)


@tool(
    "aieo.run_agent",
    effect="propose",
    description=(
        "Run one of the AIEO agents on a text or a page, with the brand context of a site you edit: "
        + ", ".join(key.removeprefix("aieo-") for key in AGENTS)
        + ". Returns the run; its structured answer is a proposal."
    ),
    input_schema=obj(
        {
            "agent": {"type": "string", "enum": [key.removeprefix("aieo-") for key in AGENTS]},
            "content": {"type": "string", "maxLength": services.MAX_TEXT},
            "page_id": {"type": "integer"},
            "site": {"type": "integer"},
            "inputs": {"type": "object", "additionalProperties": {"type": "string"}},
        },
        required=["agent"],
    ),
    page_arg="page_id",
    rate="30/m",
)
def run_agent(ctx, agent, content="", page_id=None, site=None, inputs=None):
    where = Site.objects.filter(pk=site).first() if site else None
    if site and where is None:
        raise ToolError("not_found", f"no site {site}")
    run = _calling(
        services.run_agent,
        ctx.user,
        f"aieo-{agent}",
        content=content,
        page=_page(page_id),
        site=where,
        inputs=inputs,
        trigger=ctx.trigger,
    )
    return _run(run)


@tool(
    "aieo_editor_review",
    effect="propose",
    description="AIEO's editor agent on a text: clarity, flow and human voice (aieo.run_agent with agent editor).",
    input_schema=obj({"content": CONTENT}, required=["content"]),
    rate="30/m",
)
def editor_review(ctx, content):
    return run_agent(ctx, "editor", content=content)


@tool(
    "aieo_headline_generate",
    effect="propose",
    description="AIEO's headline generator for a topic (aieo.run_agent with agent headline-generator).",
    input_schema=obj({"topic": {"type": "string", "minLength": 1, "maxLength": 2000}}, required=["topic"]),
    rate="30/m",
)
def headline_generate(ctx, topic):
    return run_agent(ctx, "headline-generator", inputs={"topic": topic})


@tool(
    "aieo.research_brief",
    effect="propose",
    description="A content research brief on a topic (intent, keywords, angles, outline, links) from the sources you see.",
    input_schema=obj({"topic": {"type": "string", "minLength": 1, "maxLength": 2000}}, required=["topic"]),
    rate="20/m",
)
def research(ctx, topic):
    return _run(_calling(research_brief, None, user=ctx.user, topic=topic))


@tool(
    "aieo.priorities",
    effect="read",
    description="The ranked content-update queue and quick wins of a site you edit, from its last Search Console sync.",
    input_schema=obj({"site": {"type": "integer"}}, required=["site"]),
)
def priorities(ctx, site):
    found = Site.objects.filter(pk=site).first()
    if found is None:
        raise ToolError("not_found", f"no site {site}")
    data = _calling(services.priorities, ctx.user, found)  # a site the agent edits, as REST asks of a person
    return {**data, "fetched_at": data["fetched_at"].isoformat() if data["fetched_at"] else None}


# ── AIEO's MCP names ───────────────────────────────────────────────────────

ALIASES = {
    "aieo_score_content": "aieo.score_text",
    "aieo_audit_url": "aieo.audit_url",
    "aieo_analyze_existing": "aieo.audit_url",
    "aieo_crawl_site": "aieo.audit_site",
    "aieo_site_context": "aieo.audit_site",
    "aieo_crawl_manifest": "aieo.get_audit",
    "aieo_context_map": "aieo.get_audit",
    "aieo_context_manifest": "aieo.get_audit",
    "aieo_list_patterns": "aieo.list_patterns",
    "aieo_get_pattern": "aieo.get_pattern",
    "aieo_readability": "aieo.readability",
    "aieo_keyword_analysis": "aieo.keyword_analysis",
    "aieo_search_intent": "aieo.search_intent",
    "aieo_landing_audit": "aieo.landing_audit",
    "aieo_priorities": "aieo.priorities",
    "aieo_rewrite": "aieo.optimize",
    "aieo_scrub": "aieo.scrub",
    "aieo_research": "aieo.research_brief",
    "aieo_write": "ai.generate_brief",
    "aieo_workspace_list": "content.search",
    "aieo_workspace_read": "content.get_page",
    "aieo_workspace_write": "content.propose_edit",
}

for _alias, _target in ALIASES.items():
    _tool = registry.get(_target)
    registry.register(
        dataclasses.replace(_tool, name=_alias, description=f"{_tool.description} (AIEO's name for {_target}.)")
    )
