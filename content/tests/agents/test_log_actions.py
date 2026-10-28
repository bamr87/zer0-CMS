"""Wagtail's log for the platform's own events (P4, G2's backend items): a
suggestion proposed, accepted and rejected, a run started and finished, a
token issued and revoked — each a log entry saying who did it, and a token's
never holding the token."""

import json

import pytest
from django.contrib.auth import get_user_model
from wagtail.log_actions import registry
from wagtail.models import ModelLogEntry

from accounts import services as tokens
from agents.models import AgentRun, AgentToken
from agents.runner import execute, start_run
from suggestions.models import Suggestion
from suggestions.services import accept, propose, reject


def entries(model):
    rows = ModelLogEntry.objects.filter(
        content_type__app_label=model._meta.app_label, content_type__model=model._meta.model_name
    )
    return list(rows.order_by("id"))


@pytest.mark.django_db
def test_a_suggestions_life_is_logged_by_who_did_it(article, agent, editor):
    seo = get_user_model().objects.get(username="agent:seo")
    run = AgentRun.objects.create(agent=agent("seo"), trigger="manual")

    def suggest(value):
        return propose(
            target=article, op="meta", field="seo_title", user=seo, run=run, payload={"value": value}, rationale="r"
        )

    taken, dropped = suggest("Nightly backups, explained"), suggest("Backups at night")
    accept([taken], editor)
    reject(dropped, editor, reason="too vague")
    logged = [(e.action, e.user.username, e.object_id) for e in entries(Suggestion)]
    assert logged == [
        ("zer0.suggestion.propose", "agent:seo", str(taken.pk)),
        ("zer0.suggestion.propose", "agent:seo", str(dropped.pk)),
        ("zer0.suggestion.accept", "editor", str(taken.pk)),
        ("zer0.suggestion.reject", "editor", str(dropped.pk)),
    ]
    accepted, rejected = entries(Suggestion)[2:]
    assert accepted.data["target"] == f"articlepage:{article.pk}" and accepted.data["revision_id"]
    assert rejected.data["reason"] == "too vague" and rejected.data["field"] == "seo_title"
    assert registry.get_action_label("zer0.suggestion.accept") == "Accept a suggestion"


@pytest.mark.django_db
def test_a_run_is_logged_when_it_starts_and_when_it_finishes(article, agent, editor):
    run = start_run(agent("brand"), trigger="manual", target=article, user=editor, enqueue=False)
    execute(run)
    started, finished = entries(AgentRun)
    assert (started.action, started.user.username, started.data["agent"]) == ("zer0.run.start", "editor", "brand")
    assert (finished.action, finished.user, finished.data["status"]) == ("zer0.run.finish", None, "succeeded")


@pytest.mark.django_db
def test_issuing_and_revoking_a_token_is_logged_without_the_token(editor):
    token, raw = tokens.issue(editor, name="laptop")
    tokens.revoke(editor, token.prefix, by=editor)
    agent_token, agent_raw = AgentToken.issue(get_user_model().objects.get(username="agent:seo"), name="mcp")
    logged = ModelLogEntry.objects.filter(action__startswith="zer0.token.").order_by("id")
    assert [(e.action, e.data["holder"], e.data["name"]) for e in logged] == [
        ("zer0.token.issue", "editor", "laptop"),
        ("zer0.token.revoke", "editor", "laptop"),
        ("zer0.token.issue", "agent:seo", "mcp"),
    ]
    assert logged[1].user == editor
    every = json.dumps([[e.label, e.data] for e in logged])
    assert raw not in every and agent_raw not in every and token.prefix in every
