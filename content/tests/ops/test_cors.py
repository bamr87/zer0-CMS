"""Browser origins are an allowlist, applied to the API paths only, and the
platform's own headers are exposed to scripts (UPS-BE-06)."""

import pytest

pytestmark = pytest.mark.django_db
ALLOWED = "https://allowed.example"


def test_preflight_from_an_allowed_origin(client):
    response = client.options("/api/v2/tools/", HTTP_ORIGIN=ALLOWED, HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET")
    assert response.status_code == 200
    assert response["Access-Control-Allow-Origin"] == ALLOWED
    allowed = response["Access-Control-Allow-Headers"].lower()
    assert "authorization" in allowed and "x-request-id" in allowed and "traceparent" in allowed


def test_preflight_from_another_origin_gets_no_cors_headers(client):
    response = client.options(
        "/api/v2/tools/", HTTP_ORIGIN="https://other.example", HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET"
    )
    assert "Access-Control-Allow-Origin" not in response


def test_exposed_headers_include_request_id_and_version(client):
    response = client.get("/api/v2/tools/", HTTP_ORIGIN=ALLOWED)
    exposed = response["Access-Control-Expose-Headers"]
    assert "X-Request-Id" in exposed and "X-App-Version" in exposed and "Retry-After" in exposed


def test_cors_is_not_applied_outside_the_api(client):
    response = client.get("/admin/login/", HTTP_ORIGIN=ALLOWED)
    assert "Access-Control-Allow-Origin" not in response
