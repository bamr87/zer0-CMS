"""/healthz answers while touching nothing, /readyz names the dependency that
is down, /version reports the build (UPS-BE-10, BE-11)."""

import tomllib
from pathlib import Path

import fakeredis
import pytest


def test_healthz_touches_no_dependency(client):
    # No django_db marker on purpose: pytest-django refuses every database
    # connection in this test, so a probe that opened one would fail it.
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response["Cache-Control"] == "no-store"
    assert response["traceparent"].startswith("00-")


def test_an_incoming_traceparent_is_kept(client):
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    response = client.get("/healthz", HTTP_TRACEPARENT=f"00-{trace}-00f067aa0ba902b7-01")
    assert response["traceparent"].split("-")[1] == trace


def test_healthz_is_get_only(client):
    assert client.post("/healthz").status_code == 405


@pytest.mark.django_db
def test_readyz_reports_every_check_ok(client, monkeypatch):
    monkeypatch.setattr("ops.readiness.redis_client", lambda: fakeredis.FakeRedis())
    response = client.get("/readyz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"db": "ok", "cache": "ok", "redis": "ok"}}


@pytest.mark.django_db
def test_readyz_is_degraded_when_redis_is_unreachable(client, settings):
    settings.REDIS_URL = "redis://127.0.0.1:1/0"
    response = client.get("/readyz")
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["checks"]["db"] == "ok"
    assert body["checks"]["redis"].startswith("error:")


@pytest.mark.django_db
def test_readyz_is_degraded_when_the_database_fails(client, monkeypatch):
    def down():
        raise RuntimeError("down")

    monkeypatch.setattr("ops.readiness.check_db", down)
    monkeypatch.setattr("ops.readiness.redis_client", lambda: fakeredis.FakeRedis())
    response = client.get("/readyz")
    assert response.status_code == 503
    assert response.json()["checks"]["db"] == "error: RuntimeError"


def test_version_reports_name_version_commit_and_built_at(client, settings):
    pyproject = tomllib.loads((Path(settings.BASE_DIR) / "pyproject.toml").read_text())
    body = client.get("/version").json()
    assert body == {
        "name": "zer0-content",
        "version": pyproject["project"]["version"],
        "commit": settings.GIT_SHA,
        "built_at": settings.BUILT_AT,
    }
