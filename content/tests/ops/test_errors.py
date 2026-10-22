"""Every non-2xx a REST path returns is the one envelope (UPS-BE-20..22):
DRF's own exceptions, the platform's `ApiError`, Django's 404 for an unknown
API path, and a crash — which names the request id and never its traceback."""

import json
import logging

import pytest

from ops.logging import JsonFormatter

pytestmark = pytest.mark.django_db


def envelope(response):
    body = response.json()["error"]
    assert set(body) == {"code", "message", "status", "details", "request_id", "retry_after"}
    assert body["request_id"] == response["X-Request-Id"]
    assert body["status"] == response.status_code
    return body


def test_401_envelope_keeps_www_authenticate(client, api_urls):
    response = client.get("/api/v2/_test/unauthenticated/")
    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith("Bearer")
    assert envelope(response)["code"] == "auth.required"


def test_403_envelope(client, api_urls):
    response = client.get("/api/v2/_test/forbidden/")
    assert response.status_code == 403
    assert envelope(response)["code"] == "auth.forbidden"


def test_404_envelope_from_a_drf_view(client, api_urls):
    response = client.get("/api/v2/_test/missing/")
    assert response.status_code == 404
    assert envelope(response)["code"] == "resource.not_found"


def test_404_envelope_for_an_unknown_api_path(client):
    response = client.get("/api/v2/nope/")
    assert response.status_code == 404
    body = envelope(response)
    assert body["code"] == "resource.not_found"
    assert body["details"] == [] and body["retry_after"] is None


def test_405_envelope(client, api_urls):
    response = client.post("/api/v2/_test/ok/")
    assert response.status_code == 405
    assert envelope(response)["code"] == "request.method_not_allowed"


def test_422_envelope_has_per_field_details(client, api_urls):
    response = client.get("/api/v2/_test/invalid/")
    assert response.status_code == 422
    body = envelope(response)
    assert body["code"] == "validation.failed"
    assert body["message"] == "validation failed"
    assert body["details"] == [{"field": "title", "code": "required", "message": "This field is required."}]


def test_500_envelope_never_leaks_a_stack_trace(raw_client, api_urls):
    lines = []

    class Capture(logging.Handler):
        def emit(self, record):
            lines.append(self.format(record))

    handler = Capture()
    handler.setFormatter(JsonFormatter(app="zer0", version="test"))
    logger = logging.getLogger("django.request")
    logger.addHandler(handler)
    try:
        response = raw_client.get("/api/v2/_test/crash/")
    finally:
        logger.removeHandler(handler)
    assert response.status_code == 500
    body = envelope(response)
    assert body["code"] == "internal.error"
    assert b"boom" not in response.content
    logged = [json.loads(line) for line in lines]
    assert any(entry["request_id"] == response["X-Request-Id"] and "boom" in entry.get("exc", "") for entry in logged)


def test_api_error_carries_its_own_code_and_status(client, api_urls):
    response = client.get("/api/v2/_test/teapot/")
    assert response.status_code == 418
    body = envelope(response)
    assert body["code"] == "demo.teapot" and body["message"] == "short and stout"


def test_html_paths_keep_the_default_error_pages(client):
    response = client.get("/this-path-does-not-exist/")
    assert response.status_code == 404
    assert response["Content-Type"].startswith("text/html")


def test_json_is_answered_with_json_anywhere(client):
    response = client.get("/this-path-does-not-exist/", HTTP_ACCEPT="application/json")
    assert response.status_code == 404
    assert envelope(response)["code"] == "resource.not_found"


def test_rest_views_use_the_envelope(client, editor):
    client.force_login(editor)
    assert envelope(client.get("/api/v2/agent-runs/999/"))["code"] == "resource.not_found"
    body = envelope(client.get("/api/v2/graph/search/"))
    assert body["code"] == "validation.failed"
    assert body["details"][0]["field"] == "q"
