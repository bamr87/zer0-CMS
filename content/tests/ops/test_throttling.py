"""Over the limit is 429 with Retry-After and the envelope; buckets are per
agent token and per person; probes are never throttled (UPS-BE-05)."""

from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser

from agents.models import AgentToken
from ops.throttling import PrincipalThrottle

pytestmark = pytest.mark.django_db


def test_the_third_call_is_429_with_retry_after_and_the_envelope(client, api_urls):
    assert client.get("/api/v2/_test-throttled/").status_code == 200
    assert client.get("/api/v2/_test-throttled/").status_code == 200
    response = client.get("/api/v2/_test-throttled/")
    assert response.status_code == 429
    wait = int(response["Retry-After"])
    assert wait >= 1
    body = response.json()["error"]
    assert body["code"] == "rate.limited"
    assert body["retry_after"] == wait
    assert body["request_id"] == response["X-Request-Id"]


def test_agent_tokens_are_bucketed_per_token():
    user = get_user_model().objects.get(username="agent:seo")
    one, _ = AgentToken.issue(user, name="one")
    two, _ = AgentToken.issue(user, name="two")
    throttle = PrincipalThrottle()
    keys = {throttle.get_cache_key(SimpleNamespace(auth=token, user=user), None) for token in (one, two)}
    assert len(keys) == 2
    assert all(key.startswith("throttle_principal_token_") for key in keys)


def test_people_are_bucketed_per_user(editor):
    key = PrincipalThrottle().get_cache_key(SimpleNamespace(auth=None, user=editor), None)
    assert key == f"throttle_principal_user_{editor.pk}"


def test_anonymous_callers_have_no_principal_bucket():
    assert PrincipalThrottle().get_cache_key(SimpleNamespace(auth=None, user=AnonymousUser()), None) is None


def test_health_endpoints_are_never_throttled(client):
    for _ in range(5):
        assert client.get("/healthz").status_code == 200
