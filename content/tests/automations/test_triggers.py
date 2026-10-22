"""What fires an automation (PLAN G16): an event the platform announces — read from the stream the relay writes, by
the outbox consumer `automations`, once per event —, a schedule's tick, a signed webhook (a bad signature refused), a
new research source, and a named hook. A paused automation hears nothing; an automation hears only what its owner may
see and its own site's; its own work never fires one. Nothing reaches a network or a model."""

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta

import fakeredis
import pytest
from django.conf import settings
from wagtail.models import Site

from agents.runner import start_run
from automations import services
from automations.models import Automation, AutomationRun
from ideas.models import Idea
from outbox.consumers import consume_stream, handle_envelope
from outbox.models import OutboxEvent, ProcessedEvent
from outbox.relay import RedisStreamsRelay, relay_pending
from research import services as research
from research.models import FeedSubscription, Source

from ..conftest import make_article
from .conftest import IDEA, PUBLIC

PUBLISHED = {"kind": "event", "event": "content.page.published"}
NOTE = {"kind": "idea", "title": "Read: {{ source.title }}", "notes": "{{ source.text }}"}


def envelope(event_type: str, data: dict, **fields) -> dict:
    example = json.loads((settings.EVENTS_SCHEMA_DIR / "examples" / f"{event_type}.json").read_text())
    return {**example, "data": data, **fields}


# ── events ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_published_page_fires_an_event_automation_through_the_stream_once(alice, make, consuming, worker, site_root):
    automation = make(alice, PUBLISHED, condition="data.page_type == 'cms.ArticlePage'")
    page = make_article(site_root, "Fresh news")
    redis = fakeredis.FakeRedis()
    assert relay_pending(RedisStreamsRelay(client=redis)) >= 1  # the site's root and the article, on zer0:content
    assert worker(consume_stream, redis, settings.EVENTS_STREAM, "automations", "a1", block_ms=1) >= 1

    run = AutomationRun.objects.get(automation=automation, payload__subject=f"page:{page.pk}")
    assert (run.trigger, run.status, run.matched) == ("event", AutomationRun.SUCCEEDED, True)
    assert run.payload["type"] == "content.page.published" and run.payload["data"]["page_id"] == page.pk
    [outcome] = run.outcomes
    idea = Idea.objects.get(public_id=outcome["result"]["idea"])
    assert idea.title == f"Follow up: {page.url_path}" and idea.owner == alice
    assert outcome["input"]["title"] == idea.title  # the run logs what each action was asked
    root = AutomationRun.objects.get(automation=automation, payload__subject=f"page:{site_root.pk}")
    assert (root.status, root.matched) == (AutomationRun.SKIPPED, False)  # a site root is not an article
    automation.refresh_from_db()
    assert automation.last_run is not None

    # Delivered again, the event is handled once by the `automations` consumer.
    event = OutboxEvent.objects.get(type="content.page.published", subject=f"page:{page.pk}")
    assert handle_envelope(event.envelope()) == []
    assert ProcessedEvent.objects.filter(event_id=event.id, consumer="automations").count() == 1
    assert AutomationRun.objects.filter(automation=automation).count() == 2


@pytest.mark.django_db
def test_an_event_fires_only_enabled_automations_waiting_for_it(alice, make, worker, site_root):
    waiting = make(alice, PUBLISHED)
    paused = make(alice, PUBLISHED, enabled=False)
    other = make(alice, {"kind": "event", "event": "agent.run.completed"})
    page = make_article(site_root, "Paused or not")
    event = envelope("content.page.published", {**OutboxEvent.objects.filter(subject=f"page:{page.pk}").get().data})
    runs = worker(services.on_event, event)
    assert [r.automation for r in runs] == [waiting]
    assert not AutomationRun.objects.filter(automation__in=[paused, other]).exists()
    assert worker(services.on_event, {**event, "source": "zer0-cms/rails"}) == []  # the other plane's events
    assert worker(services.on_event, {**event, "id": "00000000-0000-4000-8000-000000000001"})  # a new event fires


@pytest.mark.django_db
def test_an_automation_hears_only_what_its_owner_may_see_and_its_own_sites(alice, bob, make, worker, site_root, agent):
    run = start_run(agent("seo"), trigger="rest", user=alice, enqueue=False)
    completed = envelope("agent.run.completed", {"run_id": run.pk, "agent": "seo", "status": "succeeded"})
    hers = make(alice, {"kind": "event", "event": "agent.run.completed"}, [IDEA])
    his = make(bob, {"kind": "event", "event": "agent.run.completed"}, [IDEA])
    assert [r.automation for r in worker(services.on_event, completed)] == [hers]  # bob may not see alice's run
    assert not AutomationRun.objects.filter(automation=his).exists()

    other_root = make_article(site_root, "Elsewhere")  # a page of the test site
    elsewhere = Site.objects.create(hostname="other.localhost", root_page=other_root)
    on_other_site = make(alice, PUBLISHED, site=elsewhere, visibility="site")
    data = OutboxEvent.objects.filter(subject=f"page:{other_root.pk}").get().data
    page = make_article(site_root, "On the test site")
    event = envelope("content.page.published", {**data, "page_id": page.pk})
    assert on_other_site not in [r.automation for r in worker(services.on_event, event)]


@pytest.mark.django_db
def test_an_automations_own_work_never_fires_an_automation(alice, make, worker, agent):
    make(alice, {"kind": "event", "event": "agent.run.completed"})
    parent = start_run(agent("seo"), trigger="event", user=alice, enqueue=False, event_id="automation-run:x")
    child = start_run(agent("seo"), trigger="event", user=alice, enqueue=False, parent=parent)
    for run in (parent, child):
        event = envelope("agent.run.completed", {"run_id": run.pk, "agent": "seo", "status": "succeeded"})
        assert worker(services.on_event, event) == []


# ── schedules ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_schedule_fires_once_for_each_tick_that_comes_due(alice, make, worker):
    automation = make(
        alice, {"kind": "schedule", "cron": "0 9 * * *"}, [{"kind": "idea", "title": "Daily: {{ cron }}"}]
    )
    eight = datetime(2026, 10, 22, 8, 0, tzinfo=UTC)
    Automation.objects.filter(pk=automation.pk).update(scheduled_at=eight)
    assert services.tick(eight.replace(minute=59)) == []
    nine = datetime(2026, 10, 22, 9, 0, 30, tzinfo=UTC)
    [run] = worker(services.tick, nine)
    assert run.trigger == "schedule" and run.payload == {"scheduled_at": nine.isoformat(), "cron": "0 9 * * *"}
    run.refresh_from_db()
    assert run.status == AutomationRun.SUCCEEDED
    assert Idea.objects.get(public_id=run.outcomes[0]["result"]["idea"]).title == "Daily: 0 9 * * *"
    assert services.tick(nine) == [] and services.tick(nine + timedelta(minutes=5)) == []  # that tick is taken
    assert len(worker(services.tick, nine + timedelta(days=1))) == 1
    Automation.objects.filter(pk=automation.pk).update(enabled=False)
    assert services.tick(nine + timedelta(days=2)) == []  # paused


def test_beat_dispatches_the_schedules_every_minute():
    entry = settings.CELERY_BEAT_SCHEDULE["automations-schedule"]
    assert entry == {"task": "automations.tasks.tick", "schedule": 60.0}


@pytest.mark.django_db
def test_the_tick_task_fires_what_is_due(alice, make, worker):
    from automations.tasks import tick

    automation = make(alice, {"kind": "schedule", "cron": "* * * * *"})
    Automation.objects.filter(pk=automation.pk).update(scheduled_at=datetime(2026, 1, 1, tzinfo=UTC))
    assert worker(tick) == 1


@pytest.mark.django_db
def test_a_trigger_changed_to_a_schedule_counts_from_then(alice, make, api):
    automation = make(alice, {"kind": "hook", "hook": "x"})
    Automation.objects.filter(pk=automation.pk).update(scheduled_at=datetime(2026, 1, 1, tzinfo=UTC))
    path = f"/api/v2/automations/{automation.public_id}/"
    daily = {"trigger": {"kind": "schedule", "cron": "0 9 * * *"}}
    assert api(alice).patch(path, daily, format="json").status_code == 200
    assert services.tick() == []  # not the nine o'clocks it missed since January


# ── webhooks ───────────────────────────────────────────────────────────────


def signed(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


@pytest.mark.django_db
def test_a_signed_webhook_fires_and_a_bad_signature_is_refused(alice, make, api, worker):
    automation = make(alice, {"kind": "webhook"}, [{"kind": "idea", "title": "Issue: {{ body.issue.title }}"}])
    secret, url = automation.get_secret(), f"/api/v2/automations/{automation.public_id}/webhook/"
    body = json.dumps({"action": "opened", "issue": {"title": "Slow archive"}}).encode()

    def post(data=body, **headers):
        return worker(api().post, url, data=data, content_type="application/json", **headers)

    assert post().status_code == 401  # unsigned
    assert post(HTTP_X_ZER0_SIGNATURE_256=signed("not the secret", body)).status_code == 401
    assert post(HTTP_X_ZER0_SIGNATURE_256=signed(secret, b"another body")).status_code == 401
    assert not AutomationRun.objects.filter(automation=automation).exists()

    answer = post(HTTP_X_ZER0_SIGNATURE_256=signed(secret, body), HTTP_X_GITHUB_EVENT="issues")
    assert answer.status_code == 202, answer.content
    run = AutomationRun.objects.get(public_id=answer.json()["run"])
    assert run.status == AutomationRun.SUCCEEDED and run.trigger == "webhook"
    assert run.payload["body"]["issue"]["title"] == "Slow archive"
    assert run.payload["headers"]["x-github-event"] == "issues"
    assert not any("signature" in name for name in run.payload["headers"])  # the signature is not kept
    assert Idea.objects.get(public_id=run.outcomes[0]["result"]["idea"]).title == "Issue: Slow archive"

    # GitHub's header is read the same way; a delivery sent again gets the run it made.
    again = {"HTTP_X_HUB_SIGNATURE_256": signed(secret, body), "HTTP_X_GITHUB_DELIVERY": "d-1"}
    first, second = post(**again), post(**again)
    assert first.status_code == second.status_code == 202 and first.json()["run"] == second.json()["run"]
    assert post(data=b"not json", HTTP_X_ZER0_SIGNATURE_256=signed(secret, b"not json")).status_code == 422
    assert api().post("/api/v2/automations/00000000-0000-4000-8000-000000000000/webhook/").status_code == 404

    services.disable(automation, user=alice)
    assert post(HTTP_X_ZER0_SIGNATURE_256=signed(secret, body)).json()["error"]["code"] == "automation.paused"
    new = services.rotate_secret(automation, user=alice)
    assert post(HTTP_X_ZER0_SIGNATURE_256=signed(secret, body)).status_code == 401  # the old secret is gone
    assert post(HTTP_X_ZER0_SIGNATURE_256=signed(new, body)).status_code == 409


@pytest.mark.django_db
def test_only_a_webhook_automation_has_a_webhook(alice, make, api):
    other = make(alice, {"kind": "hook", "hook": "x"})
    body = b"{}"
    answer = api().post(
        f"/api/v2/automations/{other.public_id}/webhook/",
        data=body,
        content_type="application/json",
        HTTP_X_ZER0_SIGNATURE_256=signed(other.get_secret(), body),
    )
    assert answer.status_code == 404


# ── new research sources ───────────────────────────────────────────────────

FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Wire</title>
<item><guid>w-1</guid><title>Bridge vote tonight</title><link>https://news.example.com/w-1</link>
<description>The council votes at seven.</description></item>
<item><guid>w-2</guid><title>Library hours</title><link>https://news.example.com/w-2</link>
<description>Longer on Sundays.</description></item>
</channel></rss>"""


@pytest.mark.django_db
def test_new_feed_items_fire_a_source_automation_once_each(alice, make, worker, web):
    feed = FeedSubscription.objects.create(owner=alice, url="https://news.example.com/wire.xml")
    automation = make(alice, {"kind": "source", "feed": str(feed.public_id)}, [NOTE])
    web.get(f"https://{PUBLIC}/wire.xml").respond(200, text=FEED, headers={"Content-Type": "application/rss+xml"})
    assert worker(research.refresh, feed) == 2
    assert worker(research.refresh, feed) == 0  # the same items are not new
    runs = AutomationRun.objects.filter(automation=automation).order_by("created_at")
    assert [r.payload["source"]["title"] for r in runs] == ["Bridge vote tonight", "Library hours"]
    assert {r.status for r in runs} == {AutomationRun.SUCCEEDED}
    assert sorted(Idea.objects.filter(owner=alice).values_list("title", flat=True)) == [
        "Read: Bridge vote tonight",
        "Read: Library hours",
    ]
    note = worker(research.add_note, alice, "Not from the feed")
    assert not AutomationRun.objects.filter(automation=automation, payload__source__id=str(note.public_id)).exists()


@pytest.mark.django_db
def test_a_captured_page_fires_once_it_is_fetched_and_only_for_who_may_see_it(alice, bob, make, worker):
    hers = make(alice, {"kind": "source"}, [NOTE])
    his = make(bob, {"kind": "source"}, [NOTE])
    # Captured, a page is pending: its fetch is queued for a worker, which this test plays below (nothing is fetched).
    source = research.capture_url(alice, "https://news.example.com/page")
    assert source.status == Source.PENDING and not AutomationRun.objects.exists()
    source.status, source.text = Source.READY, "The page's text."
    worker(source.save, update_fields=["status", "text"])
    [run] = AutomationRun.objects.all()
    assert run.automation == hers and run.payload["source"]["text"] == "The page's text."
    worker(source.save, update_fields=["status"])  # fetched again: it fired already
    assert AutomationRun.objects.count() == 1
    assert not AutomationRun.objects.filter(automation=his).exists()  # bob may not see alice's private source


# ── named hooks ────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_named_hook_fires_the_automations_waiting_for_it(alice, make, worker, site_root):
    site = Site.objects.get(root_page=site_root)
    finding = {"kind": "idea", "title": "Fix {{ data.rule }} on {{ data.url }}", "tags": ["monitor"]}
    anywhere = make(alice, {"kind": "hook", "hook": "monitor.finding"}, [finding], condition="by == 'monitor'")
    here = make(alice, {"kind": "hook", "hook": "monitor.finding"}, [finding], site=site, visibility="site")
    make(alice, {"kind": "hook", "hook": "something.else"})
    data = {"rule": "broken-link", "url": "https://example.com/a"}
    runs = worker(services.fire_hook, "monitor.finding", data, by="monitor")
    assert {r.automation for r in runs} == {anywhere, here}  # fired for no site: every site hears it
    run = AutomationRun.objects.get(pk=next(r.pk for r in runs if r.automation == anywhere))
    assert run.payload == {"hook": "monitor.finding", "by": "monitor", "site": None, "data": data}
    idea = Idea.objects.get(public_id=run.outcomes[0]["result"]["idea"])
    assert idea.title == "Fix broken-link on https://example.com/a" and list(idea.tags.names()) == ["monitor"]

    other = Site.objects.create(hostname="other.localhost", root_page=make_article(site_root, "Other root"))
    assert {r.automation for r in worker(services.fire_hook, "monitor.finding", data, site=other, by="x")} == {anywhere}
    spoofed = AutomationRun.objects.filter(automation=anywhere).latest("created_at")
    assert spoofed.status == AutomationRun.SKIPPED  # its condition insists the monitor fired it
