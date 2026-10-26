"""JSON-RPC errors over HTTP carry the request id; a crash is an internal
error, never a traceback; over stdio an error is exactly the spec's fields."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from agents.models import AgentToken
from mcp_server import protocol

pytestmark = pytest.mark.django_db


def token():
    return AgentToken.issue(get_user_model().objects.get(username="agent:editor"), name="ops-test")[1]


def rpc(raw, method):
    return Client().post(
        "/mcp/",
        data=json.dumps({"jsonrpc": "2.0", "id": 1, "method": method}),
        content_type="application/json",
        HTTP_AUTHORIZATION=f"Bearer {raw}",
    )


def test_jsonrpc_errors_carry_the_request_id():
    response = rpc(token(), "resources/list")
    body = response.json()["error"]
    assert body["code"] == -32601
    assert body["data"]["request_id"] == response["X-Request-Id"]


def test_a_crashing_handler_is_a_jsonrpc_internal_error(monkeypatch):
    def explode(message, principal):
        raise RuntimeError("boom")

    monkeypatch.setattr("mcp_server.views.handle", explode)
    response = rpc(token(), "ping")
    assert response.status_code == 500
    body = response.json()["error"]
    assert body["code"] == -32603 and body["message"] == "internal error"
    assert body["data"]["request_id"] == response["X-Request-Id"]
    assert "boom" not in response.content.decode()


def test_stdio_errors_carry_no_data():
    assert protocol.error(1, -32601, "nope") == {
        "jsonrpc": "2.0",
        "id": 1,
        "error": {"code": -32601, "message": "nope"},
    }


def test_initialize_reports_the_platform_version(settings):
    body = rpc(token(), "initialize").json()
    assert body["result"]["serverInfo"]["version"] == settings.APP_VERSION
