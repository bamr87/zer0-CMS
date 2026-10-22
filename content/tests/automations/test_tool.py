"""The `automations.fire_hook` tool (PLAN G16): a `propose` effect in the one registry, reached under the registry's
checks by an agent that lists it — in a run, or over MCP — firing the automations waiting for the hook with the
payload saying which agent fired it; a run an automation started never fires one, so automations cannot set each
other off in a loop."""

import copy
import json

import pytest
from django.contrib.auth import get_user_model

from agents.models import AgentDefinition
from agents.registry import ToolContext, ToolError, registry
from agents.runner import start_run
from automations.models import AutomationRun
from ideas.models import Idea

FIRE = "automations.fire_hook"


@pytest.fixture
def ctx(agent):
    """The drafter, whose definition (here) lists the tool."""
    definition = copy.copy(agent("drafter"))
    definition.tools = [*definition.tools, FIRE]
    user = get_user_model().objects.get(username=definition.username)
    return ToolContext(user=user, agent=definition, trigger="mcp")


def test_the_tool_is_registered_as_a_proposal():
    tool = registry.get(FIRE)
    assert tool.effect == "propose" and tool.input_schema["additionalProperties"] is False
    assert tool.annotations["readOnlyHint"] is False and tool.annotations["destructiveHint"] is False


@pytest.mark.django_db
def test_an_agent_fires_a_named_hook_and_its_automations_run_as_their_owners(ctx, alice, make, worker):
    automation = make(alice, {"kind": "hook", "hook": "agent.flagged"}, [{"kind": "idea", "title": "{{ data.why }}"}])
    result = worker(registry.call, FIRE, {"hook": "agent.flagged", "data": {"why": "A stale page"}}, ctx)
    assert result == {"hook": "agent.flagged", "fired": 1}
    run = AutomationRun.objects.get(automation=automation)
    assert run.payload == {
        "hook": "agent.flagged",
        "by": "agent:drafter",
        "site": None,
        "data": {"why": "A stale page"},
    }
    assert run.status == AutomationRun.SUCCEEDED and Idea.objects.get().owner == alice
    with pytest.raises(ToolError) as nowhere:
        registry.call(FIRE, {"hook": "agent.flagged", "site_id": 999999}, ctx)
    assert nowhere.value.code == "not_found"
    with pytest.raises(ToolError) as malformed:
        registry.call(FIRE, {"hook": "Not A Hook!"}, ctx)
    assert malformed.value.code == "invalid_args"
    ctx.agent.tools = [t for t in ctx.agent.tools if t != FIRE]
    with pytest.raises(ToolError) as unlisted:
        registry.call(FIRE, {"hook": "agent.flagged"}, ctx)
    assert unlisted.value.code == "not_allowed"


@pytest.mark.django_db
def test_a_run_an_automation_started_does_not_fire_hooks(ctx, alice, make, agent):
    make(alice, {"kind": "hook", "hook": "agent.flagged"})
    started = start_run(agent("drafter"), trigger="event", user=alice, enqueue=False, event_id="automation-run:x")
    with pytest.raises(ToolError) as looped:
        registry.call(FIRE, {"hook": "agent.flagged"}, ToolContext(**{**ctx.__dict__, "run": started}))
    assert looped.value.code == "not_allowed" and not AutomationRun.objects.exists()


@pytest.mark.django_db
def test_an_mcp_client_whose_agent_lists_the_tool_fires_a_hook(alice, make, django_capture_on_commit_callbacks):
    from ..mcp.test_mcp import rpc, token_for

    drafter = AgentDefinition.objects.get(slug="drafter")
    drafter.tools = [*drafter.tools, FIRE]
    drafter.save(update_fields=["tools"])
    automation = make(alice, {"kind": "hook", "hook": "agent.flagged"}, [{"kind": "idea", "title": "Over MCP"}])
    raw = token_for("drafter")
    assert FIRE in [t["name"] for t in rpc(raw, "tools/list").json()["result"]["tools"]]
    with django_capture_on_commit_callbacks(execute=True):
        reply = rpc(raw, "tools/call", {"name": FIRE, "arguments": {"hook": "agent.flagged", "data": {}}})
    assert json.loads(reply.json()["result"]["content"][0]["text"]) == {"hook": "agent.flagged", "fired": 1}
    assert AutomationRun.objects.get(automation=automation).status == AutomationRun.SUCCEEDED
    assert Idea.objects.get().title == "Over MCP"
