"""Agent definitions stay GitOps (ADR 0004 decision 8): the admin shows a
definition and never edits or publishes one; the commands that publish one
leave a `wagtail.publish` entry in the log; and an agent's token can be listed
and revoked from the command line, the revoke logged (ADMIN-06, ADMIN-05,
ADMIN-01)."""

import io

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.urls import reverse
from wagtail.models import ModelLogEntry

from agents.models import AgentDefinition, AgentToken

from ..mcp.test_mcp import rpc


@pytest.fixture
def admin_client(client, db):
    root = get_user_model().objects.create_superuser("root", password="pw")
    client.force_login(root)
    return client


def url(view, definition):
    return reverse(f"wagtailsnippets_agents_agentdefinition:{view}", args=[definition.pk])


@pytest.mark.django_db
def test_the_admin_shows_a_definition_and_never_edits_or_publishes_one(admin_client):
    definition = AgentDefinition.objects.get(slug="seo")
    assert admin_client.get(url("inspect", definition)).status_code == 200
    assert admin_client.get(reverse("wagtailsnippets_agents_agentdefinition:list")).status_code == 200
    for view in ("edit", "delete"):
        assert admin_client.get(url(view, definition)).status_code in (302, 403), view
    changed = admin_client.post(url("edit", definition), {"name": "Renamed", "policy": "auto", "action-publish": "1"})
    assert changed.status_code in (302, 403)
    assert admin_client.get(reverse("wagtailsnippets_agents_agentdefinition:add")).status_code in (302, 403)
    definition.refresh_from_db()
    assert definition.name != "Renamed" and definition.policy == "suggest"


def published(definition) -> list[ModelLogEntry]:
    return list(
        ModelLogEntry.objects.filter(
            action="wagtail.publish",
            content_type__app_label="agents",
            content_type__model="agentdefinition",
            object_id=str(definition.pk),
        ).order_by("id")
    )


@pytest.mark.django_db
@pytest.mark.parametrize("command", [["sync_agents", "--publish"], ["run_evals", "--agent", "brand", "--publish"]])
def test_publishing_a_definition_from_the_command_line_is_logged(command):
    definition = AgentDefinition.objects.get(slug="brand")
    definition.save_revision()  # a revision newer than the live one, as a changed YAML file makes
    before = len(published(definition))
    call_command(*command, stdout=io.StringIO())
    definition.refresh_from_db()
    assert definition.live_revision_id == definition.latest_revision_id
    entries = published(definition)
    assert len(entries) == before + 1
    assert entries[-1].revision_id == definition.live_revision_id and entries[-1].user is None


@pytest.mark.django_db
def test_an_agents_token_is_listed_and_revoked_and_the_revoke_is_logged():
    out = io.StringIO()
    call_command("agent_token", "seo", "--name", "laptop", stdout=out, stderr=io.StringIO())
    raw = out.getvalue().strip()
    token = AgentToken.authenticate(raw)
    assert token is not None and rpc(raw, "tools/list").status_code == 200

    listed = io.StringIO()
    call_command("agent_token", "seo", "--list", stdout=listed)
    assert token.prefix in listed.getvalue() and "laptop" in listed.getvalue()
    assert raw not in listed.getvalue()

    call_command("agent_token", "seo", "--revoke", token.prefix, stderr=io.StringIO())
    assert AgentToken.authenticate(raw) is None
    assert rpc(raw, "tools/list").status_code == 401
    revoked = ModelLogEntry.objects.filter(action="zer0.token.revoke").order_by("id").last()
    assert revoked.data == {"holder": "agent:seo", "name": "laptop", "prefix": token.prefix}

    listed = io.StringIO()
    call_command("agent_token", "seo", "--list", stdout=listed)
    assert "revoked" in listed.getvalue()
    with pytest.raises(CommandError, match="0 active tokens"):
        call_command("agent_token", "seo", "--revoke", token.prefix)
    with pytest.raises(CommandError, match="--name"):
        call_command("agent_token", "seo")
