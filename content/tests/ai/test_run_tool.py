"""An MCP client reads the runs it starts (W1-16): `ai.run_assistant` queues a run of the `assistant` agent, which the
calling agent's token could never read back. An agent now sees the runs it started (`AgentRun.objects.visible_to`),
and `runs.get` reads one over the protocol it already speaks; another agent's token still finds nothing."""

import json

import pytest
from django.test import Client

from agents.models import AgentDefinition, AgentRun
from agents.registry import registry
from ai.models import Assistant, Visibility

from ..mcp.test_mcp import rpc, token_for


def listing(slug: str, *tools: str) -> None:
    definition = AgentDefinition.objects.get(slug=slug)
    definition.tools = [*definition.tools, *tools]
    definition.save(update_fields=["tools"])


def call(raw: str, name: str, arguments: dict) -> tuple[bool, dict]:
    """(isError, the tool's answer) of one tools/call."""
    reply = rpc(raw, "tools/call", {"name": name, "arguments": arguments}).json()["result"]
    return reply["isError"], json.loads(reply["content"][0]["text"])


def test_runs_get_is_a_read_tool_with_a_closed_schema():
    tool = registry.get("runs.get")
    assert tool.effect == "read" and tool.input_schema["additionalProperties"] is False
    assert tool.input_schema["required"] == ["run_id"]


@pytest.mark.django_db
def test_an_mcp_client_reads_the_assistant_run_it_started(alice, fake, django_capture_on_commit_callbacks):
    listing("drafter", "ai.run_assistant", "runs.get")
    shared = Assistant.objects.create(owner=alice, name="Ours", visibility=Visibility.SHARED)
    raw = token_for("drafter")
    fake.script.append({"text": "Over MCP."})
    with django_capture_on_commit_callbacks(execute=True):
        _, started = call(raw, "ai.run_assistant", {"assistant": str(shared.public_id), "prompt": "hi"})
    assert AgentRun.objects.get(public_id=started["run_id"]).agent.slug == "assistant"  # not the drafter's own

    failed, read = call(raw, "runs.get", {"run_id": started["run_id"]})
    assert failed is False
    assert (read["id"], read["agent"], read["status"]) == (started["run_id"], "assistant", "succeeded")
    assert read["output"]["text"] == "Over MCP." and "steps" not in read
    _, with_steps = call(raw, "runs.get", {"run_id": started["run_id"], "steps": True})
    assert [s["kind"] for s in with_steps["steps"]] == ["llm"]

    # The stream link it was given answers too: REST reads the same scope.
    rest = Client().get(f"/api/v2/agent-runs/{started['run_id']}/", HTTP_AUTHORIZATION=f"Bearer {raw}")
    assert rest.status_code == 200, rest.content
    assert rest.json()["output"]["text"] == "Over MCP."


@pytest.mark.django_db
def test_another_agents_token_finds_nothing(alice, fake, django_capture_on_commit_callbacks):
    listing("drafter", "ai.run_assistant")
    listing("seo", "runs.get")
    shared = Assistant.objects.create(owner=alice, name="Ours", visibility=Visibility.SHARED)
    fake.script.append({"text": "Not yours."})
    with django_capture_on_commit_callbacks(execute=True):
        _, started = call(
            token_for("drafter"), "ai.run_assistant", {"assistant": str(shared.public_id), "prompt": "hi"}
        )

    other = token_for("seo")
    failed, refused = call(other, "runs.get", {"run_id": started["run_id"]})
    assert failed is True and refused["error"] == "not_found"
    assert "Not yours" not in json.dumps(refused)
    rest = Client().get(f"/api/v2/agent-runs/{started['run_id']}/", HTTP_AUTHORIZATION=f"Bearer {other}")
    assert rest.status_code == 404
    failed, malformed = call(other, "runs.get", {"run_id": "not-a-uuid"})
    assert failed is True and malformed["error"] == "invalid_args"


@pytest.mark.django_db
def test_an_agent_sees_its_own_runs_and_the_runs_it_started(agent, article):
    from django.contrib.auth import get_user_model

    from agents.runner import start_run

    drafter = get_user_model().objects.get(username="agent:drafter")
    own = start_run(agent("drafter"), trigger="mcp", target=article, enqueue=False)
    started = start_run(agent("seo"), trigger="mcp", target=article, user=drafter, enqueue=False)
    unrelated = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    visible = set(AgentRun.objects.visible_to(drafter).values_list("pk", flat=True))
    assert {own.pk, started.pk} <= visible and unrelated.pk not in visible
