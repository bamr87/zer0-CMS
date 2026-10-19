"""The tool registry and the principals behind it (M9): every check holds on
every call, a run of a tool is recorded, and there is no superuser path."""

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group, Permission
from wagtail.models import GroupPagePermission

from agents.models import AgentRun, AgentStep, AgentToken
from agents.principals import STANDARD_AGENTS, ensure_principal, is_agent_user
from agents.registry import Registry, Tool, ToolContext, ToolError, obj, registry
from agents.runner import RunRefused, execute, start_run

from ..conftest import make_article


def ctx_for(definition, run=None, **overrides):
    user = get_user_model().objects.get(username=definition.username)
    return ToolContext(
        user=overrides.pop("user", user), agent=overrides.pop("agent_obj", definition), run=run, **overrides
    )


@pytest.mark.django_db
def test_the_standard_agents_exist_as_plain_users_in_their_groups():
    for slug in STANDARD_AGENTS:
        user = get_user_model().objects.get(username=f"agent:{slug}")
        assert is_agent_user(user)
        assert not user.is_staff and not user.has_usable_password()
        assert set(user.groups.values_list("name", flat=True)) == {"Agents", f"agent:{slug}"}
    review = Group.objects.get(name="agent:review")
    assert not GroupPagePermission.objects.filter(group=review).exists()


@pytest.mark.django_db
def test_ensure_principal_never_widens_an_editors_narrowing(root_page):
    group = Group.objects.get(name="agent:seo")
    GroupPagePermission.objects.filter(group=group).delete()
    ensure_principal("seo")
    assert not GroupPagePermission.objects.filter(group=group).exists()


@pytest.mark.django_db
def test_a_fake_tool_run_records_a_run_and_its_steps(agent, article):
    local = Registry()
    local.register(
        Tool(
            name="test.echo",
            fn=lambda ctx, text: {"echo": text},
            description="echo",
            input_schema=obj({"text": {"type": "string"}}, required=["text"]),
            effect="read",
        )
    )
    seo = agent("seo")
    seo.tools = [*seo.tools, "test.echo"]
    run = AgentRun.objects.create(agent=seo, trigger="manual")
    assert local.call("test.echo", {"text": "hi"}, ctx_for(seo, run=run)) == {"echo": "hi"}
    step = AgentStep.objects.get(run=run)
    assert (step.kind, step.name, step.args, step.result, step.error) == (
        "tool",
        "test.echo",
        {"text": "hi"},
        {"echo": "hi"},
        "",
    )
    with pytest.raises(ToolError) as refused:
        local.call("test.echo", {"text": 3}, ctx_for(seo, run=run))
    assert refused.value.code == "invalid_args"
    assert AgentStep.objects.filter(run=run).count() == 2  # a refusal is in the audit trail too


@pytest.mark.django_db
def test_publish_is_refused_unless_the_policy_allows_it(agent, article):
    drafter = agent("drafter")
    drafter.tools = [*drafter.tools, "content.publish"]
    with pytest.raises(ToolError) as e:
        registry.call("content.publish", {"page_id": article.pk}, ctx_for(drafter))
    assert e.value.code == "policy" and "needs policy auto" in e.value.message
    drafter.policy = "auto"
    article.agent_policy = "draft"
    article.save_revision().publish()
    with pytest.raises(ToolError) as e:
        registry.call("content.publish", {"page_id": article.pk}, ctx_for(drafter))
    assert e.value.code == "policy" and f"on page {article.pk}" in e.value.message


@pytest.mark.django_db
def test_write_needs_draft_and_the_page_must_allow_it(agent, article):
    drafter = agent("drafter")
    ops = [{"op": "insert", "block": {"type": "markdown", "value": "More."}}]
    with pytest.raises(ToolError) as e:
        registry.call("content.draft_revision", {"page_id": article.pk, "ops": ops, "rationale": "r"}, ctx_for(drafter))
    assert e.value.code == "policy"
    drafter.policy = "draft"
    article.agent_policy = "draft"
    article.save_revision().publish()
    out = registry.call(
        "content.draft_revision", {"page_id": article.pk, "ops": ops, "rationale": "r"}, ctx_for(drafter)
    )
    assert out["revision_id"] and len(out["blocks_written"]) == 1
    from wagtail.models import Revision

    assert Revision.objects.get(pk=out["revision_id"]).user.username == "agent:drafter"


@pytest.mark.django_db
def test_there_is_no_superuser_path(agent, article):
    admin = get_user_model().objects.create_superuser("root", password="pw")
    with pytest.raises(ToolError) as e:
        registry.call("content.get_page", {"page_id": article.pk}, ctx_for(agent("seo"), user=admin))
    assert e.value.code == "permission_denied"
    with pytest.raises(ValueError):
        AgentToken.issue(admin, name="nope")


@pytest.mark.django_db
def test_page_permissions_are_checked_as_the_agent_user(agent, site_root, root_page):
    page = make_article(site_root, "Elsewhere")
    group = Group.objects.get(name="agent:seo")
    GroupPagePermission.objects.filter(group=group).delete()
    rationale = {"op": "meta", "field": "seo_title", "value": "x", "rationale": "r"}
    with pytest.raises(ToolError) as e:
        registry.call("content.propose_edit", {"page_id": page.pk, **rationale}, ctx_for(agent("seo")))
    assert e.value.code == "permission_denied"
    GroupPagePermission.objects.create(
        group=group,
        page=site_root,
        permission=Permission.objects.get(content_type__app_label="wagtailcore", codename="change_page"),
    )
    assert (
        registry.call("content.propose_edit", {"page_id": page.pk, **rationale}, ctx_for(agent("seo")))["status"]
        == "pending"
    )


@pytest.mark.django_db
def test_a_tool_outside_the_agents_list_is_not_allowed_and_review_never_publishes(agent, article):
    with pytest.raises(ToolError) as e:
        registry.call(
            "content.draft_revision", {"page_id": article.pk, "ops": [], "rationale": "r"}, ctx_for(agent("seo"))
        )
    assert e.value.code == "not_allowed"
    review = agent("review")
    review.tools = [*review.tools, "content.publish"]
    assert "content.publish" not in [t.name for t in registry.for_context(ctx_for(review))]


@pytest.mark.django_db
def test_rates_are_per_agent_and_tool(agent, article, settings):
    local = Registry()
    local.register(
        Tool(name="test.limited", fn=lambda ctx: {}, description="", input_schema=obj({}), effect="read", rate="2/m")
    )
    seo = agent("seo")
    seo.tools = ["test.limited"]
    ctx = ctx_for(seo)
    local.call("test.limited", {}, ctx)
    local.call("test.limited", {}, ctx)
    with pytest.raises(ToolError) as e:
        local.call("test.limited", {}, ctx)
    assert e.value.code == "rate_limited"


@pytest.mark.django_db
def test_tokens_store_only_a_hash_and_resolve_to_their_agent():
    user = get_user_model().objects.get(username="agent:seo")
    token, raw = AgentToken.issue(user, name="rails")
    assert raw.startswith("zer0_") and raw not in token.key_hash
    assert AgentToken.authenticate(raw).user == user
    token.revoked_at = token.created_at
    token.save()
    assert AgentToken.authenticate(raw) is None


@pytest.mark.django_db
def test_a_definition_that_never_went_live_cannot_run(agent):
    from agents.models import AgentDefinition

    draft = AgentDefinition(slug="draft-only", name="Draft", live=False, tools=[])
    draft.save()
    draft.save_revision()
    with pytest.raises(RunRefused):
        start_run(draft, trigger="manual")


@pytest.mark.django_db
def test_a_run_without_its_agent_user_is_refused(agent, article):
    run = start_run(agent("brand"), trigger="manual", target=article, enqueue=False)
    get_user_model().objects.filter(username="agent:brand").update(is_active=False)
    assert execute(run).status == AgentRun.REFUSED
