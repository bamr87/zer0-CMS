"""What `/readyz` checks: the database, the cache the tool rate limits live in,
and the Redis the Celery broker and the outbox relay use. Each check is short
and bounded, because a readiness probe that hangs is worse than one that says
`degraded`.

It also reports what it does not gate on (`reports`): the event pipeline behind
the web role — the oldest event the relay has not sent, and how far each
consumer group on `EVENTS_STREAM` is behind. Past `OUTBOX_LAG_SECONDS` or
`EVENTS_LAG_ENTRIES` the status is `degraded`, but the probe still answers 200:
the web role serves while the relay is down, and the relay waits for this probe
before it starts (docker-compose.yml), so refusing here would keep it down."""

import uuid

from django.conf import settings
from django.core.cache import caches
from django.db import connection
from django.utils import timezone
from redis.exceptions import ResponseError

from outbox.models import OutboxEvent


class Behind(Exception):
    """A dependency that answers but has fallen behind."""


def check_db():
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")


def check_cache():
    cache = caches["default"]
    key = f"readyz:{uuid.uuid4().hex}"
    cache.set(key, "ok", 5)
    if cache.get(key) != "ok":
        raise RuntimeError("cache read-after-write failed")
    cache.delete(key)


def redis_client():
    import redis

    return redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5, socket_timeout=0.5)


def check_redis():
    redis_client().ping()


def check_outbox():
    behind = []
    # The (dispatched_at, created_at) index answers this without a scan.
    pending = OutboxEvent.objects.filter(dispatched_at__isnull=True).order_by("created_at")
    oldest = pending.values_list("created_at", flat=True).first()
    if oldest is not None:
        age = (timezone.now() - oldest).total_seconds()
        if age > settings.OUTBOX_LAG_SECONDS:
            behind.append(f"oldest undispatched event {age:.0f} s old")
    try:
        groups = redis_client().xinfo_groups(settings.EVENTS_STREAM)
    except ResponseError:
        groups = []  # no stream yet: nothing was ever relayed, so no group can be behind
    for group in groups:
        # Entries the group has not read yet; Redis leaves it unset when it cannot say (after a trim).
        lag = group.get("lag")
        if lag is not None and lag > settings.EVENTS_LAG_ENTRIES:
            name = group["name"].decode() if isinstance(group["name"], bytes) else group["name"]
            behind.append(f"group {name} {lag} entries behind")
    if behind:
        raise Behind("; ".join(behind))


def checks() -> dict:
    """What readiness needs: one failing is a 503. Looked up at call time, so a test can replace one check."""
    return {"db": check_db, "cache": check_cache, "redis": check_redis}


def reports() -> dict:
    """What readiness reports and does not gate on."""
    return {"outbox": check_outbox}


def run_checks(which: dict | None = None) -> dict[str, str]:
    results = {}
    for name, check in (checks() if which is None else which).items():
        try:
            check()
            results[name] = "ok"
        except Behind as e:
            results[name] = f"degraded: {e}"
        except Exception as e:  # noqa: BLE001 — readiness reports a failing dependency, it does not raise
            results[name] = f"error: {type(e).__name__}"
    return results
