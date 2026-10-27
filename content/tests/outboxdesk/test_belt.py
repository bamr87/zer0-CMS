"""`/api/v2/outbox/belt/` (outboxdesk/views.py): people with the desk's permissions only; the belt read through the
library — summary, messages filtered and paged, a message's CloudEvents form, a piece's journey, the dead letters;
a person sends an idea, an approval or a signal as the editor station, validated by the library and recorded with
who sent it; the relay delivers in the worker, now or on beat. A harness that cannot load is a 503."""

import json
import sys

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model

from outboxdesk import harness, tasks
from outboxdesk.models import SentHandoff

BASE = "/api/v2/outbox/belt"


def belt():
    lib = harness.module("belt")
    return lib, lib.Belt(settings.OUTBOX_BELT_ROOT, settings.OUTBOX_BELT_STATIONS)


@pytest.fixture
def piece():
    """A piece of work some way down the belt: a scout's idea, its draft, and the verifier's verdict to the editor."""
    lib, b = belt()
    idea = lib.Handoff(
        kind="idea", from_station="scout-a", to=["planner", "ledger"], subject="hydra-guide", payload={"title": "Hydra"}
    )
    draft = idea.reply("draft", "drafter", ["verifier", "ledger"], {"revision": 1}, ref={"path": "_posts/hydra.md"})
    verdict = draft.reply("verdict", "verifier", ["editor", "ledger"], {"verdict": "pass", "tier": "factual"})
    for station, message in (("scout-a", idea), ("drafter", draft), ("verifier", verdict)):
        b.station(station).send(message)
    b.deliver()
    return idea, draft, verdict


@pytest.mark.django_db
def test_the_belt_is_for_people_who_hold_the_desks_permissions(api, ed, reader, nobody):
    agent = get_user_model().objects.get(username="agent:seo")
    for path in ("/", "/messages/", "/dead-letters/"):
        assert api().get(f"{BASE}{path}").status_code == 401
        assert api(agent).get(f"{BASE}{path}").status_code == 403
        assert api(nobody).get(f"{BASE}{path}").status_code == 403
        assert api(reader).get(f"{BASE}{path}").status_code == 200
    idea = {"kind": "idea", "to": ["planner"], "subject": "x"}
    refused = api(reader).post(f"{BASE}/send/", idea, format="json")
    assert refused.status_code == 403 and refused.json()["error"]["code"] == "auth.forbidden"
    assert api(reader).post(f"{BASE}/deliver/").status_code == 403
    assert api(ed).post(f"{BASE}/send/", idea, format="json").status_code == 201


@pytest.mark.django_db
def test_a_person_sends_an_idea_as_the_editor_and_the_relay_delivers_it(api, ed, worker):
    idea = {
        "kind": "idea",
        "to": ["planner", "ledger"],
        "subject": "backups-guide",
        "payload": {"title": "Backups", "by": "someone else"},
    }
    sent = api(ed).post(f"{BASE}/send/", idea, format="json")
    assert sent.status_code == 201
    body = sent.json()
    assert (body["from"], body["kind"], body["seq"], body["payload"]) == (
        "editor",
        "idea",
        None,
        {"title": "Backups", "by": "ed"},
    )
    assert len(body["trace"]) == 32 and body["parent_id"] is None
    assert SentHandoff.objects.get(public_id=body["id"]).sent_by == ed
    summary = api(ed).get(f"{BASE}/").json()
    assert (summary["delivered"], summary["pending"], summary["editor"]) == (0, 1, "editor")
    assert set(summary["stations"]) == set(settings.OUTBOX_BELT_STATIONS) and summary["harness"]

    queued = worker(api(ed).post, f"{BASE}/deliver/")
    assert queued.status_code == 202 and queued.json() == {"pending": 1}
    summary = api(ed).get(f"{BASE}/").json()
    assert (summary["delivered"], summary["pending"], summary["seq_gapless"], summary["ids_unique"]) == (
        1,
        0,
        True,
        True,
    )
    assert summary["kinds"] == [{"kind": "idea", "count": 1}]
    inbox = settings.OUTBOX_BELT_ROOT / "stations" / "planner" / "inbox"
    assert [json.loads(p.read_text())["id"] for p in inbox.glob("*.json")] == [body["id"]]
    listed = api(ed).get(f"{BASE}/messages/").json()
    assert listed["count"] == 1 and listed["results"][0]["seq"] == 1
    assert tasks.deliver_belt() == 0  # beat's pass finds nothing left
    assert settings.CELERY_BEAT_SCHEDULE["outbox-belt"]["task"] == "outboxdesk.tasks.deliver_belt"


@pytest.mark.django_db
def test_an_approval_answers_a_delivered_message_keeps_its_trace_and_names_its_page(api, ed, worker, article, piece):
    idea, draft, verdict = piece
    approve = {
        "kind": "approval",
        "to": ["publisher", "ledger"],
        "parent_id": verdict.id,
        "page": article.pk,
        "payload": {"note": "ship it"},
    }
    sent = api(ed).post(f"{BASE}/send/", approve, format="json")
    assert sent.status_code == 201
    approval = sent.json()
    assert (approval["trace"], approval["subject"], approval["parent_id"]) == (idea.trace, "hydra-guide", verdict.id)
    assert approval["ref"]["page_id"] == article.pk and approval["ref"]["url"]
    worker(api(ed).post, f"{BASE}/deliver/")

    journey = api(ed).get(f"{BASE}/traces/{idea.trace}/").json()
    assert [(m["seq"], m["from"], m["kind"]) for m in journey["messages"]] == [
        (1, "scout-a", "idea"),
        (2, "drafter", "draft"),
        (3, "verifier", "verdict"),
        (4, "editor", "approval"),
    ]
    one = api(ed).get(f"{BASE}/messages/{approval['id']}/").json()
    assert one["seq"] == 4 and one["cloudevent"]["type"] == "dev.bamr87.outbox.approval"
    assert (
        one["cloudevent"]["traceparent"].startswith(f"00-{idea.trace}-")
        and one["cloudevent"]["source"] == "outbox://belt/editor"
    )

    def listed(**query):
        return api(ed).get(f"{BASE}/messages/", query).json()

    assert [m["kind"] for m in listed()["results"]] == ["approval", "verdict", "draft", "idea"]
    assert [m["kind"] for m in listed(ordering="seq")["results"]] == ["idea", "draft", "verdict", "approval"]
    assert [m["kind"] for m in listed(station="editor")["results"]] == ["approval", "verdict"]
    assert [m["kind"] for m in listed(kind="draft")["results"]] == ["draft"]
    assert listed(trace="0" * 32)["count"] == 0
    paged = listed(page_size=3)
    assert (paged["count"], len(paged["results"]), bool(paged["next"])) == (4, 3, True)
    assert api(ed).get(f"{BASE}/traces/{'f' * 32}/").status_code == 404
    assert api(ed).get(f"{BASE}/messages/no-such-id/").json()["error"]["code"] == "resource.not_found"


@pytest.mark.django_db
def test_the_library_and_the_desk_refuse_a_handoff_the_belt_would_not_carry(api, ed, piece):
    idea, _, verdict = piece

    def refused(**body):
        response = api(ed).post(f"{BASE}/send/", {"to": ["publisher"], **body}, format="json")
        assert response.status_code == 422, response.json()
        return {d["field"] for d in response.json()["error"]["details"]}

    assert refused(kind="approval", subject="x") == {"parent_id"}  # the library: an approval answers something
    assert refused(kind="approval", parent_id="not-delivered") == {"parent_id"}
    assert refused(kind="approval", parent_id=verdict.id, trace="a" * 32) == {"trace"}
    assert refused(kind="draft", subject="x") == {"kind"}  # a person sends ideas, approvals and signals
    assert refused(kind="idea") == {"subject"}
    assert refused(kind="idea", subject="x", to=["nowhere"]) == {"to"}
    assert refused(kind="signal", subject="x", trace="not-hex") == {"trace"}
    assert refused(kind="idea", subject="x", page=999999) == {"page"}
    signal = api(ed).post(
        f"{BASE}/send/",
        {"kind": "signal", "to": ["planner"], "subject": "hydra-guide", "trace": idea.trace},
        format="json",
    )
    assert signal.status_code == 201 and signal.json()["trace"] == idea.trace
    assert SentHandoff.objects.count() == 1


@pytest.mark.django_db
def test_the_relay_dead_letters_what_it_cannot_carry_and_the_desk_says_why(api, ed, worker):
    outbox = settings.OUTBOX_BELT_ROOT / "stations" / "planner" / "outbox"
    outbox.mkdir(parents=True)
    (outbox / "20261027_idea_broken.json").write_text("{not json")
    (outbox / "20261027_idea_x.json").write_text(json.dumps({"id": "x", "kind": "idea"}))
    assert api(ed).get(f"{BASE}/").json()["pending"] == 2
    worker(api(ed).post, f"{BASE}/deliver/")
    summary = api(ed).get(f"{BASE}/").json()
    assert (summary["delivered"], summary["dead_letters"], summary["pending"]) == (0, 2, 0)
    dead = api(ed).get(f"{BASE}/dead-letters/").json()
    assert {d["path"] for d in dead} == {"20261027_idea_broken.json", "20261027_idea_x.json"}
    assert "unparseable_json" in next(d for d in dead if d["path"].endswith("broken.json"))["errors"]
    assert "missing:subject" in next(d for d in dead if d["id"] == "x")["errors"]


@pytest.mark.django_db
def test_a_harness_that_cannot_load_is_a_503_and_the_platform_still_answers(api, ed, monkeypatch):
    for name in [n for n in sys.modules if n == harness.NAME or n.startswith(f"{harness.NAME}.")]:
        monkeypatch.delitem(sys.modules, name)

    def missing(name):
        raise harness.metadata.PackageNotFoundError(name)

    monkeypatch.setattr(harness.metadata, "distribution", missing)
    response = api(ed).get(f"{BASE}/")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "outbox.unavailable"
    assert api(ed).get("/api/v2/me").status_code == 200


def test_the_desk_names_the_kinds_the_library_has_and_the_platform_keeps_its_outbox():
    from outboxdesk.serializers import KINDS

    assert KINDS == tuple(harness.module("belt").KINDS)
    import outbox

    assert (
        outbox.__file__.endswith("content/outbox/__init__.py")
        and harness.module("belt").__name__ == "outbox_harness.belt"
    )
