"""Consuming events from the other plane, each one exactly once per consumer.

Delivery is at least once, so a handler can see the same envelope twice.
`handle_envelope` validates it against the shared schemas, then records
(`event id`, `consumer`) in `ProcessedEvent` in the same transaction as the
handler's own writes: the second delivery finds the row and does nothing.

`consume_stream` reads a Redis stream through a consumer group and acks what
it handled; tests call `handle_envelope` directly. A read that waits out its
block, or times out on the socket, is a quiet stream: nothing to handle yet.

An entry is acked only once it is handled, so one whose reader died, or whose
handler raised, stays in the group's pending list: each pass first claims those
idle for `RECLAIM_IDLE_MS` (XAUTOCLAIM) and handles them again. Each entry is
handled on its own, so one that fails never stops the rest of its batch, and
after `MAX_DELIVERIES` it moves to `<stream>:dead` (with the group, the error
and its delivery count) and is acked there, for a person to read and replay.
A database or Redis error (`loop.TRANSIENT`) is no fault of the event's: it
ends the pass, the entry stays pending, and the command's loop backs off.
"""

import json
import logging

from django.db import IntegrityError, transaction
from redis.exceptions import TimeoutError as ReadTimedOut

from ops.logging import redact

from .loop import TRANSIENT
from .models import ProcessedEvent
from .schemas import check_envelope

log = logging.getLogger(__name__)

RECLAIM_IDLE_MS = 60_000  # an entry pending this long lost its reader, or its handler raised: claim it again
MAX_DELIVERIES = 5  # deliveries of an entry that keeps failing before it moves to `<stream>:dead`
DEAD_MAXLEN = 10_000  # the dead stream is bounded too, as the relay bounds the live one

HANDLERS: dict[str, dict] = {}


def handler(event_type: str, consumer: str):
    """Register `fn(envelope)` as `consumer`'s handler for `event_type`."""

    def register(fn):
        HANDLERS.setdefault(event_type, {})[consumer] = fn
        return fn

    return register


def handle_envelope(envelope: dict) -> list[str]:
    """Run every handler for this event that has not run yet; returns the
    consumers that ran."""
    check_envelope(envelope)
    ran = []
    for consumer, fn in HANDLERS.get(envelope["type"], {}).items():
        with transaction.atomic():
            try:
                # Its own savepoint, so a duplicate is the only IntegrityError
                # caught here; one from the handler's writes still propagates.
                with transaction.atomic():
                    ProcessedEvent.objects.create(event_id=envelope["id"], consumer=consumer, type=envelope["type"])
            except IntegrityError:
                log.info("events: %s already handled by %s", envelope["id"], consumer)
                continue
            fn(envelope)
        ran.append(consumer)
    return ran


def consume_stream(
    client,
    stream: str,
    group: str,
    name: str,
    count: int = 100,
    block_ms: int = 5000,
    reclaim_idle_ms: int = RECLAIM_IDLE_MS,
    max_deliveries: int = MAX_DELIVERIES,
) -> int:
    """One pass of `name` in `group`: the group's entries idle past `reclaim_idle_ms`, then new ones; returns how
    many it handled."""
    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:  # noqa: BLE001 — BUSYGROUP means the group exists, which is the usual case
        if "BUSYGROUP" not in str(exc):
            raise
    # Redis 7 answers [next start, entries, ids trimmed away while pending]; 6.2 leaves out the third.
    _next, claimed, *_trimmed = client.xautoclaim(
        stream, group, name, min_idle_time=reclaim_idle_ms, start_id="0-0", count=count
    )
    handled = handle_messages(client, stream, group, claimed, max_deliveries)
    try:
        read = client.xreadgroup(group, name, {stream: ">"}, count=count, block=block_ms)
    except ReadTimedOut:
        return handled  # nothing arrived while the socket waited; the next read asks again
    for _stream, messages in read or []:
        handled += handle_messages(client, stream, group, messages, max_deliveries)
    return handled


def handle_messages(client, stream: str, group: str, messages, max_deliveries: int = MAX_DELIVERIES) -> int:
    """Handle and ack each entry on its own; returns how many were handled."""
    handled = 0
    for message_id, fields in messages:
        if not fields:  # trimmed from the stream while it was pending (Redis 6.2 claims it empty): nothing to handle
            if message_id is not None:
                client.xack(stream, group, message_id)
            continue
        try:
            handle_envelope(json.loads(fields.get(b"event") or fields.get("event")))
        except TRANSIENT:
            raise
        except Exception as exc:  # noqa: BLE001 — one event's failure stays pending to be retried; the batch goes on
            failed(client, stream, group, message_id, fields, exc, max_deliveries)
            continue
        client.xack(stream, group, message_id)
        handled += 1
    return handled


def failed(client, stream: str, group: str, message_id, fields: dict, exc: Exception, max_deliveries: int) -> None:
    """Leave a failed entry pending for the next claim, or, at its last delivery, move it to `<stream>:dead`."""
    entries = client.xpending_range(stream, group, min=message_id, max=message_id, count=1)
    deliveries = entries[0]["times_delivered"] if entries else 0
    error = redact(f"{type(exc).__name__}: {exc}")[:2000]
    if deliveries < max_deliveries:
        log.warning(
            "events: %s on %s failed in %s, delivery %d of %d: %s",
            message_id,
            stream,
            group,
            deliveries,
            max_deliveries,
            error,
            exc_info=exc,
        )
        return
    dead = f"{stream}:dead"
    pipe = client.pipeline()  # MULTI: the entry is in the dead stream and acked, or neither
    pipe.xadd(
        dead,
        {**fields, "message_id": message_id, "group": group, "deliveries": deliveries, "error": error},
        maxlen=DEAD_MAXLEN,
        approximate=True,
    )
    pipe.xack(stream, group, message_id)
    pipe.execute()
    log.error(
        "events: %s on %s moved to %s after %d deliveries in %s: %s",
        message_id,
        stream,
        dead,
        deliveries,
        group,
        error,
        exc_info=exc,
    )
