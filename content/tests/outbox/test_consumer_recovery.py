"""The event pipeline outlives its own failures (W1-10): a consumer reclaims what a dead reader left pending, retries
a handler that raised, moves an event that keeps failing to `<stream>:dead` without stopping the batch, and the relay
and consumer loops wait out a database or Redis blip instead of exiting, touching a heartbeat after every pass."""

import json
import uuid
from pathlib import Path

import fakeredis
import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import OperationalError
from redis.exceptions import ConnectionError as RedisConnectionError

from ops import heartbeat
from outbox import loop
from outbox.consumers import HANDLERS, MAX_DELIVERIES, consume_stream, handler
from outbox.models import ProcessedEvent

STREAM = "zer0:test"
GROUP = "platform"


def envelope(**changes) -> dict:
    example = Path(settings.EVENTS_SCHEMA_DIR) / "examples" / "content.page.published.json"
    return {**json.loads(example.read_text()), "id": str(uuid.uuid4()), **changes}


def put(redis, env: dict) -> bytes:
    return redis.xadd(STREAM, {"id": env["id"], "type": env["type"], "event": json.dumps(env)})


def pending(redis) -> list:
    return redis.xpending_range(STREAM, GROUP, min="-", max="+", count=100)


@pytest.fixture
def only(monkeypatch):
    """Only this test's handlers see content.page.published (distribution's drafts are tested where they live)."""
    monkeypatch.setitem(HANDLERS, "content.page.published", {})

    def register(fn):
        return handler("content.page.published", consumer="test.recovery")(fn)

    return register


@pytest.fixture
def redis():
    client = fakeredis.FakeRedis()
    client.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
    return client


@pytest.mark.django_db
def test_an_entry_a_dead_reader_left_pending_is_handled_on_the_next_pass(redis, only):
    seen = []
    only(lambda env: seen.append(env["id"]))
    event = envelope()
    put(redis, event)
    # A consumer reads the entry and dies before its ack: the entry sits in the group's pending list, and a read of
    # new entries ('>') never returns it again.
    redis.xreadgroup(GROUP, "crashed-1", {STREAM: ">"}, count=10)
    assert len(pending(redis)) == 1

    # Younger than the reclaim idle time, it is still its reader's.
    assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1) == 0
    assert seen == []
    assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0) == 1
    assert seen == [event["id"]]
    assert pending(redis) == []


@pytest.mark.django_db
def test_a_handler_that_raises_once_is_retried_and_handled_exactly_once(redis, only):
    calls, done = [], []

    @only
    def flaky(env):
        calls.append(env["id"])
        if len(calls) == 1:
            raise RuntimeError("the site's config could not be read")
        done.append(env["id"])

    event = envelope()
    put(redis, event)
    assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0) == 0
    assert [p["times_delivered"] for p in pending(redis)] == [1]  # left pending, not acked and not lost
    assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0) == 1
    assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0) == 0
    assert calls == [event["id"], event["id"]]
    assert done == [event["id"]]
    assert ProcessedEvent.objects.filter(event_id=event["id"], consumer="test.recovery").count() == 1
    assert pending(redis) == []
    assert redis.xlen(f"{STREAM}:dead") == 0


@pytest.mark.django_db
def test_an_event_that_always_fails_is_dead_lettered_and_the_batch_goes_on(redis, only):
    poison, good, handled = envelope(subject="page:1"), envelope(subject="page:2"), []

    @only
    def picky(env):
        if env["id"] == poison["id"]:
            raise ValueError("no page 1")
        handled.append(env["id"])

    poison_id = put(redis, poison)
    put(redis, good)
    # The first pass reads both: the poison one fails and the next one in the same batch is still handled.
    assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0) == 1
    assert handled == [good["id"]]
    for _ in range(MAX_DELIVERIES - 1):
        assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0) == 0

    assert pending(redis) == []  # acked once it was moved
    [(_, dead)] = redis.xrange(f"{STREAM}:dead")
    assert json.loads(dead[b"event"])["id"] == poison["id"]
    assert dead[b"message_id"] == poison_id and dead[b"group"] == GROUP.encode()
    assert dead[b"deliveries"] == str(MAX_DELIVERIES).encode()
    assert dead[b"error"] == b"ValueError: no page 1"
    assert handled == [good["id"]]
    assert consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0) == 0
    assert redis.xlen(f"{STREAM}:dead") == 1


@pytest.mark.django_db
def test_a_database_error_in_a_handler_is_not_the_events_fault(redis, only):
    """A blip ends the pass for the loop to back off; the entry stays pending, and nothing is dead-lettered."""

    @only
    def down(env):
        raise OperationalError("the database system is in recovery mode")

    put(redis, envelope())
    with pytest.raises(OperationalError):
        consume_stream(redis, STREAM, GROUP, "platform-1", block_ms=1, reclaim_idle_ms=0)
    assert len(pending(redis)) == 1
    assert redis.xlen(f"{STREAM}:dead") == 0


class Stop(Exception):
    """Ends a loop that would otherwise run for as long as its container."""


def scripted(*outcomes):
    """A pass that raises or returns each outcome in turn, then stops the loop."""
    calls = []

    def step(*args, **kwargs):
        calls.append(1)
        if len(calls) > len(outcomes):
            raise Stop
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    step.calls = calls
    return step


@pytest.fixture
def sleeps(monkeypatch, tmp_path):
    """The loops' sleeps and dropped connections, recorded; heartbeats go to tmp_path."""
    monkeypatch.setenv("HEARTBEAT_DIR", str(tmp_path))
    record = {"sleeps": [], "closed": 0}
    monkeypatch.setattr(loop, "sleep", record["sleeps"].append)
    monkeypatch.setattr(loop, "close_old_connections", lambda: record.update(closed=record["closed"] + 1))
    return record


BLIP = OperationalError("the database system is in recovery mode")


@pytest.mark.django_db
def test_the_relay_survives_a_database_blip_and_writes_a_heartbeat_each_loop(monkeypatch, sleeps):
    from outbox.management.commands import relay_outbox

    relay = scripted(BLIP, 0)
    monkeypatch.setattr(relay_outbox, "relay_pending", relay)
    assert heartbeat.age("relay") is None
    with pytest.raises(Stop):
        call_command("relay_outbox", "--interval", "2")
    assert len(relay.calls) == 3  # the pass after the blip ran, and the one after its idle wait
    assert sleeps["sleeps"] == [loop.FIRST_DELAY, 2.0]  # backed off once, then waited out an empty outbox
    assert sleeps["closed"] == 1  # the connection the blip broke was dropped, so the next pass opens a new one
    assert 0 <= heartbeat.age("relay") < 60


@pytest.mark.django_db
def test_the_consumer_survives_a_redis_blip(monkeypatch, sleeps):
    import redis as redis_lib

    from outbox.management.commands import consume_events

    monkeypatch.setattr(redis_lib.Redis, "from_url", classmethod(lambda cls, url, **kw: object()))
    blip = RedisConnectionError("Error 111 connecting to redis:6379. Connection refused.")
    consume = scripted(blip, blip, 0)
    monkeypatch.setattr(consume_events, "consume_stream", consume)
    with pytest.raises(Stop):
        call_command("consume_events", "--own", "--group", "platform", "--name", "platform-1")
    # Two blips back off 1 s, then 2 s; a pass that finds nothing does not sleep, since the read itself blocks.
    assert sleeps["sleeps"] == [loop.FIRST_DELAY, 2 * loop.FIRST_DELAY]
    assert len(consume.calls) == 4
    assert heartbeat.age("consumer-platform-1") is not None


def test_the_backoff_doubles_to_its_cap_and_starts_over_after_a_good_pass(sleeps):
    down = RedisConnectionError("down")
    loop_step = scripted(*[down] * 7, 0, down, 1)
    with pytest.raises(Stop):
        loop.run(loop_step, heartbeat="test", idle=5.0)
    assert sleeps["sleeps"] == [1.0, 2.0, 4.0, 8.0, 16.0, loop.MAX_DELAY, loop.MAX_DELAY, 5.0, 1.0]


def test_any_other_error_still_ends_the_loop(sleeps):
    """A bug is not a blip: the process exits and says so, rather than retrying it forever."""
    with pytest.raises(KeyError):
        loop.run(scripted(KeyError("type")), heartbeat="test")
    assert sleeps["sleeps"] == []
    assert heartbeat.age("test") is None
