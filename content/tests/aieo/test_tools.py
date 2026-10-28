"""AIEO's tools in the one registry, and AIEO's MCP tool names kept as aliases of them: the same function, input
schema, effect and checks under both names, listed to an MCP client holding the `aieo` agent's token; a page tool
needs the agent's group to hold page rights (a review agent holds none), and an agent never asks for suggestions on
a page — it rewrites a text. The `aieo` agent is also the citability review, a workflow task that passes or fails a
page by its heuristic score."""

import json

from django.contrib.auth import get_user_model
from django.test import Client

from agents.models import AgentRun, AgentToken
from agents.registry import ToolContext, ToolError, registry
from agents.runner import execute, start_run
from aieo import services
from aieo.models import Audit
from aieo.tools import ALIASES

from ..conftest import make_article


def rpc(raw, method, params=None):
    body = {"jsonrpc": "2.0", "id": 1, "method": method, **({"params": params} if params is not None else {})}
    return (
        Client()
        .post(
            "/mcp/",
            data=json.dumps(body),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {raw}",
            HTTP_ACCEPT="application/json, text/event-stream",
        )
        .json()
    )


def token(**kwargs):
    return AgentToken.issue(get_user_model().objects.get(username="agent:aieo"), name="mcp", **kwargs)[1]


def test_every_alias_is_its_platform_tool_under_aieos_name():
    assert len(ALIASES) == 22
    for alias, target in ALIASES.items():
        named, real = registry.get(alias), registry.get(target)
        assert (named.fn, named.input_schema, named.effect, named.perms, named.page_arg) == (
            real.fn,
            real.input_schema,
            real.effect,
            real.perms,
            real.page_arg,
        )
    assert registry.get("aieo_editor_review").effect == registry.get("aieo_headline_generate").effect == "propose"


def test_an_mcp_client_with_the_aieo_token_lists_aieos_tool_names_and_scores_a_text(agent, db):
    assert agent("aieo").live  # its evals passed in the session's sync_agents --publish
    raw = token()
    names = {t["name"] for t in rpc(raw, "tools/list")["result"]["tools"]}
    assert set(ALIASES) <= names and {"aieo_editor_review", "aieo_headline_generate", "aieo.score_text"} <= names
    answer = rpc(raw, "tools/call", {"name": "aieo_score_content", "arguments": {"content": "# Backups\n\nCopies."}})
    result = answer["result"]
    assert not result["isError"] and result["structuredContent"]["scoring_method"] == "heuristic"
    patterns = rpc(raw, "tools/call", {"name": "aieo_list_patterns", "arguments": {}})["result"]["structuredContent"]
    assert len(patterns["patterns"]) == 10
    one = rpc(raw, "tools/call", {"name": "aieo_get_pattern", "arguments": {"pattern_name": "nope"}})["result"]
    assert one["isError"] and one["structuredContent"]["error"] == "not_found"


def test_a_text_is_scored_at_once_only_when_short_and_a_long_one_is_audited(
    agent, db, django_capture_on_commit_callbacks
):
    ctx = ToolContext(user=agent("aieo").user, agent=agent("aieo"))
    long = "Backups are copies. " * (services.NOW_MAX // 20 + 1)
    for name in ("aieo.score_text", "aieo_score_content", "aieo.readability", "aieo.landing_audit"):
        try:
            registry.call(name, {"content": long}, ctx)
            raise AssertionError(f"{name} scored {len(long)} characters inside the call")
        except ToolError as e:
            assert e.code == "invalid_args"
    with django_capture_on_commit_callbacks(execute=True):
        started = registry.call("aieo.audit_text", {"content": long, "method": "heuristic"}, ctx)
    row = Audit.objects.get(public_id=started["audit"])
    assert row.kind == Audit.TEXT and row.status == Audit.READY and row.owner.username == "agent:aieo"


def test_auditing_a_url_over_mcp_is_a_run_the_agent_owns(agent, db, fake, web, django_capture_on_commit_callbacks):
    from .conftest import at

    web.get(at("/robots.txt")).respond(404)
    web.get(at("/")).respond(200, text="<h1>Home</h1><p>Backups, explained.</p>", headers={"Content-Type": "text/html"})
    raw = token()
    with django_capture_on_commit_callbacks(execute=True):
        result = rpc(
            raw,
            "tools/call",
            {"name": "aieo_audit_url", "arguments": {"url": "https://example.com/", "method": "heuristic"}},
        )
    started = result["result"]["structuredContent"]
    row = Audit.objects.get(public_id=started["audit"])
    assert row.owner.username == "agent:aieo" and row.origin == "mcp" and row.status == Audit.READY
    read = rpc(raw, "tools/call", {"name": "aieo_crawl_manifest", "arguments": {"audit": started["audit"]}})
    assert read["result"]["structuredContent"]["score"] == row.score


def test_aieos_agents_rewrites_and_patterns_over_mcp_are_runs_that_only_propose(
    agent, db, fake, django_capture_on_commit_callbacks
):
    from .conftest import answer

    raw = token()
    fake.script = [
        answer({"humanity_score": 70, "edits": ["Shorter."], "rewritten_excerpt": "Copies keep sites."}),
        {"text": "Copies keep a site safe."},
        {"text": "## FAQ\n\nWhy back up? Disks fail."},
    ]
    calls = [
        ("aieo_editor_review", {"content": "Copies — of a site — keep it."}),
        ("aieo_scrub", {"content": "Copies — of a site — keep it."}),
        ("aieo.apply_pattern", {"pattern_name": "faq_injection", "content": "Why back up?"}),
    ]
    for name, arguments in calls:
        with django_capture_on_commit_callbacks(execute=True):
            result = rpc(raw, "tools/call", {"name": name, "arguments": arguments})["result"]
        assert not result["isError"], result
        run = AgentRun.objects.get(pk=result["structuredContent"]["run_id"])
        assert run.status == AgentRun.SUCCEEDED and run.started_by.username == "agent:aieo", run.error
    assert AgentRun.objects.filter(input__kind="aieo.rewrite").count() == 2


def test_a_page_tool_needs_page_rights_and_an_agent_rewrites_a_text_never_a_page(
    agent, site_root, fake, django_capture_on_commit_callbacks
):
    page = make_article(site_root, "Backups", body=[{"type": "markdown", "value": "Copies of a site."}])
    ctx = ToolContext(user=agent("aieo").user, agent=agent("aieo"))
    try:
        registry.call("aieo.audit_page", {"page_id": page.pk, "method": "heuristic"}, ctx)
        raise AssertionError("a review agent holds no page rights")
    except ToolError as e:
        assert e.code == "permission_denied"
    fake.script = [{"text": "Copies of a site, kept elsewhere."}]
    with django_capture_on_commit_callbacks(execute=True):
        started = registry.call("aieo.scrub", {"content": "Copies — of a site."}, ctx)
    run = AgentRun.objects.get(pk=started["run_id"])
    assert run.status == AgentRun.SUCCEEDED and run.output["markdown"] == "Copies of a site, kept elsewhere."


def test_the_citability_review_passes_a_page_by_its_score(agent, site_root, settings):
    from agents.sync import load

    spec = next(d for d in load() if d["slug"] == "aieo")
    strong = make_article(site_root, "How to back up a site", body=spec["evals"][0]["input"]["page"]["body"])
    thin = make_article(site_root, "About", body=[{"type": "markdown", "value": "We make websites."}])
    verdicts = {}
    for page in (strong, thin):
        run = execute(start_run(agent("aieo"), trigger="workflow", target=page, enqueue=False))
        assert run.status == AgentRun.SUCCEEDED, run.error
        verdicts[page.title] = run.output["verdict"]
    assert verdicts["How to back up a site"]["passed"] is True
    settings.AIEO_REVIEW_MIN_SCORE = 90
    stricter = execute(start_run(agent("aieo"), trigger="workflow", target=strong, enqueue=False))
    assert stricter.output["verdict"]["passed"] is False
    assert verdicts["About"]["passed"] is False and verdicts["About"]["comments"]
    assert "citability" in verdicts["About"]["summary"]
