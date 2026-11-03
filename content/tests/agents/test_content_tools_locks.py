"""An agent's write tools keep the rules a person's save and publish keep
(CONTENT-03): `content.draft_revision` and `content.publish` go through
`cms.services` — a Wagtail lock refuses them, a draft names the revision it
was written from, publishing clears a future go-live time as Write's Publish
does, and a draft is held to its site's banned phrases."""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group, Permission
from django.utils import timezone
from wagtail.models import GroupPagePermission

from agents.models import AgentDefinition
from agents.registry import ToolError, registry
from sites.models import SiteSettings

from ..mcp.test_mcp import rpc, token_for
from .test_registry import ctx_for

INSERT = [{"op": "insert", "block": {"type": "markdown", "value": "One more line."}}]


@pytest.fixture
def drafter(agent, article, root_page):
    """The drafter at policy auto with `content.publish`, allowed to publish, on
    a page that allows it too — so only the rules under test can refuse it."""
    AgentDefinition.objects.filter(slug="drafter").update(
        policy="auto", tools=[*agent("drafter").tools, "content.publish"]
    )
    GroupPagePermission.objects.get_or_create(
        group=Group.objects.get(name="agent:drafter"),
        page=root_page,
        permission=Permission.objects.get(content_type__app_label="wagtailcore", codename="publish_page"),
    )
    article.agent_policy = "auto"
    article.save_revision().publish()
    return agent("drafter")


def call(name, args):
    return rpc(token_for("drafter"), "tools/call", {"name": name, "arguments": args}).json()["result"]


@pytest.mark.django_db
def test_a_page_a_person_locked_refuses_both_tools(drafter, article, editor):
    article.locked, article.locked_by, article.locked_at = True, editor, timezone.now()
    article.save(update_fields=["locked", "locked_by", "locked_at"])
    revisions = article.revisions.count()
    for name, args in (
        ("content.draft_revision", {"page_id": article.pk, "ops": INSERT, "rationale": "r"}),
        ("content.publish", {"page_id": article.pk}),
    ):
        answer = call(name, args)
        assert answer["isError"] is True, name
        assert answer["structuredContent"]["error"] == "locked", answer
    assert article.revisions.count() == revisions


@pytest.mark.django_db
def test_publishing_a_page_due_to_go_live_later_publishes_it_now(drafter, article):
    draft = article.get_latest_revision_as_object()
    draft.go_live_at = timezone.now() + timedelta(days=3)
    draft.save_revision()
    out = registry.call("content.publish", {"page_id": article.pk}, ctx_for(drafter))
    article.refresh_from_db()
    assert article.live and article.live_revision_id == out["revision_id"]
    assert article.go_live_at is None and article.scheduled_revision is None


@pytest.mark.django_db
def test_a_draft_with_a_phrase_its_site_bans_is_refused(drafter, article):
    own = SiteSettings.for_site(article.get_site())
    own.banned_patterns = [{"name": "nightly", "pattern": r"\bnightly\b"}]
    own.save()
    ops = [{"op": "insert", "block": {"type": "markdown", "value": "The nightly copy runs at two."}}]
    with pytest.raises(ToolError) as refused:
        registry.call("content.draft_revision", {"page_id": article.pk, "ops": ops, "rationale": "r"}, ctx_for(drafter))
    assert refused.value.code == "invalid_args" and "nightly" in refused.value.message


@pytest.mark.django_db
def test_a_draft_from_an_older_revision_is_a_conflict(drafter, article):
    base = article.latest_revision_id
    article.get_latest_revision_as_object().save_revision()  # a person saved since
    args = {"page_id": article.pk, "ops": INSERT, "rationale": "r", "base_revision_id": base}
    with pytest.raises(ToolError) as refused:
        registry.call("content.draft_revision", args, ctx_for(drafter))
    assert refused.value.code == "conflict"
    article.refresh_from_db()
    out = registry.call(
        "content.draft_revision", {**args, "base_revision_id": article.latest_revision_id}, ctx_for(drafter)
    )
    assert out["revision_id"] and len(out["blocks_written"]) == 1
