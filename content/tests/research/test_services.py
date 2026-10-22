"""The research library's services (research/services.py) and its runs
(research/handlers.py): a captured page is fetched by a worker under the guard,
robots.txt honoured, and extracted; a document is read on upload; a feed brings
its new items once; summaries, cited answers, fact-checks and web searches are
runs of the `assistant` agent whose results a person reviews — a fact-check's
corrections are suggestions on the draft, never edits. HTTP is recorded,
names resolve from a table, and the provider is the scripted fake."""

import json
from datetime import timedelta
from decimal import Decimal

import httpx
import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings
from django.utils import timezone

from agents.models import AgentRun
from ai import providers
from ai import services as ai_services
from ai.models import Assistant, Brief, ProviderConfig
from graph.models import Embedding
from ops.errors import Forbidden, Invalid
from research import services
from research.models import Collection, FeedSubscription, Source
from research.tasks import refresh_feeds
from suggestions.models import Suggestion
from suggestions.services import accept

from ..ai.test_services import DETAIL
from ..conftest import make_article
from .conftest import FEED, at, tiny_pdf

SUMMARY = {
    "summary": "Nightly backups save small sites.",
    "key_points": ["A second disk is enough", "Test your restores"],
    "entities": [{"name": "Ada Lovelace", "kind": "person"}],
    "quotes": ["A nightly backup to a second disk costs almost nothing"],
}


def fresh(row):
    row.refresh_from_db()
    return row


# ── gathering ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_captured_page_is_fetched_by_a_worker_extracted_and_embedded(alice, site_web, worker):
    collection = Collection.objects.create(owner=alice, name="Backups")
    source = worker(services.capture_url, alice, "https://example.com/backups", collection=collection)
    source = fresh(source)
    assert (source.kind, source.status, source.robots, source.error) == ("url", "ready", "unknown", "")
    assert (source.title, source.author, source.site_name, source.published) == (
        "Backups explained",
        "Ada Lovelace",
        "Example News",
        "2026-10-01",
    )
    assert "A nightly backup to a second disk" in source.text and source.fetched_at is not None
    assert source.metadata["content_type"].startswith("text/html") and source.collection == collection
    assert Embedding.objects.filter(kind="source", object_id=source.pk).exists()


@pytest.mark.django_db
def test_a_page_off_the_public_web_or_closed_by_robots_txt_is_refused_and_says_why(alice, web, worker):
    with pytest.raises(Invalid, match="not a public address"):
        services.capture_url(alice, "http://127.0.0.1:8000/admin/")
    inside = fresh(worker(services.capture_url, alice, "http://intranet.example.com/wiki"))
    assert inside.status == "failed" and "not a public address" in inside.error and web.calls.call_count == 0
    web.get(at("/robots.txt")).respond(200, text="User-agent: *\nDisallow: /members\n")
    closed = fresh(worker(services.capture_url, alice, "https://example.com/members/list"))
    assert (closed.status, closed.robots) == ("failed", "disallowed") and "robots.txt" in closed.error
    web.get(at("/gone")).respond(404)
    missing = fresh(worker(services.capture_url, alice, "https://example.com/gone"))
    assert missing.status == "failed" and missing.error == "the site answered HTTP 404" and missing.robots == "allowed"
    web.get(at("/notes.txt")).respond(200, content=b"Plain\x00 notes.", headers={"Content-Type": "text/plain"})
    plain = fresh(worker(services.capture_url, alice, "https://example.com/notes.txt"))
    assert (plain.status, plain.text) == ("ready", "Plain notes.")  # a NUL would fail the save on Postgres


@pytest.mark.django_db
def test_a_document_is_read_on_upload_and_a_note_kept_as_written(alice):
    pdf = services.upload(alice, SimpleUploadedFile("backups.pdf", tiny_pdf(), content_type="application/pdf"))
    assert (pdf.kind, pdf.status, pdf.title, pdf.text) == (
        "document",
        "ready",
        "Nightly Backups",
        "Backups save the day.",
    )
    assert pdf.metadata["pages"] == 1 and pdf.metadata["file_name"] == "backups.pdf"
    guide = services.upload(alice, SimpleUploadedFile("guide.md", b"# Restores\n\nTest them.", "text/markdown"))
    assert guide.title == "Restores" and guide.text == "# Restores\n\nTest them."
    with pytest.raises(Invalid, match="is not a web page, a PDF or text"):
        services.upload(alice, SimpleUploadedFile("photo.png", b"\x89PNG", content_type="image/png"))
    with override_settings(RESEARCH_UPLOAD_MAX_BYTES=10), pytest.raises(Invalid, match="at most 10 bytes"):
        services.upload(alice, SimpleUploadedFile("big.txt", b"x" * 11, content_type="text/plain"))
    unicode = SimpleUploadedFile("notepad.txt", "Restore drills\r\nOnce a quarter.".encode("utf-16"), "text/plain")
    saved = services.upload(alice, unicode)  # stored on Postgres too, which refuses a NUL in text
    assert (saved.title, saved.text) == ("Restore drills", "Restore drills\r\nOnce a quarter.")
    note = services.add_note(alice, "\n  Call the hosting company\nabout restores.")
    assert (note.kind, note.title, note.status) == ("note", "Call the hosting company", "ready")
    with pytest.raises(Invalid):
        services.add_note(alice, "   ")


@pytest.mark.django_db
def test_a_feed_brings_its_new_items_once_and_records_a_failure(alice, web, django_capture_on_commit_callbacks):
    route = web.get(at("/feed.xml")).mock(
        side_effect=[
            httpx.Response(200, text=FEED, headers={"ETag": '"v1"', "Content-Type": "application/rss+xml"}),
            httpx.Response(304),
            httpx.Response(500),
        ]
    )
    collection = Collection.objects.create(owner=alice, name="Wires")
    with django_capture_on_commit_callbacks(execute=True):
        feed = services.subscribe(alice, "https://example.com/feed.xml", collection=collection, interval_minutes=30)
    feed = fresh(feed)
    items = Source.objects.filter(feed=feed).order_by("guid")
    assert [(s.kind, s.guid, s.title, s.collection) for s in items] == [
        ("feed", "a-1", "Backups, weekly", collection),
        ("feed", "a-2", "Restores, tested", collection),
    ]
    assert items[0].text == "Weekly backups are not enough." and items[0].url == "https://news.example.com/a-1"
    assert (feed.title, feed.etag, feed.error) == ("Example News", '"v1"', "")
    assert feed.next_check_at - feed.last_checked_at == timedelta(minutes=30)
    assert services.refresh(feed) == 0 and route.calls.last.request.headers["if-none-match"] == '"v1"'
    assert services.refresh(feed) == 0 and fresh(feed).error == "the feed answered HTTP 500"
    assert Source.objects.filter(feed=feed).count() == 2


@pytest.mark.django_db
def test_a_feed_whose_body_is_a_path_on_the_worker_brings_nothing_from_that_file(alice, web, tmp_path):
    local = tmp_path / "secret-feed.xml"
    local.write_text(FEED.replace("Example News", "A FILE ON THE WORKER"))
    web.get(at("/evil.xml")).respond(200, content=str(local).encode(), headers={"Content-Type": "application/rss+xml"})
    feed = FeedSubscription.objects.create(owner=alice, url="https://example.com/evil.xml")
    assert services.refresh(feed) == 0
    feed = fresh(feed)
    assert (feed.title, feed.error) == ("", "not a feed it can read")
    assert not Source.objects.filter(feed=feed).exists()


@pytest.mark.django_db
def test_beat_claims_and_reads_only_the_feeds_that_are_due_and_never_twice(alice, web):
    route = web.get(at("/due.xml")).respond(200, text=FEED)
    due = FeedSubscription.objects.create(owner=alice, url="https://example.com/due.xml")
    later = FeedSubscription.objects.create(
        owner=alice, url="https://example.com/later.xml", next_check_at=timezone.now() + timedelta(hours=1)
    )
    FeedSubscription.objects.create(owner=alice, url="https://example.com/off.xml", active=False)
    assert refresh_feeds() == 1  # the due feed, read in a task of its own
    assert fresh(due).last_checked_at is not None and fresh(later).last_checked_at is None
    assert Source.objects.filter(feed=due).count() == 2
    assert services.claim(due.pk) is False  # its next check moved on when it was claimed
    assert refresh_feeds() == 0 and route.calls.call_count == 1


@pytest.mark.django_db
def test_a_worker_writes_only_what_its_fetch_owns_and_never_brings_back_a_deleted_row(alice, site_root, site_web):
    from wagtail.models import Site

    site = Site.objects.get(root_page=site_root)
    source = Source.objects.create(
        owner=alice, kind="url", url="https://example.com/backups", status="pending", site=site, visibility="site"
    )
    stale = Source.objects.get(pk=source.pk)  # what the worker loaded before its network round trip
    Source.objects.filter(pk=source.pk).update(visibility="private", title="A person's title")  # meanwhile
    services.fetch_into(stale)
    source = fresh(source)
    assert (source.visibility, source.title, source.status) == ("private", "A person's title", "ready")
    assert "A nightly backup" in source.text and source.author == "Ada Lovelace"
    gone = Source.objects.create(owner=alice, kind="url", url="https://example.com/backups", status="pending")
    stale = Source.objects.get(pk=gone.pk)
    Source.objects.filter(pk=gone.pk).delete()  # the person deletes it while it is fetched
    assert services.fetch_into(stale) is None and not Source.objects.filter(pk=gone.pk).exists()


@pytest.mark.django_db
def test_a_feed_paused_or_deleted_while_it_is_read_takes_nothing(alice, web):
    web.get(at("/feed.xml")).respond(200, text=FEED)
    feed = FeedSubscription.objects.create(owner=alice, url="https://example.com/feed.xml", title="Mine")
    stale = FeedSubscription.objects.get(pk=feed.pk)
    FeedSubscription.objects.filter(pk=feed.pk).update(active=False, interval_minutes=120)  # paused meanwhile
    assert services.refresh(stale) == 0
    feed = fresh(feed)
    assert (feed.active, feed.interval_minutes, feed.last_checked_at) == (False, 120, None)
    assert not Source.objects.filter(feed=feed).exists()
    FeedSubscription.objects.filter(pk=feed.pk).update(active=True)
    stale = FeedSubscription.objects.get(pk=feed.pk)
    FeedSubscription.objects.filter(pk=feed.pk).delete()  # deleted meanwhile
    assert services.refresh(stale) == 0
    assert not FeedSubscription.objects.filter(pk=feed.pk).exists() and not Source.objects.exists()
    kept = FeedSubscription.objects.create(owner=alice, url="https://example.com/feed.xml", title="Mine")
    assert services.refresh(kept) == 2 and fresh(kept).title == "Mine"  # a title a person gave stays


@pytest.mark.django_db
def test_a_fetch_whose_result_cannot_be_stored_says_so_rather_than_stay_fetching(alice, site_web, monkeypatch):
    from django.db import DataError

    def refuse(*args):
        raise DataError("PostgreSQL text fields cannot contain NUL (0x00) bytes")

    monkeypatch.setattr(services, "_fetched", refuse)
    source = Source.objects.create(owner=alice, kind="url", url="https://example.com/backups", status="pending")
    assert services.fetch_into(source).status == "failed"
    assert (fresh(source).status, fresh(source).error) == ("failed", "the page could not be stored")


# ── the AI steps ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_summary_entities_and_quotes_arrive_on_the_source_from_a_run(alice, bob, fake, worker):
    source = services.add_note(alice, "A nightly backup to a second disk costs almost nothing. Ada Lovelace agreed.")
    fake.script.append({"text": json.dumps(SUMMARY), "tokens_in": 300, "tokens_out": 80})
    run = fresh(worker(services.summarize, source, user=alice))
    assert (run.status, run.agent.slug, run.input["kind"], run.target_id) == (
        "succeeded",
        "assistant",
        "research.summarize",
        source.pk,
    )
    source = fresh(source)
    assert source.summary == "Nightly backups save small sites.\n\n- A second disk is enough\n- Test your restores"
    assert source.entities == SUMMARY["entities"] and source.highlights == SUMMARY["quotes"]
    assert source.summary_run == run and run.tokens == 380
    call = fake.calls[0]
    assert call["schema"]["required"] == ["summary", "key_points", "entities", "quotes"]
    assert call["system"].startswith("You read one source") and "Ada Lovelace agreed." in call["messages"][0]["content"]
    with pytest.raises(Forbidden):
        services.summarize(source, user=bob)


@pytest.mark.django_db
def test_a_question_is_answered_from_the_closest_sources_and_its_quotes_checked(
    alice, fake, worker, django_capture_on_commit_callbacks
):
    collection = Collection.objects.create(owner=alice, name="Backups")
    with django_capture_on_commit_callbacks(execute=True):
        basics = services.add_note(
            alice,
            "Small sites should take nightly backups to a second disk.\n\nRestores must be tested.",
            collection=collection,
            title="Backup basics",
        )
        services.add_note(alice, "Sourdough wants a warm kitchen.", collection=collection, title="Bread")
        services.add_note(alice, "Nightly backups to a second disk, elsewhere.", title="Not in the collection")
    answer = {
        "answer": "Take nightly backups to a second disk [S1].",
        "citations": [
            {"source": "S1", "quote": "Small sites should take  nightly backups to a second disk."},
            {"source": "[S1]", "quote": "Words the source never says."},
            {"source": "S9", "quote": "A source it was not given."},
        ],
    }
    fake.script.append({"text": json.dumps(answer)})
    question = fresh(
        worker(services.ask, alice, "Should small sites take nightly backups to a second disk?", collection=collection)
    )
    assert question.answer == "Take nightly backups to a second disk [S1]." and question.run.status == "succeeded"
    assert [(c["label"], c["title"], c["verified"]) for c in question.citations] == [
        ("S1", "Backup basics", True),
        ("S1", "Backup basics", False),
    ]
    assert question.citations[0]["source"] == str(basics.public_id)
    request = fake.calls[0]["messages"][0]["content"]
    assert "[S1] Backup basics" in request and "Not in the collection" not in request
    with pytest.raises(Invalid, match="no sources"):
        services.ask(alice, "Anything?", collection=Collection.objects.create(owner=alice, name="Empty"))


@pytest.mark.django_db
def test_a_fact_check_turns_corrections_into_suggestions_and_changes_nothing_itself(alice, fake, worker, site_root):
    page = make_article(
        site_root,
        "Backup advice",
        body=[{"type": "markdown", "value": "Back up weekly."}, {"type": "markdown", "value": "Keep two copies."}],
        publish=False,
    )
    first, second = (block.id for block in page.body)
    guide = services.add_note(alice, "Back up nightly, never just weekly.", title="Backup guide")
    services.cite(alice, guide, page=page)
    findings = {
        "summary": "One claim is wrong.",
        "findings": [
            {
                "block": "B1",
                "claim": "Back up weekly",
                "verdict": "contradicted",
                "explanation": "The guide says nightly.",
                "sources": ["S1"],
                "correction": "Back up nightly.",
            },
            {
                "block": "B2",
                "claim": "Keep two copies",
                "verdict": "unsupported",
                "explanation": "No source speaks to it.",
                "sources": [],
                "correction": "",
            },
        ],
    }
    fake.script.append({"text": json.dumps(findings)})
    check = fresh(worker(services.fact_check, page, user=alice))
    suggestion = Suggestion.objects.get(run=check.run)
    assert (suggestion.op, suggestion.block_id, suggestion.status, suggestion.agent.slug) == (
        "replace",
        first,
        "pending",
        "assistant",
    )
    assert suggestion.payload == {"type": "markdown", "value": "Back up nightly."}
    assert "Fact-check (contradicted)" in suggestion.rationale and "Backup guide" in suggestion.rationale
    assert [f["suggestion"] for f in check.findings] == [suggestion.pk, None]
    assert [f["block"] for f in check.findings] == [first, second] and check.summary == "One claim is wrong."
    assert check.findings[0]["sources"] == [{"id": str(guide.public_id), "title": "Backup guide"}]
    request = fake.calls[0]["messages"][0]["content"]
    assert "[B1] Back up weekly." in request and "[S1] Backup guide" in request
    page.refresh_from_db()
    assert page.get_latest_revision_as_object().body[0].value == "Back up weekly."  # nothing changed until accepted
    accept([suggestion], alice)
    page.refresh_from_db()
    assert page.get_latest_revision_as_object().body[0].value == "Back up nightly."


@pytest.mark.django_db
def test_a_fact_check_needs_text_sources_and_the_right_to_edit_and_respects_a_page_policy_off(
    alice, bob, fake, worker, site_root
):
    page = make_article(
        site_root, "Claims", body=[{"type": "markdown", "value": "Water boils at 90 C."}], publish=False
    )
    with pytest.raises(Invalid, match="cite sources"):
        services.fact_check(page, user=alice)
    source = services.add_note(alice, "Water boils at 100 C at sea level.", title="Physics")
    services.cite(alice, source, page=page)
    with pytest.raises(Forbidden):
        services.fact_check(page, user=bob)
    type(page).objects.filter(pk=page.pk).update(agent_policy="off")  # agents may do nothing on this page
    fake.script.append(
        {
            "text": json.dumps(
                {
                    "summary": "Wrong.",
                    "findings": [
                        {
                            "block": "B1",
                            "claim": "90 C",
                            "verdict": "contradicted",
                            "explanation": "100 C.",
                            "sources": ["S1"],
                            "correction": "Water boils at 100 C.",
                        }
                    ],
                }
            )
        }
    )
    check = fresh(worker(services.fact_check, page, user=alice))
    assert check.run.status == "succeeded" and check.findings[0]["suggestion"] is None
    assert not Suggestion.objects.filter(run=check.run).exists()


@pytest.mark.django_db
def test_a_web_search_goes_through_a_provider_that_can_and_its_hits_become_sources(
    alice, worker, site_web, hits, monkeypatch
):
    from .conftest import SearchingFake

    for name in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(Invalid, match="no provider here can search"):
        services.search_web(alice, "backups")
    collection = Collection.objects.create(owner=alice, name="Found")
    with providers.override(SearchingFake(hits), "fake") as searching:
        run = fresh(worker(services.search_web, alice, "backups", collection=collection, max_results=3))
    assert run.status == "succeeded" and searching.searches == [("backups", 3)]
    assert (run.cost_usd, run.tokens, run.llm_backend) == (Decimal("0.011"), 50, "fake")
    assert run.steps.get().name == "web_search · fake-1"
    found = Source.objects.get(url="https://example.com/backups")
    assert (found.collection, found.status, found.title) == (collection, "ready", "Backups explained")
    assert found.metadata["search"] == {"query": "backups", "snippet": "A nightly backup", "published": "2026-10-01"}
    assert not Source.objects.filter(url__startswith="ftp").exists() and run.output["sources"] == [str(found.public_id)]
    ProviderConfig.objects.filter(slug="fake").update(enabled=False)
    with providers.override(SearchingFake(hits), "fake"), pytest.raises(Exception, match="disabled"):
        services.search_web(alice, "backups", provider="fake")


@pytest.mark.django_db
def test_a_brief_reads_the_sources_it_cites_and_a_research_brief_is_a_run(alice, bob, fake, worker):
    restores = services.add_note(alice, "Restores must be tested every month.", title="Restore guide")
    secret = services.add_note(bob, "Bob's private notes.", title="Bob's")
    brief = Brief.objects.create(
        owner=alice, prompt="Write about restores", assistant=Assistant.objects.create(owner=alice, name="Writer")
    )
    services.cite(alice, restores, brief=brief)
    services.cite(bob, secret, brief=Brief.objects.create(owner=bob, prompt="Bob's brief"))
    with pytest.raises(Forbidden):
        services.cite(bob, secret, brief=brief)
    fake.script += [{"text": "A draft about restores."}, {"text": json.dumps(DETAIL)}]
    run = fresh(worker(ai_services.generate_brief, brief, user=alice))
    request = fake.calls[0]["messages"][0]["content"]
    assert run.status == "succeeded" and request.startswith("Write about restores")
    assert "Restore guide" in request and "Restores must be tested every month." in request and "Bob" not in request
    collection = Collection.objects.create(owner=alice, name="Restores")
    Source.objects.filter(pk=restores.pk).update(collection=collection)
    fake.script.append({"text": "## Target intent\n\nTo restore with confidence."})
    brief_run = fresh(worker(services.research_brief, collection, user=alice, topic="restores"))
    assert brief_run.status == "succeeded" and brief_run.output["markdown"].startswith("## Target intent")
    assert fake.calls[-1]["system"].startswith("You write a content research brief")
    assert "Restore guide" in fake.calls[-1]["messages"][0]["content"]
    assert AgentRun.objects.filter(pk=brief_run.pk, agent__slug="assistant").exists()
