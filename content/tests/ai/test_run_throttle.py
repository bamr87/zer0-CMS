"""Starting a model run is limited per caller on every surface (AI-07): each
REST action that answers 202 with a run, REST's and GraphQL's agent-run
creation, all spend one `ai_run` allowance (`THROTTLE_AI_RUN_RATE`, 30 a
minute by default — `ai.run_assistant`'s rate over MCP); over it is 429
`rate.limited` with `Retry-After`, and another person is unaffected."""

import json

import pytest
from django.test import Client

from agents.registry import registry
from config.settings import base
from ops.throttling import RunThrottle

BASE = "/api/v2/ai"


@pytest.fixture
def two_a_minute(monkeypatch):
    monkeypatch.setitem(RunThrottle.THROTTLE_RATES, "ai_run", "2/min")


def assistant(api, owner):
    made = api(owner).post(f"{BASE}/assistants/", {"name": "Headlines", "visibility": "shared"}, format="json")
    assert made.status_code == 201, made.content
    return f"{BASE}/assistants/{made.json()['id']}/run/"


def test_the_default_matches_the_mcp_tools_rate():
    assert base.REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]["ai_run"] == "30/min"
    assert registry.get("ai.run_assistant").rate == "30/m"


@pytest.mark.django_db
def test_the_third_run_in_a_minute_is_429_and_another_person_is_unaffected(two_a_minute, api, alice, bob, fake):
    run = assistant(api, alice)
    for _ in range(2):
        assert api(alice).post(run, {"prompt": "go"}, format="json").status_code == 202
    refused = api(alice).post(run, {"prompt": "go"}, format="json")
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "rate.limited"
    assert refused.json()["error"]["retry_after"] == int(refused["Retry-After"]) >= 1
    assert api(bob).post(run, {"prompt": "go"}, format="json").status_code == 202
    # listing and reading spend nothing
    assert api(alice).get(f"{BASE}/assistants/").status_code == 200


@pytest.mark.django_db
def test_every_surface_that_starts_a_run_spends_the_same_allowance(two_a_minute, api, alice, fake, article):
    run = assistant(api, alice)
    assert api(alice).post(run, {"prompt": "go"}, format="json").status_code == 202
    started = api(alice).post("/api/v2/agent-runs/", {"agent": "brand", "page_id": article.pk}, format="json")
    assert started.status_code == 201, started.content
    assert api(alice).post("/api/v2/agents/brand/runs", {"page_id": article.pk}, format="json").status_code == 429
    client = Client()
    client.force_login(alice)
    body = json.dumps({"query": 'mutation { requestAgentRun(agent: "brand") { runId } }'})
    answer = client.post("/graphql/", data=body, content_type="application/json").json()
    assert answer["data"]["requestAgentRun"] is None
    error = answer["errors"][0]
    assert error["extensions"]["code"] == "rate.limited" and error["extensions"]["retry_after"] >= 1
