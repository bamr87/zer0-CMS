"""`/api/v2/newsroom/` (PLAN G15): desks a person may see and the permission to
set one up; pitching by hand and from a wire item; the budget and the calendar
as the story list's filters; a story's panel (its history, moves, bylines and
corrections); moves and assignments over REST, with the workflow's refusals as
409s and missing page rights as 403s; authors and their pages; and bylines and
corrections in the page API a site reads."""

from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from newsroom import services
from newsroom.models import Author, Desk, Story

S = Story.Status
URL = "/api/v2/newsroom"


@pytest.mark.django_db
def test_desks_are_seen_by_the_people_of_their_site_and_set_up_with_a_permission(
    api, desk, ed, outsider, site, section
):
    assert api(outsider).get(f"{URL}/desks/").json()["count"] == 0
    listed = api(ed).get(f"{URL}/desks/").json()["results"]
    assert [(d["name"], d["is_editor"], d["section_title"]) for d in listed] == [("Metro", True, "News")]
    assert [p["username"] for p in listed[0]["editors"]] == ["ed"]
    body = {"site": site.pk, "name": "Sports", "slug": "sports", "section": section.pk}
    assert api(ed).post(f"{URL}/desks/", body, format="json").status_code == 403
    ed.user_permissions.add(Permission.objects.get(codename="add_desk"))
    ed = type(ed).objects.get(pk=ed.pk)  # Django caches a person's permissions on the object
    made = api(ed).post(f"{URL}/desks/", {**body, "editor_ids": [ed.pk]}, format="json")
    assert made.status_code == 201, made.json()
    assert Desk.objects.get(slug="sports").editors.get() == ed
    bad = api(ed).post(
        f"{URL}/desks/", {**body, "slug": "bad", "section": site.root_page.get_parent().pk}, format="json"
    )
    assert bad.status_code == 422 and bad.json()["error"]["details"][0]["field"] == "section"
    people = api(ed).get(f"{URL}/desks/{desk.public_id}/people/").json()
    assert {p["username"] for p in people} >= {"ed", "copy"} and "outsider" not in {p["username"] for p in people}


@pytest.mark.django_db
def test_a_pitch_from_a_wire_item_and_the_budget_and_calendar_as_filters(api, desk, ed, reporter, outsider, advance):
    item = {"url": "https://wire.example/bridge", "title": "Bridge to close", "summary": "Repairs.", "feed": "Wire"}
    pitched = api(reporter).post(f"{URL}/stories/", {"desk": str(desk.public_id), "source": item}, format="json")
    assert pitched.status_code == 201, pitched.json()
    story = pitched.json()
    assert (story["headline"], story["summary"], story["status"]) == ("Bridge to close", "Repairs.", "pitch")
    assert story["wire_item"]["url"] == item["url"] and story["moves"] == ["assigned"]
    assert (
        api(outsider).post(f"{URL}/stories/", {"desk": str(desk.public_id), "headline": "x"}, format="json").status_code
        == 422
    )

    slotted = advance(desk, S.DRAFTING, headline="Slotted", slot_date=date(2026, 11, 2))
    advance(desk, S.PUBLISHED, headline="Out already")
    budget = api(ed).get(f"{URL}/stories/", {"status": ["drafting", "published"], "desk": str(desk.public_id)}).json()
    assert sorted(s["headline"] for s in budget["results"]) == ["Out already", "Slotted"]
    week = {"slot_after": "2026-11-01", "slot_before": "2026-11-07"}
    assert [s["headline"] for s in api(ed).get(f"{URL}/stories/", week).json()["results"]] == ["Slotted"]
    mine = api(reporter).get(f"{URL}/stories/", {"assignee": "me"}).json()["results"]
    assert {s["headline"] for s in mine} == {"Slotted", "Out already"}
    assert {s["headline"] for s in api(ed).get(f"{URL}/stories/", {"my_desks": "true"}).json()["results"]} >= {
        "Slotted",
        "Bridge to close",
    }
    assert api(reporter).get(f"{URL}/stories/", {"my_desks": "true"}).json()["count"] == 0
    assert api(outsider).get(f"{URL}/stories/").json()["count"] == 0
    assert api(outsider).get(f"{URL}/stories/{slotted.public_id}/").status_code == 404


@pytest.mark.django_db
def test_a_storys_panel_moves_it_and_refuses_what_the_workflow_does_not_allow(api, desk, ed, reporter, copyeditor):
    story = services.pitch(desk, user=ed, headline="Panel")
    move = f"{URL}/stories/{story.public_id}/move/"
    refused = api(ed).post(move, {"status": "published"}, format="json")
    assert refused.status_code == 409 and refused.json()["error"]["code"] == "story.transition"
    assigned = api(ed).post(move, {"status": "assigned", "assignee": reporter.pk}, format="json").json()
    assert assigned["status"] == "assigned" and assigned["assignee"]["username"] == "reporter"
    assert api(reporter).post(move, {"status": "drafting"}, format="json").json()["status"] == "drafting"
    assert api(reporter).post(move, {"status": "editing"}, format="json").json()["status"] == "editing"
    forbidden = api(reporter).post(move, {"status": "copy"}, format="json")
    assert forbidden.status_code == 403
    assert api(ed).post(move, {"status": "copy"}, format="json").json()["status"] == "copy"

    later = (timezone.now() + timedelta(hours=3)).isoformat()
    scheduled = api(copyeditor).post(move, {"status": "scheduled", "go_live_at": later}, format="json").json()
    assert scheduled["status"] == "scheduled" and not scheduled["page"]["live"]
    panel = api(ed).get(f"{URL}/stories/{story.public_id}/").json()
    assert [e["to_status"] for e in panel["events"]][-1] == "scheduled"
    assert panel["moves"] == ["published"] and panel["corrections"] == [] and panel["ai_runs"] == []


@pytest.mark.django_db
def test_a_reporter_without_publish_rights_gets_a_403_from_the_publish_service(api, desk, ed, reporter, advance):
    desk.copy_editors.set([reporter])
    story = advance(desk, S.COPY)
    answer = api(reporter).post(f"{URL}/stories/{story.public_id}/move/", {"status": "published"}, format="json")
    assert answer.status_code == 403
    assert Story.objects.get(pk=story.pk).status == S.COPY


@pytest.mark.django_db
def test_planning_fields_bylines_reassignment_and_spiking(api, desk, ed, reporter, outsider):
    author = Author.objects.create(name="Ada Reporter", slug="ada")
    other = Author.objects.create(name="Bo Photographer", slug="bo")
    story = services.pitch(desk, user=ed, headline="Plan")
    detail = f"{URL}/stories/{story.public_id}/"
    changed = api(ed).patch(
        detail,
        {
            "priority": 1,
            "deadline": "2026-11-01T17:00:00Z",
            "byline_ids": [str(other.public_id), str(author.public_id)],
        },
        format="json",
    )
    assert changed.status_code == 200, changed.json()
    assert [b["name"] for b in changed.json()["bylines"]] == ["Bo Photographer", "Ada Reporter"]
    assert api(outsider).patch(detail, {"priority": 4}, format="json").status_code == 404
    assigned = api(ed).post(f"{detail}assign/", {"assignee": reporter.pk, "note": "Yours"}, format="json").json()
    assert assigned["status"] == "assigned"
    assert api(reporter).post(f"{detail}assign/", {"assignee": reporter.pk}, format="json").status_code == 403
    assert api(ed).delete(detail).status_code == 409  # only a pitch is spiked
    pitch = services.pitch(desk, user=ed, headline="Spike me")
    assert api(reporter).delete(f"{URL}/stories/{pitch.public_id}/").status_code == 403
    assert api(ed).delete(f"{URL}/stories/{pitch.public_id}/").status_code == 204


@pytest.mark.django_db
def test_an_author_page_lists_the_authors_published_stories(api, desk, ed, reporter, advance):
    made = api(ed).post(f"{URL}/authors/", {"name": "Ada Reporter", "bio": "Covers the city."}, format="json")
    assert made.status_code == 201 and made.json()["slug"] == "ada-reporter"
    assert api(reporter).post(f"{URL}/authors/", {"name": "Not an editor"}, format="json").status_code == 403
    author = Author.objects.get(slug="ada-reporter")
    out = advance(desk, S.PUBLISHED, headline="Out")
    draft = advance(desk, S.DRAFTING, headline="Not yet")
    for story in (out, draft):
        services.update(story, user=ed, bylines=[author])
    page = api(reporter).get(f"{URL}/authors/{author.public_id}/").json()
    assert [s["headline"] for s in page["stories"]] == ["Out"] and page["stories"][0]["url_path"].endswith("/out/")


@pytest.mark.django_db
def test_bylines_and_corrections_are_in_the_page_api(client, desk, ed, advance):
    author = Author.objects.create(name="Ada Reporter", slug="ada")
    story = advance(desk, S.PUBLISHED, headline="Read me")
    services.update(story, user=ed, bylines=[author])
    services.move(story, S.CORRECTED, user=ed, text="An earlier version misspelled the mayor's name.")
    story.refresh_from_db()
    data = client.get(f"/api/v2/pages/{story.page_id}/").json()
    assert data["bylines"] == [{"id": str(author.public_id), "name": "Ada Reporter", "slug": "ada"}]
    assert [(c["kind"], c["text"]) for c in data["corrections"]] == [
        ("correction", "An earlier version misspelled the mayor's name.")
    ]
