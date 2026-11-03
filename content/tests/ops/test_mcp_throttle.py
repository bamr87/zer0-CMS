"""/mcp/ stands behind REST's doors (API-02, SEC-03): a request without a valid
token spends the caller's anonymous bucket before it is refused, a token's
requests spend that token's bucket, and over the limit is HTTP 429 with
`Retry-After` and a JSON-RPC error carrying `data.retry_after`."""

import json

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from agents.models import AgentToken
from ops.throttling import AnonThrottle

pytestmark = pytest.mark.django_db


def rpc(raw=None):
    headers = {"HTTP_AUTHORIZATION": f"Bearer {raw}"} if raw else {}
    body = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "tools/list"})
    return Client().post("/mcp/", data=body, content_type="application/json", **headers)


def token(name):
    return AgentToken.issue(get_user_model().objects.get(username="agent:seo"), name=name)[1]


def assert_limited(response):
    assert response.status_code == 429
    wait = int(response["Retry-After"])
    error = response.json()["error"]
    assert error["data"]["retry_after"] == wait >= 1
    assert error["data"]["code"] == "rate.limited"
    assert error["data"]["request_id"] == response["X-Request-Id"]
    assert response.json()["id"] is None  # answered before the body is read, as a refused token is


def test_the_third_request_without_a_token_is_429_not_401(monkeypatch):
    monkeypatch.setitem(AnonThrottle.THROTTLE_RATES, "anon", "2/min")
    assert rpc().status_code == 401
    assert rpc("zer0_" + "x" * 43).status_code == 401  # an unknown token is no one's: the same bucket
    assert_limited(rpc())


def test_a_tokens_third_request_is_429_and_another_token_is_unaffected(monkeypatch):
    monkeypatch.setitem(AnonThrottle.THROTTLE_RATES, "principal", "2/min")
    first, second = token("one"), token("two")
    for _ in range(2):
        assert rpc(first).status_code == 200
    assert_limited(rpc(first))
    assert rpc(second).status_code == 200
