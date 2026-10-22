"""HTML responses carry the security headers; the CSP is report-only for now;
HSTS appears only on a secure request (UPS-OPS-23)."""

import pytest

pytestmark = pytest.mark.django_db


def test_html_responses_carry_the_security_headers(client):
    response = client.get("/admin/login/")
    assert response["Referrer-Policy"] == "strict-origin-when-cross-origin"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "camera=()" in response["Permissions-Policy"]
    assert response["Content-Security-Policy-Report-Only"].startswith("default-src 'self'")
    assert "Content-Security-Policy" not in response


def test_json_responses_carry_no_csp(client):
    response = client.get("/healthz")
    assert "Content-Security-Policy-Report-Only" not in response
    assert response["X-Content-Type-Options"] == "nosniff"


def test_hsts_only_over_https(client, settings):
    settings.SECURE_HSTS_SECONDS = 3600
    assert "Strict-Transport-Security" in client.get("/healthz", secure=True)
    assert "Strict-Transport-Security" not in client.get("/healthz")
