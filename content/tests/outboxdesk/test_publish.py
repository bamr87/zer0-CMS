"""A page that goes live is announced on the belt (outboxdesk/consumers.py): not by the publish or its signal, which
write nothing to the belt, but by the transactional outbox's `content.page.published` event — the consumer, once
per event, sends a `published` handoff from the publisher station whose `ref` names the page, whose parent is the latest
delivered message about the page (an editor's approval) or else the event, and whose trace is that parent's (a page
nothing on the belt names takes the event's `traceparent`'s)."""

import json
import uuid
from pathlib import Path

import pytest
from django.conf import settings

from outbox.consumers import HANDLERS, handle_envelope
from outbox.models import OutboxEvent
from outboxdesk import services

BELT = "/api/v2/outbox/belt"


@pytest.fixture
def consumer():
    """The desk's handler, registered as `consume_events` registers it (by importing the module), and taken away
    again, so no other test's `handle_envelope` runs it — which is why nothing here imports it at collection."""
    from outboxdesk import consumers

    HANDLERS.setdefault("content.page.published", {})[consumers.CONSUMER] = consumers.page_published
    yield consumers.CONSUMER
    HANDLERS["content.page.published"].pop(consumers.CONSUMER, None)


def published_event(page):
    return OutboxEvent.objects.filter(type="content.page.published", subject=f"page:{page.pk}").latest("created_at")


def example(page, traceparent=None):
    envelope = json.loads((Path(settings.EVENTS_SCHEMA_DIR) / "examples" / "content.page.published.json").read_text())
    envelope.update(id=str(uuid.uuid4()), subject=f"page:{page.pk}")
    envelope["data"].update(page_id=page.pk, url_path=page.url_path, page_type="cms.ArticlePage")
    if traceparent is None:
        envelope.pop("traceparent")
    else:
        envelope["traceparent"] = traceparent
    return envelope


def outbox_files(station):
    return sorted((settings.OUTBOX_BELT_ROOT / "stations" / station / "outbox").glob("*.json"))


@pytest.mark.django_db
def test_a_page_that_goes_live_is_announced_by_the_outbox_events_consumer_once(article, consumer):
    event = published_event(article)  # the publish wrote the event, in its transaction …
    assert not settings.OUTBOX_BELT_ROOT.exists()  # … and nothing on the belt
    envelope = event.envelope()
    assert consumer in handle_envelope(envelope)  # with any other consumer of the event (distribution's auto-draft)
    assert handle_envelope(envelope) == []  # redelivered: handled once (ProcessedEvent)
    assert services.publish_page(envelope) is None  # and the handoff's id is the event's: never sent twice
    [path] = outbox_files("publisher")
    sent = json.loads(path.read_text())
    assert (sent["kind"], sent["from"], sent["to"], sent["subject"]) == (
        "published",
        "publisher",
        ["learner", "ledger"],
        f"page:{article.pk}",
    )
    assert sent["ref"] == {"page_id": article.pk, "url": article.full_url, "url_path": article.url_path}
    assert sent["payload"]["canonical_url"] == article.full_url and sent["payload"]["event_id"] == envelope["id"]
    assert sent["parent_id"] == envelope["id"]  # no message on the belt was about the page: the event is its parent
    expected = services.trace_of(envelope.get("traceparent")) or uuid.UUID(envelope["id"]).hex
    assert sent["trace"] == expected
    services.deliver()
    [row] = services.messages(kind="published")
    assert (row["seq"], row["id"]) == (1, sent["id"])
    assert list((settings.OUTBOX_BELT_ROOT / "stations" / "learner" / "inbox").glob("*.json"))


@pytest.mark.django_db
def test_a_published_handoff_answers_the_approval_about_its_page_and_stays_on_its_trace(api, ed, article, consumer):
    lib = services.module("belt")
    belt = services.open_belt()
    idea = lib.Handoff(kind="idea", from_station="scout-a", to=["editor", "ledger"], subject="backups")
    belt.station("scout-a").send(idea)
    belt.deliver()
    approval = (
        api(ed)
        .post(
            f"{BELT}/send/",
            {"kind": "approval", "to": ["publisher", "ledger"], "parent_id": idea.id, "page": article.pk},
            format="json",
        )
        .json()
    )
    services.deliver()

    traced = "4bf92f3577b34da6a3ce929d0e0e4736"
    with_trace = example(article, traceparent=f"00-{traced}-0000000000000001-01")
    assert consumer in handle_envelope(with_trace)
    without = example(article)
    assert consumer in handle_envelope(without)
    services.deliver()
    first, second = services.messages(kind="published", oldest_first=True)
    # The piece of work keeps its trace through the publish, whatever request published it; the request's own
    # trace stays readable in the payload.
    assert (first["parent_id"], first["trace"]) == (approval["id"], idea.trace)
    assert first["payload"]["traceparent"] == with_trace["traceparent"]
    assert (second["parent_id"], second["trace"]) == (approval["id"], idea.trace)
    assert "traceparent" not in second["payload"]
    journey = [m["kind"] for m in services.journey(idea.trace)]
    assert journey == ["idea", "approval", "published", "published"]


def test_a_traceparent_gives_its_trace_and_anything_else_none():
    assert (
        services.trace_of("00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01")
        == "4bf92f3577b34da6a3ce929d0e0e4736"
    )
    assert services.trace_of(f"00-{'0' * 32}-00f067aa0ba902b7-01") == ""
    assert services.trace_of("garbage") == "" and services.trace_of(None) == ""
