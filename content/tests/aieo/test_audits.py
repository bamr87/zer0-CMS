"""Audits of a text, a page, a URL and a crawled site: each a run of the `assistant` agent that scores with the
heuristics and — when a model's evaluation is asked for — has the bundled evaluator score it through the AI layer
(AIEO's system prompt, rubric and patterns, its answer held to the rubric's schema), the heuristics standing in when
the provider fails. URLs and crawls go through the research library's guarded fetcher (respx answers; robots.txt
honoured, private addresses refused); the visual audit's browser is faked. The reports AIEO wrote for its ten site
audits come out byte for byte from the audits imported here."""

import json
from datetime import datetime
from pathlib import Path

import pytest
from django.conf import settings
from django.core.files.storage import default_storage
from django.core.management import call_command

from agents.models import AgentRun
from ai import providers
from ai.providers.base import ProviderError
from ai.providers.fake import FakeProvider
from aieo import parser, reports, scoring, services, visual
from aieo.models import Audit
from ops.errors import Forbidden, Invalid

from .conftest import answer, at, evaluation

HERE = Path(__file__).resolve().parent
ARTICLE = (HERE / "fixtures" / "article.md").read_text(encoding="utf-8")
ROBOTS_OFF = "User-agent: *\nDisallow: /private/\n"


def audited(row) -> Audit:
    row.refresh_from_db()
    return row


def test_a_text_audit_is_a_run_the_evaluator_scores_with_aieos_prompt_and_schema(alice, fake, worker):
    fake.script = [answer(evaluation(0.5, penalties=5))]
    row = audited(worker(services.audit, alice, kind="text", content=ARTICLE, method="ai"))
    assert row.status == Audit.READY and row.run.status == AgentRun.SUCCEEDED
    assert row.scoring_method == "ai" and row.score == 45.0 and row.grade == "F"
    assert row.result["executive_summary"] and row.result["priority_actions"][0]["title"] == "Add sources"
    assert set(row.result["dimensions"]) == {"aieo", "seo", "readability", "humanity", "cro"}
    call = fake.calls[0]
    assert call["system"] == scoring.prompt("system.md")
    patterns = scoring.bundled_patterns()
    assert call["messages"][0]["content"] == scoring.evaluation_prompt(parser.parse(ARTICLE), patterns)
    assert call["schema"]["properties"]["patterns"]["required"] == [p["name"] for p in patterns]


def test_a_provider_that_fails_leaves_the_heuristic_score_and_says_why(alice, fake, worker):
    fake.script = [ProviderError("the provider is down")]
    row = audited(worker(services.audit, alice, kind="text", content=ARTICLE, method="ai"))
    assert row.status == Audit.READY and row.scoring_method == "heuristic"
    assert row.score == scoring.score(ARTICLE)["score"] == 52.0
    assert "the provider is down" in row.result["fallback"]


def test_a_heuristic_audit_asks_no_model_and_reads_the_sites_keywords(alice, fake, worker, site):
    from aieo.models import BrandContext

    context = BrandContext.for_site(site)
    context.target_keywords = "- Pillar keyword: backup\n- Long-tail variations: restore test, offsite copy\n"
    context.competitors = {"competitors": [], "keywords": [], "topics": ["pricing", "migration", "restore"]}
    context.save()
    row = audited(worker(services.audit, alice, kind="text", content=ARTICLE, method="heuristic", site=site))
    assert fake.calls == [] and row.scoring_method == "heuristic"
    assert row.result["keyword_analysis"]["primary"]["keyword"] == "backup"
    assert [k["keyword"] for k in row.result["keyword_analysis"]["secondary"]] == ["restore test", "offsite copy"]
    # The two analyzers AIEO exported and never wired: engagement, and the competitors' topics the text misses.
    assert row.result["competitor_gaps"]["missing_topics"] == ["pricing", "migration"]
    assert row.result["engagement"]["questions"] == 4


def test_an_audit_can_name_the_engine_that_evaluates_it(alice, fake, worker):
    with providers.override(FakeProvider([answer(evaluation(1.0, penalties=0))]), "openai") as openai:
        row = audited(worker(services.audit, alice, kind="text", content=ARTICLE, method="ai", provider="openai"))
    assert row.score == 100.0 and row.result["provider"] == "fake" and len(openai.calls) == 1 and fake.calls == []
    with pytest.raises(Invalid):
        services.audit(alice, kind="text", content=ARTICLE, method="ai", provider="nope")


def test_a_page_audit_reads_its_latest_revision_for_someone_who_edits_it(alice, bob, fake, worker, page):
    row = audited(worker(services.audit, alice, kind="page", page=page, method="heuristic"))
    assert row.status == Audit.READY and row.title == "Nightly backups" and row.site_id == page.get_site().pk
    assert row.result["pattern_scores"]["definitional_precision"]["detected"]
    with pytest.raises(Forbidden):
        services.audit(bob, kind="page", page=page, method="heuristic")
    assert list(services.history(alice, page=page)) == [row]


def test_a_url_is_fetched_through_the_guard_and_robots_txt_is_honoured(alice, fake, worker, web):
    web.get(at("/robots.txt")).respond(200, text=ROBOTS_OFF)
    html = (HERE / "fixtures" / "page.html").read_text(encoding="utf-8")
    web.get(at("/services/")).respond(200, text=html, headers={"Content-Type": "text/html; charset=utf-8"})
    row = audited(worker(services.audit, alice, kind="url", url="https://example.com/services/", method="heuristic"))
    assert row.status == Audit.READY and row.title.startswith("Sopris Accounting")
    assert row.score == scoring.score(html, "html")["score"]
    shut = audited(worker(services.audit, alice, kind="url", url="https://example.com/private/x", method="heuristic"))
    assert shut.status == Audit.FAILED and "robots.txt" in shut.error
    with pytest.raises(Invalid):
        services.audit(alice, kind="url", url="http://10.0.0.5/admin", method="heuristic")
    with pytest.raises(Invalid):
        services.audit(alice, kind="url", url="file:///etc/passwd", method="heuristic")


SITEMAP = """<?xml version="1.0"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
<url><loc>https://example.com/</loc></url><url><loc>https://example.com/a/</loc></url>
<url><loc>https://example.com/b/</loc></url><url><loc>https://example.com/tag/x/</loc></url></urlset>"""


def _page(title, links=(), body="Backups are copies of a site, kept elsewhere."):
    anchors = "".join(f'<a href="{link}">{link}</a> ' for link in links)
    return f"<html><head><title>{title}</title></head><body><h1>{title}</h1><p>{body}</p>{anchors}</body></html>"


def test_a_site_is_crawled_cheap_first_and_scored_page_by_page_with_its_link_map(alice, fake, worker, web):
    html = {"Content-Type": "text/html"}
    web.get(at("/robots.txt")).respond(
        200, text="User-agent: *\nDisallow: /secret/\nSitemap: https://example.com/map.xml\n"
    )
    web.get(at("/map.xml")).respond(200, text=SITEMAP, headers={"Content-Type": "application/xml"})
    for feed in ("/feed.xml", "/atom.xml", "/feed/", "/rss.xml"):
        web.get(at(feed)).respond(404)
    web.get(at("/")).respond(200, text=_page("Home", ["/a/", "/c/", "/secret/plans", "/tag/x/"]), headers=html)
    web.get(at("/a/")).respond(200, text=_page("A", ["/", "/c/"]), headers=html)
    web.get(at("/b/")).respond(200, text=_page("B"), headers=html)
    web.get(at("/c/")).respond(500)
    row = audited(worker(services.audit, alice, kind="site", url="https://example.com/", method="heuristic"))
    assert row.status == Audit.READY
    assert [(p["url"], p["found_by"]) for p in row.pages] == [
        ("https://example.com/", "seed"),
        ("https://example.com/a/", "sitemap"),
        ("https://example.com/b/", "sitemap"),
        ("https://example.com/c/", "link"),
    ]
    assert row.pages[3]["score"] is None and "HTTP 500" in row.pages[3]["error"]
    read = [p["score"] for p in row.pages if p["score"] is not None]
    assert row.score == round(sum(read) / len(read), 1)
    site = row.result["site"]
    assert site["discovery"]["source"] == "sitemap" and site["robots"] == "present" and site["unread"] == 1
    assert site["link_map"]["orphans"] == ["https://example.com/b/"]
    assert site["link_map"]["hubs"][0] == {"url": "https://example.com/a/", "inbound": 1}
    assert not [c for c in web.calls if "/secret/" in str(c.request.url) or "/tag/" in str(c.request.url)]


class Seeing(FakeProvider):
    capabilities = FakeProvider.capabilities | {"vision"}


def test_the_visual_audit_screenshots_the_page_and_the_evaluator_sees_it(alice, worker, web, api, monkeypatch):
    web.get(at("/robots.txt")).respond(404)
    web.get(at("/")).respond(200, text=_page("Home"), headers={"Content-Type": "text/html"})
    monkeypatch.setattr(settings, "AIEO_VISUAL_AUDIT", True)
    monkeypatch.setattr(visual, "capture", lambda url: b"\x89PNG-screenshot")
    with providers.override(Seeing([answer(evaluation(0.8))])) as seeing:
        row = audited(worker(services.audit, alice, kind="url", url="https://example.com/", method="ai", visual=True))
    content = seeing.calls[0]["messages"][0]["content"]
    assert isinstance(content, list) and content[1]["type"] == "image" and "Screenshot" in content[0]["text"]
    assert row.status == Audit.READY and default_storage.exists(row.screenshot)
    got = api(alice).get(f"/api/v2/aieo/audits/{row.public_id}/screenshot/")
    assert got.status_code == 200 and b"".join(got.streaming_content) == b"\x89PNG-screenshot"


def test_without_playwright_the_visual_audit_says_so_and_scores_the_text(alice, fake, worker, web, monkeypatch):
    web.get(at("/robots.txt")).respond(404)
    web.get(at("/")).respond(200, text=_page("Home"), headers={"Content-Type": "text/html"})
    row = audited(
        worker(services.audit, alice, kind="url", url="https://example.com/", method="heuristic", visual=True)
    )
    assert row.status == Audit.READY and "AIEO_VISUAL_AUDIT" in row.result["visual"] and not row.screenshot


def test_a_screenshot_reaches_each_vendor_in_its_own_shape_and_claude_code_reads_the_text():
    from ai.providers.anthropic import anthropic_messages
    from ai.providers.base import openai_messages
    from ai.providers.claude_code import transcript

    image = visual.image_part(b"ABC")
    messages = [{"role": "user", "content": [{"type": "text", "text": "Look."}, image]}]
    assert image == {"type": "image", "media_type": "image/png", "data": "QUJD"}
    source = {"type": "base64", "media_type": "image/png", "data": "QUJD"}
    assert anthropic_messages(messages)[0]["content"] == [
        {"type": "text", "text": "Look."},
        {"type": "image", "source": source},
    ]
    assert openai_messages("", messages)[0]["content"][1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/png;base64,QUJD"},
    }
    assert transcript(messages) == "Look." and "vision" in providers.provider_class("anthropic").capabilities


class Route:
    """A Playwright route, as `through_guard` uses it."""

    def __init__(self, url, method="GET"):
        self.request = type("Request", (), {"url": url, "method": method})()
        self.fulfilled, self.aborted = None, False

    def fulfill(self, **answer):
        self.fulfilled = answer

    def abort(self):
        self.aborted = True


def test_every_request_the_browser_makes_goes_through_the_guarded_fetcher(web):
    web.get(at("/style.css")).respond(200, text="body{}", headers={"Content-Type": "text/css", "Content-Length": "6"})
    styles = Route("https://example.com/style.css")
    visual.through_guard(styles)
    assert styles.fulfilled["status"] == 200 and styles.fulfilled["body"] == b"body{}"
    assert "content-length" not in {k.lower() for k in styles.fulfilled["headers"]}
    inside, post = Route("http://10.0.0.5/admin"), Route("https://example.com/form", method="POST")
    visual.through_guard(inside)
    visual.through_guard(post)
    assert inside.aborted and post.aborted and len(web.calls) == 1


def test_an_audit_is_benchmarked_against_the_others_and_the_engines_that_cite_its_domain(alice, fake, worker, web):
    from aieo.models import CitationCheck, CitationQuery

    for text in ("We make websites.", "# Short\n\nA page.", ARTICLE):
        worker(services.audit, alice, kind="text", content=text, method="heuristic")
    best = Audit.objects.get(content=ARTICLE)
    assert best.benchmark["compared_with"] == 2 and best.benchmark["percentile"] == 100.0
    # Its neighbours in meaning (graph.Embedding, kind audit — the platform's vectors in place of AIEO's Qdrant).
    near = best.benchmark["similar"]
    assert (
        len(near) == 2
        and {n["target"] for n in near} == {"the text"}
        and near[0]["similarity"] >= near[1]["similarity"]
    )
    from graph.models import Embedding

    assert Embedding.objects.filter(kind="audit").count() == 3
    best.delete()
    assert Embedding.objects.filter(kind="audit").count() == 2  # a deleted audit's vector goes with it
    query = CitationQuery.objects.create(owner=alice, prompt="Who explains backups?", domain="example.com")
    for engine, hit in (("fake", True), ("fake", False), ("openai", True)):
        CitationCheck.objects.create(query=query, engine=engine, status=CitationCheck.READY, cited=hit)
    web.get(at("/robots.txt")).respond(404)
    web.get(at("/")).respond(200, text=_page("Home"), headers={"Content-Type": "text/html"})
    row = audited(worker(services.audit, alice, kind="url", url="https://example.com/", method="heuristic"))
    assert row.benchmark["engines"] == {
        "fake": {"checks": 2, "cited": 1, "rate": 0.5},
        "openai": {"checks": 1, "cited": 1, "rate": 1.0},
    }


def test_a_run_that_ends_without_succeeding_fails_its_audit(alice, fake, worker):
    from agents.runner import _finish

    row = services.audit(alice, kind="text", content="x", method="heuristic")  # queued, never executed here
    _finish(row.run, AgentRun.REFUSED, error="assistant has policy off")
    assert audited(row).status == Audit.FAILED and audited(row).error == "assistant has policy off"


def test_a_run_that_scores_is_stopped_at_its_time_limit(alice, monkeypatch, django_capture_on_commit_callbacks):
    """Scoring a long text takes time with the square of a long paragraph (Python-Markdown), so an audit's run and a
    rewrite's (it scores the text before and after) are queued with a time limit, soft and then hard."""
    from agents.tasks import run_agent

    queued = []
    monkeypatch.setattr(run_agent, "apply_async", lambda args, kwargs=None, **options: queued.append((args, options)))
    with django_capture_on_commit_callbacks(execute=True):
        audit = services.audit(alice, kind="text", content="# Backups", method="heuristic")
        rewrite = services.rewrite(alice, mode="scrub", content="Copies — of a site.")
    limit = settings.AIEO_RUN_TIME_LIMIT
    assert queued == [
        ((audit.run.pk,), {"soft_time_limit": limit, "time_limit": limit + 30}),
        ((rewrite.pk,), {"soft_time_limit": limit, "time_limit": limit + 30}),
    ]


FIXED = datetime(2026, 10, 22, 12, 0, 0)


def test_aieos_ten_site_audits_import_as_history_and_report_as_aieo_reported_them(db):
    source = settings.REPO_ROOT / "apps" / "aieo" / "reports"
    call_command("aieo", "import-reports", "--path", str(source))
    call_command("aieo", "import-reports", "--path", str(source))  # idempotent
    rows = list(Audit.objects.filter(batch="aieo-reports"))
    assert len(rows) == 10 and {r.status for r in rows} == {Audit.READY} and {r.scoring_method for r in rows} == {"ai"}
    golden = HERE / "golden" / "reports"
    data = sorted((reports.data_of(r) for r in rows), key=lambda d: d["_name"])
    for item in data:
        assert reports.site_report(item, FIXED) == (golden / f"{item['_name']}.md").read_text(encoding="utf-8")
    assert reports.summary_report(data, FIXED) == (golden / "REPORT.md").read_text(encoding="utf-8")
    summary = json.loads((source / "summary.json").read_text())
    assert {r.url.strip() for r in rows} == {s["url"].strip() for s in summary}


def test_the_reports_keep_the_scorers_pattern_order_where_the_database_reorders_keys(db):
    """Postgres's jsonb hands an object back with its keys in its own order (shortest first), so patterns that tie
    would list differently than on SQLite; the reports follow the order Audit.save kept beside them instead."""
    source = settings.REPO_ROOT / "apps" / "aieo" / "reports"
    call_command("aieo", "import-reports", "--path", str(source))
    for row in Audit.objects.filter(batch="aieo-reports"):
        scores = row.result["pattern_scores"]
        jsonb = dict(sorted(scores.items(), key=lambda kv: (len(kv[0]), kv[0])))
        Audit.objects.filter(pk=row.pk).update(result={**row.result, "pattern_scores": jsonb})  # what Postgres returns
    golden = HERE / "golden" / "reports"
    data = sorted((reports.data_of(r) for r in Audit.objects.filter(batch="aieo-reports")), key=lambda d: d["_name"])
    for item in data:
        assert reports.site_report(item, FIXED) == (golden / f"{item['_name']}.md").read_text(encoding="utf-8")
    assert reports.summary_report(data, FIXED) == (golden / "REPORT.md").read_text(encoding="utf-8")
