"""`/api/v2/newsroom/` (PLAN G15): desks a person may see and the permission to
set one up; pitching by hand and from a wire item; the budget and the calendar
as the story list's filters; a story's panel (its history, moves, bylines and
corrections); moves and assignments over REST, with the workflow's refusals as
409s and missing page rights as 403s; the desk's planning decisions and the
pitcher's own pitch; authors and their pages, changed only by the sites their
bylines are on; bylines and corrections in the page API a site reads; and a
bad `site`, an issue moved off its newsletter, refused with the envelope."""

import json
from datetime import date, timedelta

import pytest
from django.contrib.auth.models import Permission
from django.utils import timezone

from newsroom import services
from newsroom.models import Author, Desk, Issue, Newsletter, Story

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


@pytest.mark.django_db
def test_the_desk_decides_a_storys_priority_deadline_slot_and_embargo(api, desk, ed, reporter, advance):
    story = advance(desk, S.COPY, embargo=timezone.now() + timedelta(days=2))
    url = f"{URL}/stories/{story.public_id}/"
    lifted = api(reporter).patch(url, {"embargo": None, "priority": 1}, format="json")
    assert lifted.status_code == 403 and "priority, embargo" in lifted.json()["error"]["message"]
    kept = api(reporter).patch(url, {"headline": "Sharper", "priority": 3}, format="json")  # an unchanged value
    assert kept.status_code == 200 and kept.json()["headline"] == "Sharper"
    later = timezone.now() + timedelta(days=3)
    assert api(ed).patch(url, {"embargo": later.isoformat()}, format="json").status_code == 200
    event = Story.objects.get(pk=story.pk).events.last()
    assert (event.action, event.actor, event.note[:6]) == ("embargo", ed, "until ")
    assert api(ed).get(url).json()["is_editor"] is True and api(reporter).get(url).json()["is_editor"] is False


@pytest.mark.django_db
def test_whoever_pitched_a_story_works_on_the_pitch(api, desk, reporter, copyeditor, fake):
    item = {"url": "https://wire.example/2", "title": "Water main bursts"}
    story = api(reporter).post(f"{URL}/stories/", {"desk": str(desk.public_id), "source": item}, format="json").json()
    url = f"{URL}/stories/{story['id']}/"
    assert api(reporter).patch(url, {"summary": "Flooding on Elm Street."}, format="json").status_code == 200
    fake.script.append({"text": json.dumps({"headline": "Elm Street floods", "angle": "Homes cut off."})})
    assert api(reporter).post(f"{url}ai/", {"kind": "pitch"}, format="json").status_code == 202
    assert api(reporter).patch(url, {"priority": 1}, format="json").status_code == 403  # the desk's decision
    assert api(copyeditor).patch(url, {"summary": "Not theirs."}, format="json").status_code == 403


@pytest.mark.django_db
def test_authors_are_seen_and_changed_by_the_sites_their_bylines_are_on(api, desk, ed, advance, elsewhere):
    other_ed = elsewhere.editors.get()
    ada = Author.objects.create(name="Ada Reporter", slug="ada")
    services.update(advance(desk, S.PUBLISHED), user=ed, bylines=[ada])
    url = f"{URL}/authors/{ada.public_id}/"
    assert api(other_ed).patch(url, {"name": "Renamed by another site"}, format="json").status_code == 404
    assert api(other_ed).delete(url).status_code == 404
    assert str(ada.public_id) not in {a["id"] for a in api(other_ed).get(f"{URL}/authors/").json()["results"]}

    made = api(other_ed).post(f"{URL}/authors/", {"name": "Bo Writer"}, format="json")
    assert made.status_code == 201  # an author no story carries yet: anyone's to byline
    bo = Author.objects.get(public_id=made.json()["id"])
    services.update(Story.objects.get(desk=desk), user=ed, bylines=[ada, bo])
    services.pitch(elsewhere, user=other_ed, headline="Over there", bylines=[bo])
    shared = f"{URL}/authors/{bo.public_id}/"
    for someone in (ed, other_ed):  # bylines on both sites: neither site's editors alone rename them
        assert api(someone).patch(shared, {"bio": "Changed."}, format="json").status_code == 403

    assert api(ed).patch(url, {"bio": "Covers the city."}, format="json").status_code == 200
    gone = api(ed).delete(url)
    assert gone.status_code == 409 and "bylines" in gone.json()["error"]["message"]
    taken = api(ed).post(f"{URL}/authors/", {"name": "Another Ada", "slug": "ada"}, format="json")
    assert taken.status_code == 422 and taken.json()["error"]["details"][0]["field"] == "slug"
    spare = Author.objects.create(name="Spare", slug="spare")
    assert api(ed).delete(f"{URL}/authors/{spare.public_id}/").status_code == 204


@pytest.mark.django_db
def test_a_site_that_is_not_an_id_is_a_422(api, ed):
    for table in ("desks", "stories", "authors", "fronts", "newsletters", "issues"):
        answer = api(ed).get(f"{URL}/{table}/", {"site": "abc"})
        assert answer.status_code == 422 and answer.json()["error"]["details"][0]["field"] == "site", table


@pytest.mark.django_db
def test_an_issue_stays_on_its_newsletter(api, desk, site, ed, reporter, elsewhere):
    elsewhere.editors.add(reporter)  # sees this site's newsletters, curates only the other site's
    here = Newsletter.objects.create(site=site, name="Here", slug="here")
    there = Newsletter.objects.create(site=elsewhere.site, name="There", slug="there")
    issue = Issue.objects.create(newsletter=here, subject="Monday", created_by=ed)
    url = f"{URL}/issues/{issue.public_id}/"
    assert api(reporter).patch(url, {"subject": "Mine"}, format="json").status_code == 403
    moved = api(reporter).patch(url, {"newsletter": str(there.public_id), "subject": "Taken"}, format="json")
    assert moved.status_code == 422 and moved.json()["error"]["details"][0]["field"] == "newsletter"
    issue.refresh_from_db()
    assert (issue.newsletter, issue.subject) == (here, "Monday")
    assert api(ed).patch(url, {"subject": "Tuesday"}, format="json").status_code == 200
