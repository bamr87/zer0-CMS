"""JSON lines carry the standard fields; tokens and Authorization values never
reach a log, an error report or Sentry; one access line per request, probes
excepted (UPS-OPS-10..12, OPS-13)."""

import json
import logging
import sys

import pytest
from django.test import RequestFactory, override_settings
from django.views.debug import ExceptionReporter

from accounts.auth import UserTokenAuthentication
from accounts.models import UserToken
from agents.tracing import trace
from ops.context import bind
from ops.logging import ContextFilter, JsonFormatter, RedactionFilter, TextFormatter, redact
from ops.sentry import _scrub

PERSON_TOKEN = "zer0u_" + "a1B2c3D4" * 6


def record(msg, *args, level=logging.INFO, exc_info=None, **extra):
    found = logging.LogRecord("tests", level, __file__, 1, msg, args, exc_info)
    for key, value in extra.items():
        setattr(found, key, value)
    return found


def test_json_lines_have_the_standard_fields():
    with bind("rid-1"), trace("4bf92f3577b34da6a3ce929d0e0e4736"):
        found = record("hello %s", "world", duration_ms=1.5)
        ContextFilter().filter(found)
        RedactionFilter().filter(found)
        line = json.loads(JsonFormatter(app="zer0", version="0.1.0").format(found))
    assert line["msg"] == "hello world"
    assert line["level"] == "INFO" and line["logger"] == "tests"
    assert line["request_id"] == "rid-1"
    assert line["trace_id"] == "4bf92f3577b34da6a3ce929d0e0e4736"
    assert line["app"] == "zer0" and line["version"] == "0.1.0"
    assert line["ts"].endswith("Z")
    assert line["duration_ms"] == 1.5


def test_an_unbound_record_says_so():
    found = record("plain")
    ContextFilter().filter(found)
    line = json.loads(JsonFormatter().format(found))
    assert line["request_id"] == "-" and line["trace_id"] == "-"


@pytest.mark.parametrize(
    "secret",
    [
        "sk-ant-api03-abcdefghijklmnopqrstuvwxyz",
        "ghp_abcdefghijklmnopqrstuvwxyz012345",
        "github_pat_11ABCDEF_abcdefghijklmnopqrstuvwxyz",
        "AIzaSyAbcdefghijklmnopqrstuvwxyz0123456",
        "zer0_" + "a1B2c3D4" * 6,
        PERSON_TOKEN,
    ],
)
def test_tokens_are_redacted(secret):
    scrubbed = redact(f"key={secret} done")
    assert secret not in scrubbed
    assert scrubbed == "key=[REDACTED] done"


def test_authorization_values_are_redacted():
    assert redact("Authorization: Bearer abc.def") == "Authorization: [REDACTED]"
    assert redact("authorization=Basic Zm9vOmJhcg==") == "authorization=[REDACTED]"


def test_the_admin_token_prefix_is_not_a_secret():
    shown = "token zer0_abcdefg revoked, and zer0u_abcdefgh listed"
    assert redact(shown) == shown


def test_arguments_are_redacted_before_formatting():
    found = record("token %s for %s, then %s", "ghp_abcdefghijklmnopqrstuvwxyz012345", "seo", PERSON_TOKEN)
    RedactionFilter().filter(found)
    assert found.getMessage() == "token [REDACTED] for seo, then [REDACTED]"


def test_exception_text_is_redacted():
    try:
        raise ValueError(f"leaked sk-ant-api03-abcdefghijklmnopqrstuvwxyz and {PERSON_TOKEN}")
    except ValueError:
        found = record("failed", level=logging.ERROR, exc_info=sys.exc_info())
    for formatted in (JsonFormatter().format(found), TextFormatter("%(message)s").format(found)):
        assert "sk-ant" not in formatted and PERSON_TOKEN not in formatted


@pytest.mark.django_db
@override_settings(DEBUG=True)
def test_an_error_inside_token_authentication_reports_no_token(monkeypatch):
    """A failure while a token is checked (a locked database, say) shows the
    frames' variables on Django's error page — in development too — and sends
    them to Sentry: the token is in two of those frames, and in neither report."""

    def fail(*args, **kwargs):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(UserToken.objects, "select_related", fail)
    request = RequestFactory().get("/api/v2/me", HTTP_AUTHORIZATION=f"Bearer {PERSON_TOKEN}")
    try:
        UserTokenAuthentication().authenticate(request)
    except RuntimeError:
        exc_info = sys.exc_info()
    reporter = ExceptionReporter(request, *exc_info)
    assert "authenticate" in reporter.get_traceback_text()
    assert PERSON_TOKEN not in reporter.get_traceback_html()
    assert PERSON_TOKEN not in reporter.get_traceback_text()
    frame = {"function": "authenticate", "vars": {"raw": PERSON_TOKEN, "header": [f"Bearer {PERSON_TOKEN}"]}}
    event = _scrub({"exception": {"values": [{"value": "locked", "stacktrace": {"frames": [frame]}}]}}, {})
    assert PERSON_TOKEN not in json.dumps(event)
    assert event["exception"]["values"][0]["stacktrace"]["frames"][0]["vars"]["raw"] == "[REDACTED]"


def test_one_access_line_per_request(client, caplog):
    with caplog.at_level(logging.INFO, logger="ops.access"):
        response = client.get("/version")
    lines = [r for r in caplog.records if r.name == "ops.access"]
    assert len(lines) == 1
    line = lines[0]
    assert line.method == "GET" and line.path == "/version" and line.status == 200
    assert line.duration_ms >= 0
    assert line.request_id == response["X-Request-Id"]


@pytest.mark.django_db
def test_djangos_own_4xx_lines_carry_the_request_id(client, caplog):
    # Django logs a 4xx after the middleware stack has unwound, so the
    # contextvar is gone; the record's `request` still knows its id.
    with caplog.at_level(logging.WARNING, logger="django.request"):
        response = client.get("/api/v2/nope/")
    lines = [r for r in caplog.records if r.name == "django.request"]
    assert lines, "Django did not log the 404"
    found = lines[-1]
    ContextFilter().filter(found)
    assert found.request_id == response["X-Request-Id"]
    line = json.loads(JsonFormatter().format(found))
    assert line["request_id"] == response["X-Request-Id"]
    assert "request" not in line and line["status_code"] == 404


def test_health_endpoints_are_not_access_logged(client, caplog):
    with caplog.at_level(logging.INFO, logger="ops.access"):
        client.get("/healthz")
    assert not [r for r in caplog.records if r.name == "ops.access"]


def test_the_console_handler_carries_both_filters():
    kinds = {type(f) for h in logging.getLogger().handlers for f in h.filters}
    assert {ContextFilter, RedactionFilter} <= kinds
