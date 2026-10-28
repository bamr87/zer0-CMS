"""The review inbox (api/review.py) and the decisions it leads to: pending
suggestions across pages with their diffs, accept one, reject with a reason,
accept the suggestions of a run a person saw — all through one scope, so a
person sees, decides and opens the runs of exactly what they may — and the
run's live event stream as a browser's EventSource asks for it."""

import uuid

import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType
from django.test import Client
from django.utils import timezone
from wagtail.models import Page, Revision

from agents.models import AgentRun
from cms.models import ArticlePage, ContentImage
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
    assert set(rows) == {str(title.public_id), str(replace.public_id), str(insert.public_id)}
    assert rows[str(title.public_id)]["change"] == {
        "kind": "field",
        "label": "seo_title",
        "before": "",
        "after": "Backups, explained",
        "stale": False,
    }
    assert rows[str(replace.public_id)]["change"]["before"] == "We copy the site to a second disk every night."
    assert (
        rows[str(replace.public_id)]["change"]["after"] == "Twice."
        and rows[str(replace.public_id)]["change"]["label"] == "replace markdown"
    )
    assert (
        rows[str(insert.public_id)]["change"]["after"] == "### Why"
        and rows[str(insert.public_id)]["change"]["before"] == ""
    )
    assert rows[str(title.public_id)]["target"] == {"type": "page", "id": article.pk, "title": "Nightly backups"}
    assert rows[str(title.public_id)]["agent"] == "seo" and rows[str(title.public_id)]["run_id"] == str(run.public_id)


@pytest.mark.django_db
def test_the_inbox_filters_and_shows_people_only_what_they_may_decide(site_root, article, run, editor, agent):
    other_page = make_article(site_root, "Another page")
    other_run = AgentRun.objects.create(agent=agent("seo"), trigger="manual")
    mine = suggest(article, run, op="meta", field="seo_title", payload={"value": "One"})
    theirs = suggest(other_page, other_run, op="meta", field="seo_title", payload={"value": "Two"})
    client = signed_in(editor)
    assert [r["id"] for r in client.get(INBOX, {"run": str(run.public_id)}).json()["results"]] == [str(mine.public_id)]
    assert [r["id"] for r in client.get(INBOX, {"page_id": other_page.pk}).json()["results"]] == [str(theirs.public_id)]
    assert client.get(INBOX, {"site": 999999}).json()["count"] == 0
    stranger = get_user_model().objects.create_user("stranger", password="pw")
    assert signed_in(stranger).get(INBOX).json()["count"] == 0


@pytest.mark.django_db
def test_a_pages_suggestions_never_include_an_image_with_the_same_id(article, run):
    on_page = suggest(article, run, op="meta", field="seo_title", payload={"value": "Page"})
    image = Suggestion.objects.create(  # an image's suggestion; images and pages number their rows apart
        target_ct=ContentType.objects.get_for_model(ContentImage),
        target_id=article.pk,
        op="meta",
        field="ai_alt",
        payload={"value": "A disk"},
        run=run,
    )
    admin = get_user_model().objects.create_superuser("admin", password="pw")
    client = signed_in(admin)
    assert [r["id"] for r in client.get(INBOX, {"page_id": article.pk}).json()["results"]] == [str(on_page.public_id)]
    assert {r["id"] for r in client.get(INBOX).json()["results"]} == {str(on_page.public_id), str(image.public_id)}


@pytest.mark.django_db
def test_a_suggestion_whose_block_is_gone_is_marked_stale(article, run, editor):
    gone = suggest(article, run, op="delete", block_id=article.body[0].id)
    page = article.get_latest_revision_as_object()
    page.body = [b for b in page.body.get_prep_value() if b["id"] != article.body[0].id]
    page.save_revision(user=editor)
    row = signed_in(editor).get(INBOX).json()["results"][0]
    assert row["id"] == str(gone.public_id) and row["change"]["stale"] is True


@pytest.mark.django_db
def test_accept_one_and_reject_one_with_a_reason(article, run, editor):
    a = suggest(article, run, op="meta", field="seo_title", payload={"value": "Accepted title"})
    b = suggest(article, run, op="meta", field="search_description", payload={"value": "Off-brand"})
    client = signed_in(editor)
    accepted = client.post(f"/api/v2/suggestions/{a.public_id}/accept/", {}, content_type="application/json").json()
    assert accepted["accepted"] is True and accepted["revision_id"]
    rejected = client.post(
        f"/api/v2/suggestions/{b.public_id}/reject/", {"reason": "not our voice"}, content_type="application/json"
    ).json()
    assert rejected == {"rejected": True}
    b.refresh_from_db()
    assert (b.status, b.error) == ("rejected", "not our voice")
    assert client.get(INBOX).json()["count"] == 0
    assert client.post(f"/api/v2/suggestions/{a.public_id}/approve/").status_code == 404


def accept_shown(client, run, suggestions):
    ids = [str(s.public_id) for s in suggestions]
    return client.post(f"/api/v2/review/runs/{run.public_id}/accept/", {"ids": ids}, content_type="application/json")


@pytest.mark.django_db
def test_accept_all_shown_of_a_run_makes_one_revision_per_page_and_nothing_more(site_root, article, run, editor):
    second = make_article(site_root, "Second page")
    on_first = [
        suggest(article, run, op="meta", field="seo_title", payload={"value": "First"}),
        suggest(article, run, op="meta", field="search_description", payload={"value": "About backups"}),
    ]
    on_second = suggest(second, run, op="meta", field="seo_title", payload={"value": "Second"})
    unseen = suggest(second, run, op="meta", field="search_description", payload={"value": "Never shown"})
    before = Revision.page_revisions.count()
    client = signed_in(editor)
    result = accept_shown(client, run, [*on_first, on_second]).json()
    assert sorted(result["accepted"]) == sorted([str(s.public_id) for s in on_first] + [str(on_second.public_id)])
    assert len(result["revision_ids"]) == 2 and Revision.page_revisions.count() == before + 2
    unseen.refresh_from_db()
    assert unseen.status == "pending"  # the person never saw it, so it was not accepted
    again = accept_shown(client, run, [on_second])
    assert again.status_code == 409 and again.json()["error"]["code"] == "resource.conflict"
    assert (
        client.post(f"/api/v2/review/runs/{run.public_id}/accept/", {}, content_type="application/json").status_code
        == 422
    )
    assert accept_shown(client, AgentRun(), [unseen])  # a run that does not exist.status_code == 404


@pytest.mark.django_db
def test_deciding_needs_the_right_to_edit_and_never_names_what_it_refuses(article, run):
    shown = suggest(article, run, op="meta", field="seo_title", payload={"value": "Nope"})
    stranger = get_user_model().objects.create_user("stranger", password="pw")
    client = signed_in(stranger)
    for refused in (
        accept_shown(client, run, [shown]),  # a run they may not see
        client.post(f"/api/v2/suggestions/{shown.public_id}/accept/", {}, content_type="application/json"),
        client.post(f"/api/v2/suggestions/{shown.public_id}/reject/", {}, content_type="application/json"),
    ):
        assert refused.status_code == 404 and "Nightly" not in refused.content.decode()
    run.started_by = stranger  # a run they started, on a page they may not change
    run.save(update_fields=["started_by"])
    refused = accept_shown(client, run, [shown])
    assert refused.status_code == 409 and "Nightly" not in refused.content.decode()
    assert Suggestion.objects.get(run=run).status == "pending"


@pytest.mark.django_db
def test_a_reviewer_opens_the_run_behind_what_they_review(article, run, editor):
    suggest(article, run, op="meta", field="seo_title", payload={"value": "Why"})
    client = signed_in(editor)  # did not start the run, may decide its suggestion
    assert client.get(f"/api/v2/agent-runs/{run.public_id}/").json()["id"] == str(run.public_id)
    assert str(run.public_id) in {r["id"] for r in client.get("/api/v2/agent-runs/").json()["results"]}
    stranger = signed_in(get_user_model().objects.create_user("stranger", password="pw"))
    assert stranger.get(f"/api/v2/agent-runs/{run.public_id}/").status_code == 404
    assert stranger.get("/api/v2/agent-runs/").json()["results"] == []


@pytest.mark.django_db
def test_an_accepted_paragraph_keeps_its_internal_link(site_root, article, run, editor):
    target = make_article(site_root, "The docs")
    value = f'<p>Read <a linktype="page" id="{target.pk}">the docs</a> first.</p>'
    s = suggest(article, run, op="insert", payload={"type": "paragraph", "value": value})
    client = signed_in(editor)
    assert (
        client.post(f"/api/v2/suggestions/{s.public_id}/accept/", {}, content_type="application/json").status_code
        == 200
    )
    block = ArticlePage.objects.get(pk=article.pk).get_latest_revision_as_object().body[-1]
    raw = block.block.get_prep_value(block.value)
    assert f'id="{target.pk}"' in raw and 'linktype="page"' in raw


@pytest.mark.django_db
def test_a_locked_page_refuses_an_accept(article, run, editor):
    s = suggest(article, run, op="meta", field="seo_title", payload={"value": "Later"})
    other = get_user_model().objects.create_user("other", password="pw")
    Page.objects.filter(pk=article.pk).update(locked=True, locked_by=other, locked_at=timezone.now())
    refused = signed_in(editor).post(f"/api/v2/suggestions/{s.public_id}/accept/", {}, content_type="application/json")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "resource.locked"
    s.refresh_from_db()
    assert s.status == "pending"


@pytest.mark.django_db
def test_a_browsers_event_source_gets_the_run_stream(article, run, editor):
    run.started_by = editor
    run.status = AgentRun.SUCCEEDED
    run.save()
    response = signed_in(editor).get(f"/api/v2/agent-runs/{run.public_id}/stream/", HTTP_ACCEPT="text/event-stream")
    assert response.status_code == 200 and response["Content-Type"] == "text/event-stream"
    body = b"".join(response.streaming_content).decode()
    assert body.startswith(": open\n\n")  # a comment first, so the headers reach the browser at once
    assert '"status": "succeeded", "is_final": true' in body and body.endswith("event: end\ndata: {}\n\n")
    missing = signed_in(editor).get(f"/api/v2/agent-runs/{uuid.uuid4()}/stream/", HTTP_ACCEPT="text/event-stream")
    assert missing.status_code == 404
