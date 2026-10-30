"""`/api/v2/aieo/` for people: a score at once; audits as runs (202, an Idempotency-Key replays the first answer),
each seen only by those its owner shares it with; the pattern library read by everyone and changed only with
`aieo.change_pattern` (and the scorer reads the change); the AIEO agents listed and run with the site's brand
context; the context itself, its editors' to read and change; the lifecycle counted from the platform's rows; and
an agent token refused (an agent works through the tool registry)."""

from pathlib import Path

import pytest
from django.contrib.auth.models import Permission
from wagtail.models import Site

from agents.models import AgentRun
from agents.registry import ToolContext, ToolError, registry
from aieo import services
from aieo.models import Audit, BrandContext, Pattern
from aieo.prompts import AGENTS

from .conftest import answer

HERE = Path(__file__).resolve().parent
ARTICLE = (HERE / "fixtures" / "article.md").read_text(encoding="utf-8")


def test_a_text_is_scored_at_once_and_nothing_is_recorded(bob, api):
    got = api(bob).post("/api/v2/aieo/score/", {"content": ARTICLE}, format="json")
    assert got.status_code == 200
    data = got.json()
    assert data["score"] == 52.0 and data["grade"] == "D" and data["scoring_method"] == "heuristic"
    assert set(data["dimensions"]) == {"aieo", "seo", "readability", "humanity", "cro"}
    assert data["result"]["cro"]["checklist"]["total"] == 4 and not Audit.objects.exists()
    assert api(bob).post("/api/v2/aieo/score/", {"content": "  "}, format="json").status_code == 422
    # Inside a request only a short text: Python-Markdown's time grows with the square of a long paragraph (5,000
    # "[" take about two seconds), so a longer text is audited, in a run with a time limit.
    long = api(bob).post("/api/v2/aieo/score/", {"content": "a" * (services.NOW_MAX + 1)}, format="json")
    assert long.status_code == 422 and "audit" in long.json()["error"]["message"] and not Audit.objects.exists()


def test_audits_are_runs_kept_as_history_and_seen_only_where_shared(
    alice, bob, api, fake, worker, django_capture_on_commit_callbacks
):
    body = {"kind": "text", "content": ARTICLE, "method": "heuristic", "title": "Draft"}
    with django_capture_on_commit_callbacks(execute=True):
        made = api(alice).post("/api/v2/aieo/audits/", body, format="json", HTTP_IDEMPOTENCY_KEY="a1")
    assert made.status_code == 202, made.content
    audit, run = made.json()["audit"], made.json()["run"]
    assert audit["status"] == "pending" and run["links"]["stream"] == f"/api/v2/agent-runs/{run['id']}/stream/"
    assert AgentRun.objects.get(public_id=run["id"]).input == {"kind": "aieo.audit", "audit": audit["id"]}
    replay = api(alice).post("/api/v2/aieo/audits/", body, format="json", HTTP_IDEMPOTENCY_KEY="a1")
    assert replay.json() == made.json() and Audit.objects.count() == 1
    one = api(alice).get(f"/api/v2/aieo/audits/{audit['id']}/").json()
    assert one["status"] == "ready" and one["score"] == 52.0 and one["result"]["gaps"]
    assert "result" not in api(alice).get("/api/v2/aieo/audits/").json()["results"][0]
    assert api(bob).get(f"/api/v2/aieo/audits/{audit['id']}/").status_code == 404
    assert api(bob).get("/api/v2/aieo/audits/").json()["results"] == []
    report = api(alice).get(f"/api/v2/aieo/audits/{audit['id']}/report/").json()
    assert report["markdown"].startswith("# AIEO Audit Report:") and "<table>" in report["html"]
    shared = api(alice).patch(f"/api/v2/aieo/audits/{audit['id']}/", {"visibility": "shared"}, format="json")
    assert shared.status_code == 200 and api(bob).get(f"/api/v2/aieo/audits/{audit['id']}/").status_code == 200
    assert api(bob).delete(f"/api/v2/aieo/audits/{audit['id']}/").status_code == 403


def test_a_batch_audits_a_list_of_sites_and_its_summary_ranks_them(
    alice, api, fake, web, django_capture_on_commit_callbacks
):
    from .conftest import at

    web.get(at("/robots.txt")).respond(404)
    web.get(at("/")).respond(
        200, text="<h1>Home</h1><p>We back up sites. Is it enough?</p>", headers={"Content-Type": "text/html"}
    )
    web.get(at("/gone")).respond(404)
    urls = ["https://example.com/", "https://example.com/gone"]
    with django_capture_on_commit_callbacks(execute=True):
        made = api(alice).post("/api/v2/aieo/audits/batch/", {"urls": urls, "method": "heuristic"}, format="json")
    assert made.status_code == 202 and len(made.json()["audits"]) == 2
    summary = api(alice).get("/api/v2/aieo/audits/summary/", {"batch": made.json()["batch"]}).json()
    assert "**2 sites audited**" in summary["markdown"] and "| Failed | 1 |" in summary["markdown"]


def test_auditing_the_web_spends_the_fetch_rate_once_for_every_site(alice, api, fake, monkeypatch):
    """Audits that reach the web are throttled like the research library's fetches (`THROTTLE_RESEARCH_FETCH_RATE`),
    and a batch spends it once for every site it lists: one that would not fit is refused whole, and spends nothing.
    A text's audit reaches nothing, and is not counted."""
    from research.views import FetchThrottle

    monkeypatch.setitem(FetchThrottle.THROTTLE_RATES, "research_fetch", "3/min")
    urls = [f"https://example.com/{name}" for name in "abcd"]
    four = api(alice).post("/api/v2/aieo/audits/batch/", {"urls": urls, "method": "heuristic"}, format="json")
    assert four.status_code == 429 and not Audit.objects.exists()
    three = api(alice).post("/api/v2/aieo/audits/batch/", {"urls": urls[:3], "method": "heuristic"}, format="json")
    assert three.status_code == 202 and Audit.objects.count() == 3
    one = api(alice).post("/api/v2/aieo/audits/", {"kind": "url", "url": urls[3], "method": "heuristic"}, format="json")
    assert one.status_code == 429  # the three sites spent the minute's three fetches
    text = api(alice).post(
        "/api/v2/aieo/audits/", {"kind": "text", "content": "# A", "method": "heuristic"}, format="json"
    )
    assert text.status_code == 202


def test_everyone_reads_the_pattern_library_and_only_its_keepers_change_it(alice, api, worker, fake):
    listed = api(alice).get("/api/v2/aieo/patterns/").json()
    assert len(listed) == 10 and sum(p["weight"] for p in listed) == 125 and all(p["bundled"] for p in listed)
    faq = api(alice).get("/api/v2/aieo/patterns/faq_injection/").json()
    assert faq["category"] == "content" and faq["boost_min"] == 15 and "## What to Evaluate" in faq["body"]
    assert api(alice).patch("/api/v2/aieo/patterns/faq_injection/", {"weight": 60}, format="json").status_code == 403
    alice.user_permissions.add(Permission.objects.get(codename="change_pattern"))
    keeper = type(alice).objects.get(pk=alice.pk)
    before = api(keeper).post("/api/v2/aieo/score/", {"content": ARTICLE}, format="json").json()["score"]
    assert api(keeper).patch("/api/v2/aieo/patterns/faq_injection/", {"weight": 60}, format="json").status_code == 200
    after = api(keeper).post("/api/v2/aieo/score/", {"content": ARTICLE}, format="json").json()["score"]
    assert after != before  # the scorer reads the library
    Pattern.objects.filter(name="meta_context").update(enabled=False)
    parts = api(keeper).post("/api/v2/aieo/score/", {"content": ARTICLE}, format="json").json()["pattern_scores"]
    assert "meta_context" not in parts and len(parts) == 9
    assert api(keeper).delete("/api/v2/aieo/patterns/faq_injection/").status_code == 403  # change ≠ delete


def test_the_aieo_agents_are_listed_and_run_with_the_sites_context(
    alice, api, fake, worker, page, django_capture_on_commit_callbacks
):
    listed = api(alice).get("/api/v2/aieo/agents/").json()
    agents = [a["key"] for a in listed if a["group"] == "agent"]
    assert agents == AGENTS and {a["group"] for a in listed} >= {"evaluator", "rewriter", "writer", "probe"}
    site = page.get_site()
    context = api(alice).put(
        f"/api/v2/aieo/context/{site.pk}/", {"brand_voice": "# Voice\n\nPlain and warm."}, format="json"
    )
    assert context.status_code == 200 and context.json()["brand_voice"].startswith("# Voice")
    fake.script = [
        answer({"titles": ["A"], "descriptions": ["B"], "recommended_pair": {"title": "A", "description": "B"}})
    ]
    with django_capture_on_commit_callbacks(execute=True):
        ran = api(alice).post(
            "/api/v2/aieo/agents/run/", {"agent": "aieo-meta-creator", "page_id": page.pk}, format="json"
        )
    assert ran.status_code == 202, ran.content
    run = AgentRun.objects.get(public_id=ran.json()["run"]["id"])
    assert run.status == AgentRun.SUCCEEDED and run.output["json"]["recommended_pair"]["title"] == "A"
    sent = fake.calls[0]["messages"][0]["content"]
    assert "## Content\n\n# Nightly backups" in sent and "Plain and warm." in sent
    assert "meta title options" in fake.calls[0]["system"]  # AIEO's meta-creator prompt
    assert api(alice).post("/api/v2/aieo/agents/run/", {"agent": "aieo-writer"}, format="json").status_code == 422


def test_a_sites_context_and_its_search_console_rows_reach_its_editors_alone_however_asked(
    alice, bob, api, agent, fake, page, django_capture_on_commit_callbacks
):
    """The brand context, its keywords and competitors, and the priorities from a site's Search Console rows are its
    editors' (context/<site>/ is a 404 to anyone else): a score, an agent's prompt and the priorities tool ask the
    same, so none of them hands another site's to someone who names it — a person, or an agent over MCP."""
    from aieo.models import Connector, ConnectorData

    site = page.get_site()
    BrandContext.objects.update_or_create(
        site=site,
        defaults={
            "brand_voice": "# Voice\n\nTOP-SECRET-VOICE",
            "competitors": {"competitors": [], "keywords": ["secret-keyword"], "topics": ["secret topic"]},
        },
    )
    gsc = Connector.objects.create(site=site, kind=Connector.GSC, options={"site_url": "sc-domain:x"})
    ConnectorData.objects.create(connector=gsc, report="queries", rows=[{"query": "secret query", "impressions": 9}])
    other = Site.objects.create(hostname="other.example.com", port=80, root_page=site.root_page)
    for target in (site, other):  # bob edits no site: each is a 404 that names nothing, and nothing is made
        assert api(bob).get(f"/api/v2/aieo/context/{target.pk}/").status_code == 404
        scored = api(bob).post("/api/v2/aieo/score/", {"content": "hello there", "site": target.pk}, format="json")
        assert scored.status_code == 404 and "secret" not in scored.content.decode()
        ran = api(bob).post(
            "/api/v2/aieo/agents/run/", {"agent": "aieo-meta-creator", "content": "x", "site": target.pk}, format="json"
        )
        assert ran.status_code == 404
    assert not BrandContext.objects.filter(site=other).exists() and not AgentRun.objects.filter(started_by=bob).exists()
    mine = api(alice).post("/api/v2/aieo/score/", {"content": "hello there", "site": site.pk}, format="json").json()
    assert mine["result"]["keyword_analysis"]["primary"]["keyword"] == "secret-keyword"
    # An agent over MCP is asked the same: `agent:aieo` holds no page rights, so it edits no site.
    ctx = ToolContext(user=agent("aieo").user, agent=agent("aieo"))
    for name, args in (
        ("aieo.run_agent", {"agent": "meta-creator", "content": "x", "site": site.pk}),
        ("aieo.run_agent", {"agent": "meta-creator", "content": "x", "site": 999}),
        ("aieo.priorities", {"site": site.pk}),
        ("aieo_priorities", {"site": site.pk}),
    ):
        with pytest.raises(ToolError) as refused:
            registry.call(name, args, ctx)
        assert refused.value.code == "not_found" and "secret" not in refused.value.message
    assert not AgentRun.objects.filter(started_by=agent("aieo").user, input__kind="assistant").exists()


def test_the_brand_context_and_the_lifecycle_are_the_sites_editors(alice, bob, api, page):
    site = page.get_site()
    got = api(alice).get(f"/api/v2/aieo/context/{site.pk}/").json()
    assert got["target_keywords"].startswith("# Target Keywords") and got["keywords"] == []
    assert api(bob).get(f"/api/v2/aieo/context/{site.pk}/").status_code == 404
    stages = api(alice).get("/api/v2/aieo/lifecycle/", {"site": site.pk}).json()
    assert stages["published"] == 1 and stages["drafts"] == 0 and stages["landing_pages"] == 0


def test_an_agent_token_is_refused_it_works_through_the_tool_registry(api, agent, db):
    from agents.models import AgentToken

    principal = agent("aieo").user
    _, raw = AgentToken.issue(principal, name="t")
    client = api()
    client.credentials(HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert client.post("/api/v2/aieo/score/", {"content": ARTICLE}, format="json").status_code == 403
    assert principal.username == "agent:aieo"
