"""The `automations.fire_hook` tool (PLAN G16): a `write` effect in the one registry — what it sets off runs as other
people and may email, call webhooks and move stories — so only an agent at policy `draft`, live and past its evals,
that lists it may call it, in a run or over MCP. An agent fires only its own hooks (`agent.<slug>.<name>`): it can
never pose as the platform's monitor or another agent. The payload says which agent fired it; a run an automation
started never fires one, so automations cannot set each other off in a loop."""

import copy
import json
import re

import pytest
from django.contrib.auth import get_user_model

from agents.models import AgentDefinition
from agents.registry import ToolContext, ToolError, registry
from agents.runner import start_run
from automations import spec
from automations.models import AutomationRun
from ideas.models import Idea

FIRE = "automations.fire_hook"
FLAGGED = {"kind": "hook", "hook": "agent.drafter.flagged"}


@pytest.fixture
def ctx(agent):
    """The drafter, whose definition (here) lists the tool, promoted to `draft`."""
    definition = copy.copy(agent("drafter"))
    definition.tools = [*definition.tools, FIRE]
    definition.policy = "draft"
    user = get_user_model().objects.get(username=definition.username)
    return ToolContext(user=user, agent=definition, trigger="mcp")


def test_the_tool_is_registered_as_a_write():
    tool = registry.get(FIRE)
    assert tool.effect == "write" and tool.input_schema["additionalProperties"] is False
    assert tool.annotations["readOnlyHint"] is False and tool.annotations["destructiveHint"] is True


def test_every_hook_an_agent_can_fire_is_one_a_trigger_can_name():
    longest = "agent." + "a" * AgentDefinition._meta.get_field("slug").max_length + "." + "b" * 64
    assert re.fullmatch(registry.get(FIRE).input_schema["properties"]["hook"]["pattern"], "b" * 64)
    assert re.fullmatch(spec.HOOK["pattern"], longest)


@pytest.mark.django_db
def test_an_agent_fires_its_own_named_hook_and_its_automations_run_as_their_owners(ctx, alice, make, worker):
    automation = make(alice, FLAGGED, [{"kind": "idea", "title": "{{ data.why }}"}])
    result = worker(registry.call, FIRE, {"hook": "flagged", "data": {"why": "A stale page"}}, ctx)
    assert result == {"hook": "agent.drafter.flagged", "fired": 1}
    run = AutomationRun.objects.get(automation=automation)
    assert run.payload == {
        "hook": "agent.drafter.flagged",
        "by": "agent:drafter",
        "site": None,
        "data": {"why": "A stale page"},
    }
    assert run.status == AutomationRun.SUCCEEDED and Idea.objects.get().owner == alice
    with pytest.raises(ToolError) as nowhere:
        registry.call(FIRE, {"hook": "flagged", "site_id": 999999}, ctx)
    assert nowhere.value.code == "not_found"
    with pytest.raises(ToolError) as malformed:
        registry.call(FIRE, {"hook": "Not A Hook!"}, ctx)
    assert malformed.value.code == "invalid_args"
    ctx.agent.tools = [t for t in ctx.agent.tools if t != FIRE]
    with pytest.raises(ToolError) as unlisted:
        registry.call(FIRE, {"hook": "flagged"}, ctx)
    assert unlisted.value.code == "not_allowed"


@pytest.mark.django_db
def test_an_agent_never_poses_as_the_platform_or_another_agent_and_needs_the_draft_policy(ctx, alice, make, worker):
    monitor = make(alice, {"kind": "hook", "hook": "monitor.finding"})
    seo = make(alice, {"kind": "hook", "hook": "agent.seo.flagged"})
    for name in ("monitor.finding", "agent.seo.flagged"):
        assert worker(registry.call, FIRE, {"hook": name}, ctx) == {"hook": f"agent.drafter.{name}", "fired": 0}
    assert not AutomationRun.objects.filter(automation__in=[monitor, seo]).exists()
    ctx.agent.policy = "suggest"  # where every agent starts: it proposes, and setting other people's work off is more
    with pytest.raises(ToolError) as refused:
        registry.call(FIRE, {"hook": "flagged"}, ctx)
    assert refused.value.code == "policy" and "needs policy draft" in refused.value.message


@pytest.mark.django_db
def test_a_run_an_automation_started_does_not_fire_hooks(ctx, alice, make, agent):
    make(alice, FLAGGED)
    started = start_run(agent("drafter"), trigger="event", user=alice, enqueue=False, event_id="automation-run:x")
    with pytest.raises(ToolError) as looped:
        registry.call(FIRE, {"hook": "flagged"}, ToolContext(**{**ctx.__dict__, "run": started}))
    assert looped.value.code == "not_allowed" and not AutomationRun.objects.exists()


@pytest.mark.django_db
def test_an_mcp_client_whose_agent_lists_the_tool_fires_its_hook(alice, make, django_capture_on_commit_callbacks):
    from ..mcp.test_mcp import rpc, token_for

    drafter = AgentDefinition.objects.get(slug="drafter")
    drafter.tools, drafter.policy = [*drafter.tools, FIRE], "draft"
    drafter.save(update_fields=["tools", "policy"])
    automation = make(alice, FLAGGED, [{"kind": "idea", "title": "Over MCP"}])
    raw = token_for("drafter")
    assert FIRE in [t["name"] for t in rpc(raw, "tools/list").json()["result"]["tools"]]
    with django_capture_on_commit_callbacks(execute=True):
        reply = rpc(raw, "tools/call", {"name": FIRE, "arguments": {"hook": "flagged", "data": {}}})
    assert json.loads(reply.json()["result"]["content"][0]["text"]) == {"hook": "agent.drafter.flagged", "fired": 1}
    assert AutomationRun.objects.get(automation=automation).status == AutomationRun.SUCCEEDED
    assert Idea.objects.get().title == "Over MCP"
