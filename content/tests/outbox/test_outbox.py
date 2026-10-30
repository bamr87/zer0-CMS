"""The transactional outbox (M8): one row per publish, in the publish's
transaction; at-least-once relay in order; consumers that dedupe by id."""

import json
import uuid
from pathlib import Path

import fakeredis
import pytest
from django.conf import settings
from django.db import transaction

from outbox.consumers import HANDLERS, consume_stream, handle_envelope, handler
from outbox.models import OutboxEvent, ProcessedEvent
from outbox.relay import MemoryRelay, RedisStreamsRelay, relay_pending
from outbox.services import OutboxError, emit

from ..conftest import make_article

RUN = "3f2b8c1e-9d4a-4e7b-b6c5-0a1d2e3f4a5b"  # a run's public id


@pytest.mark.django_db
def test_publishing_a_page_writes_exactly_one_outbox_row(site_root):
    before = OutboxEvent.objects.filter(type="content.page.published").count()
    page = make_article(site_root, "Outbox", publish=False)
    assert OutboxEvent.objects.filter(type="content.page.published").count() == before
    with transaction.atomic():
        page.get_latest_revision().publish()
    events = OutboxEvent.objects.filter(type="content.page.published", subject=f"page:{page.pk}")
    assert events.count() == 1
    data = events.get().data
    assert data["page_id"] == page.pk and data["page_type"] == "cms.ArticlePage"
    assert data["content_hash"] == page.specific.compute_content_hash()


@pytest.mark.django_db
def test_a_failed_publish_leaves_no_event(site_root):
    page = make_article(site_root, "Rolled back", publish=False)
    with pytest.raises(RuntimeError), transaction.atomic():
        page.get_latest_revision().publish()
        raise RuntimeError("the request failed after the publish")
    assert not OutboxEvent.objects.filter(subject=f"page:{page.pk}", type="content.page.published").exists()


def test_emit_refuses_to_run_outside_a_transaction():
    # pytest-django's db fixture wraps a test in a transaction, so this test
    # deliberately has no database access at all.
    with pytest.raises(OutboxError, match="inside the transaction"):
        emit("agent.run.completed", {"run_id": RUN, "agent": "x", "status": "succeeded"}, version=2)


@pytest.mark.django_db
def test_emit_validates_data_against_the_shared_schema():
    from outbox.schemas import EventSchemaError

    with pytest.raises(EventSchemaError, match="status"):
        emit("agent.run.completed", {"run_id": RUN, "agent": "x", "status": "exploded"}, version=2)
    with pytest.raises(EventSchemaError, match="run_id"):  # v2 names a run by its public id, never its integer key
        emit("agent.run.completed", {"run_id": 1, "agent": "x", "status": "succeeded"}, version=2)


@pytest.mark.django_db
def test_the_relay_delivers_in_order_and_retries_after_a_failure():
    OutboxEvent.objects.all().update(dispatched_at="2026-01-01T00:00:00Z")
    first = emit("agent.run.completed", {"run_id": RUN, "agent": "a", "status": "succeeded"}, version=2)
    second = emit("agent.run.completed", {"run_id": str(uuid.uuid4()), "agent": "a", "status": "failed"}, version=2)

    class Flaky(MemoryRelay):
        calls = 0

        def publish(self, stream, envelope):
            Flaky.calls += 1
            if Flaky.calls == 1:
                raise ConnectionError("bus down")
            super().publish(stream, envelope)

    relay = Flaky()
    assert relay_pending(relay) == 0
    first.refresh_from_db()
    assert first.dispatched_at is None and first.attempts == 1 and "bus down" in first.last_error
    assert relay_pending(relay) == 2
    assert [e["id"] for _, e in relay.published] == [str(first.id), str(second.id)]
    assert relay_pending(relay) == 0


@pytest.mark.django_db
def test_redis_streams_relay_and_consumer_round_trip():
    redis = fakeredis.FakeRedis()
    OutboxEvent.objects.all().update(dispatched_at="2026-01-01T00:00:00Z")
    event = emit("app.user.interaction", {"anon_id": "abcdef123456", "page_id": 1, "kind": "view"})
    event.source = "zer0-cms/app"
    event.save()
    assert relay_pending(RedisStreamsRelay(client=redis), stream="zer0:app") == 1
    seen = []
    HANDLERS["app.user.interaction"]["test.collector"] = lambda env: seen.append(env["id"])
    try:
        assert consume_stream(redis, "zer0:app", "content", "t1", block_ms=1) == 1
        assert consume_stream(redis, "zer0:app", "content", "t1", block_ms=1) == 0
    finally:
        del HANDLERS["app.user.interaction"]["test.collector"]
    assert seen == [str(event.id)]


@pytest.mark.django_db
def test_a_redelivered_event_is_handled_once_per_consumer(monkeypatch):
    calls = []
    # Only this test's consumer: the platform's own (distribution's drafts) are tested where they live.
    monkeypatch.setitem(HANDLERS, "content.page.published", {})

    @handler("content.page.published", consumer="test.once")
    def count(envelope):
        calls.append(envelope["id"])

    try:
        envelope = json.loads(
            (Path(settings.EVENTS_SCHEMA_DIR) / "examples" / "content.page.published.json").read_text()
        )
        assert handle_envelope(envelope) == ["test.once"]
        assert handle_envelope(envelope) == []
        assert calls == [envelope["id"]]
        assert ProcessedEvent.objects.filter(event_id=envelope["id"], consumer="test.once").count() == 1
    finally:
        del HANDLERS["content.page.published"]["test.once"]


def test_consume_events_waits_out_an_idle_stream(monkeypatch):
    """The read blocks for BLOCK_MS on an idle stream; a socket timeout no longer than that killed the consumer
    (redis-py 8 defaults it to 5 s, the block's length) on its first quiet spell."""
    import redis
    from django.core.management import call_command

    from outbox.management.commands import consume_events

    seen = {}
    monkeypatch.setattr(redis.Redis, "from_url", classmethod(lambda cls, url, **kw: seen.update(kw) or object()))
    monkeypatch.setattr(consume_events, "consume_stream", lambda *a, **kw: seen.update(block_ms=kw["block_ms"]) or 0)
    call_command("consume_events", "--once")
    assert seen["socket_timeout"] > seen["block_ms"] / 1000
