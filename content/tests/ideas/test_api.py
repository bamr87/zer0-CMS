"""`/api/v2/ideas/` (ideas/views.py): people only; ideas and boards scoped by
`visible_to` (someone else's private idea is a 404, changing a visible one you
may not change a 403, and a site's board is worked on by the people who edit
that site); anyone who sees an idea votes on it, once; capture works from a
line; a brainstorm answers 202 with its reply's run, and its ideas are kept by
a person; clusters come from the stored vectors; merging and promotion work
through the same services. The fake provider answers; nothing reaches a model."""

import json

import pytest
from django.contrib.auth import get_user_model
from wagtail.models import Site

from agents.models import AgentRun
from ideas.models import Idea

from ..ai.test_services import DETAIL
from .conftest import IDEAS

BASE = "/api/v2/ideas"


@pytest.mark.django_db
def test_every_endpoint_is_for_a_signed_in_person(api, alice):
    agent = get_user_model().objects.get(username="agent:seo")
    for path in ("", "boards/", "clusters/"):
        assert api().get(f"{BASE}/{path}").status_code == 401
        assert api(agent).get(f"{BASE}/{path}").status_code == 403
        assert api(alice).get(f"{BASE}/{path}").status_code == 200


@pytest.mark.django_db
def test_ideas_live_on_boards_or_in_the_inbox_and_are_scoped_and_voted_on(api, alice, bob, site_root):
    from tests.ai.conftest import _person

    carol = _person("carol", editor=True)
    site = Site.objects.get(root_page=site_root)
    board = api(alice).post(f"{BASE}/boards/", {"name": "Team", "site": site.pk, "visibility": "site"}, format="json")
    assert board.status_code == 201, board.content
    board = board.json()
    made = api(alice).post(f"{BASE}/", {"title": "Backups", "board": board["id"], "tags": ["ops"]}, format="json")
    assert made.status_code == 201, made.content
    idea = made.json()
    assert (idea["visibility"], idea["site"], idea["tags"], idea["votes"], idea["voted"]) == (
        "site",
        site.pk,
        ["ops"],
        0,
        False,
    )
    inbox = api(alice).post(f"{BASE}/", {"title": "Mine alone"}, format="json").json()
    assert inbox["visibility"] == "private" and inbox["board"] is None
    assert [i["id"] for i in api(alice).get(f"{BASE}/", {"board": "none"}).json()["results"]] == [inbox["id"]]
    assert [i["id"] for i in api(alice).get(f"{BASE}/", {"board": board["id"]}).json()["results"]] == [idea["id"]]
    assert api(alice).get(f"{BASE}/", {"board": "not-an-id"}).json()["results"] == []
    assert api(bob).get(f"{BASE}/{idea['id']}/").status_code == 404
    moved = api(carol).patch(f"{BASE}/{idea['id']}/", {"status": "planned", "tags": ["ops", "q3"]}, format="json")
    assert moved.status_code == 200 and (moved.json()["status"], moved.json()["tags"]) == ("planned", ["ops", "q3"])
    voted = api(carol).post(f"{BASE}/{idea['id']}/vote/")
    assert (voted.json()["votes"], voted.json()["voted"]) == (1, True)
    assert api(carol).post(f"{BASE}/{idea['id']}/vote/").json()["votes"] == 1  # once per person
    assert api(alice).get(f"{BASE}/{idea['id']}/").json()["voted"] is False
    assert api(carol).delete(f"{BASE}/{idea['id']}/vote/").json()["votes"] == 0
    shared = api(alice).post(f"{BASE}/", {"title": "Open to all", "visibility": "shared"}, format="json").json()
    assert api(bob).post(f"{BASE}/{shared['id']}/vote/").json()["votes"] == 1
    assert api(bob).patch(f"{BASE}/{shared['id']}/", {"title": "taken"}, format="json").status_code == 403
    assert api(bob).delete(f"{BASE}/{shared['id']}/").status_code == 403
    ordered = api(alice).get(f"{BASE}/", {"ordering": "-vote_count"}).json()["results"]
    assert ordered[0]["id"] == shared["id"]


@pytest.mark.django_db
def test_an_idea_shows_only_the_research_brief_and_page_its_viewer_sees_and_a_save_keeps_the_rest(
    api, alice, site_root
):
    from django.contrib.auth.models import Group, Permission
    from wagtail.models import GroupPagePermission

    from ai.models import Brief
    from tests.ai.conftest import _person

    from ..conftest import make_article

    site = Site.objects.get(root_page=site_root)
    dave = _person("dave")  # edits one page of the site: one of its editors, who finds that page and the way to it
    group = Group.objects.create(name="One page")
    change = Permission.objects.get(content_type__app_label="wagtailcore", codename="change_page")
    GroupPagePermission.objects.create(group=group, page=make_article(site_root, "His page"), permission=change)
    dave.groups.add(group)
    note = {"kind": "note", "text": "The CFO resigns on Friday.", "title": "Private lead"}
    private = api(alice).post("/api/v2/research/sources/", note, format="json").json()
    filing = {"kind": "note", "text": "The annual filing.", "title": "Filing"}
    shared = api(alice).post("/api/v2/research/sources/", filing, format="json").json()
    api(alice).patch(f"/api/v2/research/sources/{shared['id']}/", {"visibility": "shared"}, format="json")
    body = {"title": "Team idea", "site": site.pk, "visibility": "site", "source_ids": [private["id"], shared["id"]]}
    idea = api(alice).post(f"{BASE}/", body, format="json").json()
    Idea.objects.filter(public_id=idea["id"]).update(
        brief=Brief.objects.create(owner=alice, title="Secret plan", prompt="A plan"),
        page=make_article(site_root, "Elsewhere", publish=False),
    )
    mine = api(alice).get(f"{BASE}/{idea['id']}/").json()
    assert {s["title"] for s in mine["sources"]} == {"Private lead", "Filing"}
    assert (mine["brief"]["title"], mine["page"]["title"]) == ("Secret plan", "Elsewhere")
    seen = api(dave).get(f"{BASE}/{idea['id']}/").json()
    assert [s["title"] for s in seen["sources"]] == ["Filing"] and (seen["brief"], seen["page"]) == (None, None)
    listed = api(dave).get(f"{BASE}/", {"board": "none"}).json()["results"]
    assert [[s["title"] for s in i["sources"]] for i in listed] == [["Filing"]]
    # Dave saves the idea as the drawer does, with the sources he was shown: Alice's private link stays.
    saved = api(dave).patch(f"{BASE}/{idea['id']}/", {"title": "Sharper", "source_ids": [shared["id"]]}, format="json")
    assert saved.status_code == 200 and [s["title"] for s in saved.json()["sources"]] == ["Filing"]
    assert set(Idea.objects.get(public_id=idea["id"]).sources.values_list("title", flat=True)) == {
        "Private lead",
        "Filing",
    }
    unlinked = api(dave).patch(f"{BASE}/{idea['id']}/", {"source_ids": []}, format="json")
    assert unlinked.status_code == 200
    assert list(Idea.objects.get(public_id=idea["id"]).sources.values_list("title", flat=True)) == ["Private lead"]
    refused = api(dave).patch(f"{BASE}/{idea['id']}/", {"source_ids": [private["id"]]}, format="json")
    assert refused.status_code == 422  # a source he cannot see cannot be named
    # Only the owner changes who sees it; the rest of a site idea is the site editors' to change.
    assert api(dave).patch(f"{BASE}/{idea['id']}/", {"visibility": "shared"}, format="json").status_code == 403
    same = {"visibility": "site", "site": site.pk, "status": "planned"}
    assert api(dave).patch(f"{BASE}/{idea['id']}/", same, format="json").status_code == 200


@pytest.mark.django_db
def test_capture_from_anywhere_and_a_brainstorm_kept_by_a_person(
    api, alice, bob, fake, brainstormed, django_capture_on_commit_callbacks
):
    captured = api(alice).post(
        f"{BASE}/capture/", {"text": "Citability\nfor small sites", "template": "topic"}, format="json"
    )
    assert captured.status_code == 201 and captured.json()["origin"] == "captured"
    assert captured.json()["notes"] == "for small sites"
    templated = (
        api(alice).post(f"{BASE}/capture/", {"text": "Restore drills", "template": "topic"}, format="json").json()
    )
    assert templated["notes"].startswith("## Why this topic matters")
    fake.script.append(brainstormed)
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(
            f"{BASE}/brainstorm/", {"prompt": "backups", "kind": "angles", "count": 3}, format="json"
        )
    assert response.status_code == 202, response.content
    body = response.json()
    assert AgentRun.objects.get(pk=body["run"]["id"]).status == "succeeded" and body["reply"]["status"] == "queued"
    reply = api(alice).get(f"/api/v2/ai/messages/{body['reply']['id']}/").json()
    assert reply["status"] == "completed" and reply["result"] == IDEAS
    assert api(bob).post(f"{BASE}/keep/", {"message": body["reply"]["id"]}, format="json").status_code == 422  # not his
    kept = api(alice).post(f"{BASE}/keep/", {"message": body["reply"]["id"], "picks": [1]}, format="json")
    assert kept.status_code == 201
    assert [(i["title"], i["origin"], i["source_message"]) for i in kept.json()["ideas"]] == [
        ("Your site will break. Will you notice?", "brainstormed", body["reply"]["id"])
    ]
    assert (
        api(alice).post(f"{BASE}/brainstorm/", {"prompt": "x", "kind": "limericks"}, format="json").status_code == 422
    )


@pytest.mark.django_db
def test_clusters_duplicates_and_merging(api, alice, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        first = api(alice).post(f"{BASE}/capture/", {"text": "Nightly backups for small sites"}, format="json").json()
        copy = (
            api(alice)
            .post(f"{BASE}/capture/", {"text": "Nightly backups for small sites, explained"}, format="json")
            .json()
        )
        api(alice).post(f"{BASE}/capture/", {"text": "Sourdough starter tips"}, format="json")
    found = api(alice).get(f"{BASE}/clusters/", {"board": "none"}).json()
    assert found["model"] == "hashing-256" and found["pending"] == []
    assert [sorted(i["title"] for i in c["ideas"]) for c in found["clusters"]] == [
        sorted([first["title"], copy["title"]])
    ]
    pair = found["duplicates"][0]
    assert {pair["a"]["id"], pair["b"]["id"]} == {first["id"], copy["id"]} and pair["similarity"] >= 0.85
    merged = api(alice).post(f"{BASE}/{first['id']}/merge/", {"other": copy["id"]}, format="json")
    assert merged.status_code == 200 and not Idea.objects.filter(public_id=copy["id"]).exists()
    assert api(alice).get(f"{BASE}/clusters/", {"threshold": "0.99"}).json()["clusters"] == []


@pytest.mark.django_db
def test_promotion_to_a_brief_written_now_and_to_an_article_draft(
    api, alice, bob, fake, site_root, django_capture_on_commit_callbacks
):
    idea = api(alice).post(f"{BASE}/capture/", {"text": "Restore drills\nOnce a quarter."}, format="json").json()
    assert api(bob).post(f"{BASE}/{idea['id']}/promote/", {"into": "brief"}, format="json").status_code == 404
    fake.script += [{"text": "# Restore drills\n\nRun them."}, {"text": json.dumps(DETAIL)}]
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(f"{BASE}/{idea['id']}/promote/", {"into": "brief", "generate": True}, format="json")
    assert response.status_code == 202, response.content
    promoted = response.json()
    assert promoted["idea"]["status"] == "promoted" and promoted["idea"]["brief"]["id"] == promoted["brief"]["id"]
    assert promoted["page_id"] is None and AgentRun.objects.get(pk=promoted["run"]["id"]).status == "succeeded"
    brief = api(alice).get(f"/api/v2/ai/briefs/{promoted['brief']['id']}/").json()
    assert brief["status"] == "ready" and brief["markdown"] == "# Restore drills\n\nRun them."
    other = api(alice).post(f"{BASE}/capture/", {"text": "A guide to restores"}, format="json").json()
    drafted = api(alice).post(
        f"{BASE}/{other['id']}/promote/", {"into": "article", "parent": site_root.pk}, format="json"
    )
    assert drafted.status_code == 201 and drafted.json()["run"] is None
    assert drafted.json()["idea"]["page"] == {"id": drafted.json()["page_id"], "title": "A guide to restores"}
    no_parent = api(alice).post(f"{BASE}/{other['id']}/promote/", {"into": "book"}, format="json")
    assert no_parent.status_code == 422
