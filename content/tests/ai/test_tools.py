"""The AI content layer's tools in the one registry (`ai.run_assistant`,
`ai.generate_brief`): `propose` effects, reached under the registry's checks by
an agent that lists them, scoped by `visible_to` like every other surface,
queuing runs rather than calling a model in the tool call."""

import copy
import json

import pytest
from django.contrib.auth import get_user_model
from wagtail.models import Site

from agents.models import AgentRun
from agents.registry import ToolContext, ToolError, registry
from ai.models import Assistant, Brief, Visibility

from .test_services import DETAIL


@pytest.fixture
def ctx(agent):
    """An agent (the drafter) whose definition lists the AI tools."""
    definition = copy.copy(agent("drafter"))
    definition.tools = [*definition.tools, "ai.run_assistant", "ai.generate_brief"]
    user = get_user_model().objects.get(username=definition.username)
    return ToolContext(user=user, agent=definition, trigger="mcp")


def test_the_tools_are_registered_as_proposals():
    for name in ("ai.run_assistant", "ai.generate_brief"):
        tool = registry.get(name)
        assert tool.effect == "propose" and tool.input_schema["additionalProperties"] is False
        assert tool.annotations["readOnlyHint"] is False and tool.annotations["destructiveHint"] is False


@pytest.mark.django_db
def test_an_agent_runs_a_shared_assistant_and_gets_the_run_to_follow(ctx, alice, fake, worker):
    shared = Assistant.objects.create(owner=alice, name="Ours", visibility=Visibility.SHARED)
    fake.script.append({"text": "An answer."})
    result = worker(registry.call, "ai.run_assistant", {"assistant": str(shared.public_id), "prompt": "hi"}, ctx)
    run = AgentRun.objects.get(pk=result["run_id"])
    assert result["stream"] == f"/api/v2/agent-runs/{run.pk}/stream/"
    assert run.status == "succeeded" and run.output["text"] == "An answer." and run.trigger == "mcp"
    assert run.started_by.username == "agent:drafter"


@pytest.mark.django_db
def test_the_tools_see_only_what_the_agent_may_see(ctx, alice, article):
    private = Assistant.objects.create(owner=alice, name="Mine")
    with pytest.raises(ToolError) as hidden:
        registry.call("ai.run_assistant", {"assistant": str(private.public_id), "prompt": "hi"}, ctx)
    assert hidden.value.code == "not_found"
    with pytest.raises(ToolError) as malformed:
        registry.call("ai.run_assistant", {"assistant": "not-a-uuid", "prompt": "hi"}, ctx)
    assert malformed.value.code == "invalid_args"
    shared = Assistant.objects.create(owner=alice, name="Ours", visibility=Visibility.SHARED)
    article.agent_policy = "off"
    article.save()
    with pytest.raises(ToolError) as off:
        registry.call(
            "ai.run_assistant", {"assistant": str(shared.public_id), "prompt": "hi", "page_id": article.pk}, ctx
        )
    assert off.value.code == "policy"
    ctx.agent.tools = [t for t in ctx.agent.tools if not t.startswith("ai.")]
    with pytest.raises(ToolError) as unlisted:
        registry.call("ai.run_assistant", {"assistant": str(shared.public_id), "prompt": "hi"}, ctx)
    assert unlisted.value.code == "not_allowed"


@pytest.mark.django_db
def test_an_agent_asks_for_a_brief_that_people_of_the_site_review_and_apply(
    ctx, api, alice, bob, fake, worker, site_root
):
    site = Site.objects.get(root_page=site_root)
    writer = Assistant.objects.create(owner=alice, name="Writer", visibility=Visibility.SHARED)
    fake.script += [{"text": "Cats rule."}, {"text": json.dumps(DETAIL)}]
    args = {"prompt": "cats", "assistant": str(writer.public_id), "parent_page_id": site_root.pk}
    result = worker(registry.call, "ai.generate_brief", args, ctx)
    brief = Brief.objects.get(public_id=result["brief"])
    assert brief.status == Brief.READY and brief.markdown == "Cats rule." and brief.owner.username == "agent:drafter"
    assert (brief.site, brief.visibility, brief.parent_id) == (site, Visibility.SITE, site_root.pk)
    assert Brief.objects.visible_to(alice).filter(pk=brief.pk).exists()  # alice edits the site
    assert not Brief.objects.visible_to(bob).filter(pk=brief.pk).exists()
    url = f"/api/v2/ai/briefs/{brief.public_id}/apply/"
    assert api(bob).post(url, {}, format="json").status_code == 404
    applied = api(alice).post(url, {}, format="json")  # not hers, but an agent's, shown to her site's editors
    assert applied.status_code == 201, applied.content
    assert Brief.objects.get(pk=brief.pk).status == Brief.APPLIED and applied.json()["page_id"]
    unwritable = {"prompt": "cats"}
    with pytest.raises(ToolError) as refused:
        registry.call("ai.generate_brief", unwritable, ctx)
    assert refused.value.code == "invalid_args" and not Brief.objects.filter(prompt="cats", assistant=None).exists()


@pytest.mark.django_db
def test_a_person_sees_the_tools_in_the_registry_listing(api, alice):
    names = [t["name"] for t in api(alice).get("/api/v2/tools/").json()["tools"]]
    assert "ai.run_assistant" in names and "ai.generate_brief" in names


@pytest.mark.django_db
def test_an_mcp_client_whose_agent_lists_the_tool_runs_an_assistant(alice, fake, django_capture_on_commit_callbacks):
    """Over /mcp/: an agent opts in by listing the tool in its definition."""
    from agents.models import AgentDefinition

    from ..mcp.test_mcp import rpc, token_for

    drafter = AgentDefinition.objects.get(slug="drafter")
    drafter.tools = [*drafter.tools, "ai.run_assistant"]
    drafter.save(update_fields=["tools"])
    shared = Assistant.objects.create(owner=alice, name="Ours", visibility=Visibility.SHARED)
    raw = token_for("drafter")
    listed = rpc(raw, "tools/list").json()["result"]["tools"]
    assert "ai.run_assistant" in [t["name"] for t in listed]
    fake.script.append({"text": "Over MCP."})
    arguments = {"assistant": str(shared.public_id), "prompt": "hi"}
    with django_capture_on_commit_callbacks(execute=True):
        reply = rpc(raw, "tools/call", {"name": "ai.run_assistant", "arguments": arguments})
    result = json.loads(reply.json()["result"]["content"][0]["text"])
    run = AgentRun.objects.get(pk=result["run_id"])
    assert run.status == "succeeded" and run.output["text"] == "Over MCP." and run.trigger == "mcp"
    assert run.parent_run.agent.slug == "drafter"  # the audited MCP call is its parent
