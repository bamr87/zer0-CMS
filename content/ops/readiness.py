"""What `/readyz` checks: the database, the cache the tool rate limits live in,
and the Redis the Celery broker and the outbox relay use. Each check is short
and bounded, because a readiness probe that hangs is worse than one that says
`degraded`."""

import uuid

from django.conf import settings
from django.core.cache import caches
from django.db import connection


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


def checks() -> dict:
    """Looked up at call time, so a test can replace one check."""
    return {"db": check_db, "cache": check_cache, "redis": check_redis}


def run_checks() -> dict[str, str]:
    results = {}
    for name, check in checks().items():
        try:
            check()
            results[name] = "ok"
        except Exception as e:  # noqa: BLE001 — readiness reports a failing dependency, it does not raise
            results[name] = f"error: {type(e).__name__}"
    return results
