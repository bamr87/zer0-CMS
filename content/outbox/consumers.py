"""Consuming events from the other plane, each one exactly once per consumer.

Delivery is at least once, so a handler can see the same envelope twice.
`handle_envelope` validates it against the shared schemas, then records
(`event id`, `consumer`) in `ProcessedEvent` in the same transaction as the
handler's own writes: the second delivery finds the row and does nothing.

`consume_stream` reads a Redis stream through a consumer group and acks what
it handled; tests call `handle_envelope` directly.
"""

import json
import logging

from django.db import IntegrityError, transaction

from .models import ProcessedEvent
from .schemas import check_envelope

log = logging.getLogger(__name__)

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


def consume_stream(client, stream: str, group: str, name: str, count: int = 100, block_ms: int = 5000) -> int:
    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except Exception as exc:  # noqa: BLE001 — BUSYGROUP means the group exists, which is the usual case
        if "BUSYGROUP" not in str(exc):
            raise
    handled = 0
    for _stream, messages in client.xreadgroup(group, name, {stream: ">"}, count=count, block=block_ms) or []:
        for message_id, fields in messages:
            raw = fields.get(b"event") or fields.get("event")
            handle_envelope(json.loads(raw))
            client.xack(stream, group, message_id)
            handled += 1
    return handled
