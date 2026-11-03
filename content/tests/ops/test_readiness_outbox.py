"""/readyz reports an event pipeline that has fallen behind (W1-10): the oldest event the relay has not sent, and a
consumer group's lag on the platform's stream. Reported, never refused: the web role still serves, and the relay that
would drain the backlog waits for this probe before it starts (docker-compose.yml)."""

from datetime import timedelta

import fakeredis
import pytest
from django.utils import timezone

from outbox.models import OutboxEvent
from outbox.services import emit

RUN = "3f2b8c1e-9d4a-4e7b-b6c5-0a1d2e3f4a5b"


@pytest.fixture
def redis(monkeypatch):
    client = fakeredis.FakeRedis()
    monkeypatch.setattr("ops.readiness.redis_client", lambda: client)
    return client


def undispatched(age: timedelta) -> OutboxEvent:
    event = emit("agent.run.completed", {"run_id": RUN, "agent": "seo", "status": "succeeded"}, version=2)
    OutboxEvent.objects.filter(pk=event.pk).update(created_at=timezone.now() - age)
    return event


@pytest.mark.django_db
def test_an_outbox_the_relay_keeps_up_with_is_ok(client, redis, settings):
    OutboxEvent.objects.update(dispatched_at=timezone.now())
    undispatched(timedelta(seconds=settings.OUTBOX_LAG_SECONDS - 30))
    body = client.get("/readyz").json()
    assert body["status"] == "ok"
    assert body["checks"]["outbox"] == "ok"


@pytest.mark.django_db
def test_an_old_undispatched_event_makes_readyz_degraded_but_still_ready(client, redis, settings):
    OutboxEvent.objects.update(dispatched_at=timezone.now())
    undispatched(timedelta(seconds=settings.OUTBOX_LAG_SECONDS + 600))
    response = client.get("/readyz")
    assert response.status_code == 200  # the web role serves; only the pipeline behind it is late
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"] == body["checks"]["redis"] == "ok"
    assert body["checks"]["outbox"].startswith("degraded: oldest undispatched event ")


@pytest.mark.django_db
def test_a_consumer_group_far_behind_makes_readyz_degraded(client, redis, settings):
    OutboxEvent.objects.update(dispatched_at=timezone.now())
    settings.EVENTS_LAG_ENTRIES = 2
    redis.xgroup_create(settings.EVENTS_STREAM, "outboxdesk", id="0", mkstream=True)
    redis.xgroup_create(settings.EVENTS_STREAM, "platform", id="0")
    for n in range(4):
        redis.xadd(settings.EVENTS_STREAM, {"event": str(n)})
    redis.xreadgroup("platform", "platform-1", {settings.EVENTS_STREAM: ">"}, count=10)
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["checks"]["outbox"] == "degraded: group outboxdesk 4 entries behind"


@pytest.mark.django_db
def test_no_stream_yet_is_not_a_lag(client, redis):
    OutboxEvent.objects.update(dispatched_at=timezone.now())
    assert client.get("/readyz").json()["checks"]["outbox"] == "ok"


@pytest.mark.django_db
def test_a_failing_outbox_report_does_not_refuse_readiness(client, redis, monkeypatch):
    def broken():
        raise RuntimeError("down")

    monkeypatch.setattr("ops.readiness.check_outbox", broken)
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["checks"]["outbox"] == "error: RuntimeError"
