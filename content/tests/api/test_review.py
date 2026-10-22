"""The review inbox (api/review.py) and the decisions it leads to: pending
suggestions across pages with their diffs, accept one, reject with a reason,
accept everything a run proposed — and the run's live event stream as a
browser's EventSource asks for it."""

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from wagtail.models import Revision

from agents.models import AgentRun
from suggestions.models import Suggestion
from suggestions.services import propose
from tests.conftest import make_article

INBOX = "/api/v2/review/suggestions/"


def signed_in(user):
    client = Client()
    client.force_login(user)
    return client


@pytest.fixture
def run(agent, article):
    return AgentRun.objects.create(agent=agent("seo"), trigger="manual", target=article)


def suggest(target, run, **kwargs):
    agent_user = get_user_model().objects.get(username=f"agent:{run.agent.slug}")
    return propose(target=target, user=agent_user, run=run, rationale="clearer", **kwargs)


@pytest.mark.django_db
def test_the_inbox_lists_pending_suggestions_with_before_and_after(article, run, editor):
    title = suggest(article, run, op="meta", field="seo_title", payload={"value": "Backups, explained"})
    replace = suggest(
        article, run, op="replace", block_id=article.body[1].id, payload={"type": "markdown", "value": "Twice."}
    )
    insert = suggest(article, run, op="insert", payload={"type": "heading", "value": {"level": "3", "text": "Why"}})
    rows = {r["id"]: r for r in signed_in(editor).get(INBOX).json()["results"]}
    assert set(rows) == {title.pk, replace.pk, insert.pk}
    assert rows[title.pk]["change"] == {
        "kind": "field",
        "label": "seo_title",
        "before": "",
        "after": "Backups, explained",
        "stale": False,
    }
    assert rows[replace.pk]["change"]["before"] == "We copy the site to a second disk every night."
    assert rows[replace.pk]["change"]["after"] == "Twice." and rows[replace.pk]["change"]["label"] == "replace markdown"
    assert rows[insert.pk]["change"]["after"] == "### Why" and rows[insert.pk]["change"]["before"] == ""
    assert rows[title.pk]["target"] == {"type": "page", "id": article.pk, "title": "Nightly backups"}
    assert rows[title.pk]["agent"] == "seo" and rows[title.pk]["run_id"] == run.pk


@pytest.mark.django_db
def test_the_inbox_filters_and_shows_people_only_what_they_may_decide(site_root, article, run, editor, agent):
    other_page = make_article(site_root, "Another page")
    other_run = AgentRun.objects.create(agent=agent("seo"), trigger="manual")
    mine = suggest(article, run, op="meta", field="seo_title", payload={"value": "One"})
    theirs = suggest(other_page, other_run, op="meta", field="seo_title", payload={"value": "Two"})
    client = signed_in(editor)
    assert [r["id"] for r in client.get(INBOX, {"run": run.pk}).json()["results"]] == [mine.pk]
    assert [r["id"] for r in client.get(INBOX, {"target": other_page.pk}).json()["results"]] == [theirs.pk]
    assert client.get(INBOX, {"site": 999999}).json()["count"] == 0
    stranger = get_user_model().objects.create_user("stranger", password="pw")
    assert signed_in(stranger).get(INBOX).json()["count"] == 0


@pytest.mark.django_db
def test_a_suggestion_whose_block_is_gone_is_marked_stale(article, run, editor):
    gone = suggest(article, run, op="delete", block_id=article.body[0].id)
    page = article.get_latest_revision_as_object()
    page.body = [b for b in page.body.get_prep_value() if b["id"] != article.body[0].id]
    page.save_revision(user=editor)
    row = signed_in(editor).get(INBOX).json()["results"][0]
    assert row["id"] == gone.pk and row["change"]["stale"] is True


@pytest.mark.django_db
def test_accept_one_and_reject_one_with_a_reason(article, run, editor):
    a = suggest(article, run, op="meta", field="seo_title", payload={"value": "Accepted title"})
    b = suggest(article, run, op="meta", field="search_description", payload={"value": "Off-brand"})
    client = signed_in(editor)
    accepted = client.post(f"/api/v2/suggestions/{a.pk}/accept/", {}, content_type="application/json").json()
    assert accepted["accepted"] is True and accepted["revision_id"]
    rejected = client.post(
        f"/api/v2/suggestions/{b.pk}/reject/", {"reason": "not our voice"}, content_type="application/json"
    ).json()
    assert rejected == {"rejected": True}
    b.refresh_from_db()
    assert (b.status, b.error) == ("rejected", "not our voice")
    assert client.get(INBOX).json()["count"] == 0
    assert client.post(f"/api/v2/suggestions/{a.pk}/approve/").status_code == 404


@pytest.mark.django_db
def test_accept_all_of_a_run_makes_one_revision_per_page(site_root, article, run, editor):
    second = make_article(site_root, "Second page")
    on_first = [
        suggest(article, run, op="meta", field="seo_title", payload={"value": "First"}),
        suggest(article, run, op="meta", field="search_description", payload={"value": "About backups"}),
    ]
    on_second = suggest(second, run, op="meta", field="seo_title", payload={"value": "Second"})
    before = Revision.page_revisions.count()
    client = signed_in(editor)
    result = client.post(f"/api/v2/review/runs/{run.pk}/accept/").json()
    assert sorted(result["accepted"]) == sorted([s.pk for s in on_first] + [on_second.pk])
    assert len(result["revision_ids"]) == 2 and Revision.page_revisions.count() == before + 2
    assert set(Suggestion.objects.filter(run=run).values_list("status", flat=True)) == {"accepted"}
    again = client.post(f"/api/v2/review/runs/{run.pk}/accept/")
    assert again.status_code == 409 and again.json()["error"]["code"] == "resource.conflict"
    assert client.post("/api/v2/review/runs/999999/accept/").status_code == 404


@pytest.mark.django_db
def test_accept_all_needs_the_right_to_edit(article, run):
    suggest(article, run, op="meta", field="seo_title", payload={"value": "Nope"})
    stranger = get_user_model().objects.create_user("stranger", password="pw")
    refused = signed_in(stranger).post(f"/api/v2/review/runs/{run.pk}/accept/")
    assert refused.status_code == 409
    assert Suggestion.objects.get(run=run).status == "pending"


@pytest.mark.django_db
def test_a_browsers_event_source_gets_the_run_stream(article, run, editor):
    run.started_by = editor
    run.status = AgentRun.SUCCEEDED
    run.save()
    response = signed_in(editor).get(f"/api/v2/agent-runs/{run.pk}/stream/", HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 200 and response["Content-Type"] == "text/event-stream"
    body = b"".join(response.streaming_content).decode()
    assert '"status": "succeeded"' in body and body.endswith("event: end\ndata: {}\n\n")
    missing = signed_in(editor).get("/api/v2/agent-runs/999999/stream/", HTTP_ACCEPT="text/event-stream")
    assert missing.status_code == 404
