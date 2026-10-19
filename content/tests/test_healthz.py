"""/healthz answers 200 with the database reachable (M3's readiness probe)."""

import pytest


@pytest.mark.django_db
def test_healthz_reports_ok(client):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}
    assert response["traceparent"].startswith("00-")


@pytest.mark.django_db
def test_an_incoming_traceparent_is_kept(client):
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    response = client.get("/healthz", HTTP_TRACEPARENT=f"00-{trace}-00f067aa0ba902b7-01")
    assert response["traceparent"].split("-")[1] == trace
