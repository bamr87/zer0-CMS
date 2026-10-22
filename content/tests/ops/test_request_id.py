"""Every response carries a request id (echoed when safe, else fresh) and the
app version; the request id and the W3C trace id are independent."""

import uuid

import pytest


def test_a_missing_request_id_is_generated_as_uuid4(client):
    assert uuid.UUID(client.get("/healthz")["X-Request-Id"]).version == 4


def test_an_incoming_request_id_is_echoed(client):
    assert client.get("/healthz", HTTP_X_REQUEST_ID="req-abc.123:x")["X-Request-Id"] == "req-abc.123:x"


@pytest.mark.parametrize("unsafe", ["x" * 300, "has space", "-leading-dash", "tab\there", "quote'd"])
def test_an_unsafe_request_id_is_replaced(client, unsafe):
    echoed = client.get("/healthz", HTTP_X_REQUEST_ID=unsafe)["X-Request-Id"]
    assert echoed != unsafe
    assert uuid.UUID(echoed).version == 4


@pytest.mark.django_db
def test_every_response_carries_the_app_version(client, settings):
    for path in ("/healthz", "/api/v2/nope/", "/admin/login/"):
        assert client.get(path)["X-App-Version"] == settings.APP_VERSION


def test_request_id_and_trace_id_are_independent(client):
    trace = "4bf92f3577b34da6a3ce929d0e0e4736"
    response = client.get("/healthz", HTTP_X_REQUEST_ID="abc", HTTP_TRACEPARENT=f"00-{trace}-00f067aa0ba902b7-01")
    assert response["X-Request-Id"] == "abc"
    assert response["traceparent"].split("-")[1] == trace
