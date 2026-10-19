"""Moving outbox rows onto the bus, at least once (PLAN-D6: Redis Streams).

A relay has one method, `publish(stream, envelope)`. `RedisStreamsRelay`
XADDs each envelope to a stream with a bounded length; `MemoryRelay` keeps
them in a list for tests. NATS, if it is ever chosen, is a third class here
and nothing else changes.

`relay_pending` publishes undelivered rows oldest first and then marks them.
If the process dies between the two, the row is published again on the next
pass — which is why consumers dedupe on the envelope id (`consumers.py`). On
Postgres, rows are claimed with `SKIP LOCKED`, so two relays never send the
same batch at once.
"""

import json
import logging

from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone

from .models import OutboxEvent

log = logging.getLogger(__name__)


class MemoryRelay:
    def __init__(self):
        self.published: list[tuple[str, dict]] = []

    def publish(self, stream: str, envelope: dict) -> None:
        self.published.append((stream, envelope))


class RedisStreamsRelay:
    def __init__(self, client=None, maxlen: int = 100_000):
        if client is None:
            import redis

            client = redis.Redis.from_url(settings.REDIS_URL)
        self.client = client
        self.maxlen = maxlen

    def publish(self, stream: str, envelope: dict) -> None:
        self.client.xadd(
            stream,
            {"id": envelope["id"], "type": envelope["type"], "event": json.dumps(envelope, sort_keys=True)},
            maxlen=self.maxlen,
            approximate=True,
        )


_memory = MemoryRelay()


def default_relay():
    return _memory if settings.OUTBOX_RELAY == "memory" else RedisStreamsRelay()


def memory_relay() -> MemoryRelay:
    return _memory


def relay_pending(relay=None, stream: str | None = None, batch: int = 100) -> int:
    """Publish up to `batch` undelivered events; returns how many went out."""
    relay = relay or default_relay()
    stream = stream or settings.EVENTS_STREAM
    sent = 0
    with transaction.atomic():
        pending = OutboxEvent.objects.filter(dispatched_at__isnull=True).order_by("created_at", "id")
        if connection.vendor == "postgresql":
            pending = pending.select_for_update(skip_locked=True)
        for event in list(pending[:batch]):
            try:
                relay.publish(stream, event.envelope())
            except Exception as exc:  # noqa: BLE001 — any transport failure is recorded on the row and retried
                event.attempts += 1
                event.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                event.save(update_fields=["attempts", "last_error"])
                log.warning("outbox: %s not delivered (%s); will retry", event.id, event.last_error)
                break  # keep order: nothing after a failed event goes out before it
            event.attempts += 1
            event.dispatched_at = timezone.now()
            event.last_error = ""
            event.save(update_fields=["attempts", "dispatched_at", "last_error"])
            sent += 1
    return sent
