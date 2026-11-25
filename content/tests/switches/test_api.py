"""`/api/v2/switches/` end to end over recorded GitHub (respx): the board with and without a credential, the
credential written and never returned, a preview that writes nothing, and an apply that needs a confirmation, a
reason and an unchanged preview — whose job sets each variable, reads it back and records the flip as an event."""

import json

import httpx
import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from jobs.models import Job
from outbox.models import OutboxEvent
from outbox.schemas import check_data
from switches.models import SwitchConfig

from .conftest import HUB, LH, MAP, TOKEN, variables_of


def board(api):
    response = api.get("/api/v2/switches/")
    assert response.status_code == 200, response.json()
    return response.json()


def switches_of(body, repo):
    outlet = next(o for o in body["outlets"] if o["repo"] == repo)
    return {(s["loop"] or s["variable"]): s for s in outlet["switches"]}


def preview(api, **body):
    response = api.post("/api/v2/switches/preview/", body, format="json")
    assert response.status_code == 200, response.json()
    return response.json()


def apply(api, capture, **body):
    with capture(execute=True):
        return api.post("/api/v2/switches/apply/", body, format="json")


# ── who may ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "method,path",
    [("get", ""), ("get", "config/"), ("patch", "config/"), ("post", "preview/"), ("post", "apply/")],
)
def test_only_people_who_manage_sites_reach_any_of_it(db, config, method, path):
    person = get_user_model().objects.create_user("writer", password="pw")
    client = APIClient()
    client.force_authenticate(person)
    response = getattr(client, method)(f"/api/v2/switches/{path}", {}, format="json")
    assert response.status_code == 403 and "manage sites" in response.json()["error"]["message"]
    assert APIClient().get("/api/v2/switches/").status_code in (401, 403)


def test_an_agent_is_refused(db, config):
    agent = get_user_model().objects.get(username="agent:seo")
    client = APIClient()
    client.force_authenticate(agent)
    assert client.get("/api/v2/switches/").status_code == 403


# ── the board ───────────────────────────────────────────────────────────────


def test_without_a_credential_the_map_is_shown_and_no_variable_is_read(api, config, github):
    body = board(api)
    assert body["hub"] == {
        "repo": "bamr87/bamr87",
        "path": "_data/fleet.yml",
        "ref": "main",
        "read_from": "github",
        "read": True,
        "error": "",
    }
    assert body["credential"]["set"] is False
    assert "“Variables”" in body["credential"]["needs"] and "o/lh, o/ij" in body["credential"]["needs"]
    lh = next(o for o in body["outlets"] if o["repo"] == "o/lh")
    assert not lh["readable"] and lh["error"] == "no credential: the variables are not read"
    rows = switches_of(body, "o/lh")
    assert list(rows) == ["lh/factory", "lh/issue-1", "lh/issue-2", "lh/auto-merge", "lh/weekly-epic", "lh/nightly"]
    assert rows["lh/factory"]["effective"] == "unknown" and rows["lh/factory"]["map_state"] == "on"
    assert rows["lh/nightly"]["effective"] == "on"  # no switch: the map's word
    assert [c.request.url.path for c in github.calls] == [HUB]
    assert "Authorization" not in github.calls.last.request.headers


def test_with_a_credential_every_outlet_is_read_against_the_map(api, credential, github):
    body = board(api)
    assert body["credential"] == {"set": True, "error": "", "needs": body["credential"]["needs"]}
    rows = switches_of(body, "o/lh")
    assert rows["lh/factory"]["effective"] == "on" and not rows["lh/factory"]["drift"]
    assert rows["lh/issue-1"]["live"] == "false" and rows["lh/issue-1"]["drift"]  # the map says on
    assert rows["lh/auto-merge"]["hold"]["name"] == "HUB_ORIGINATION_HOLD" and rows["lh/auto-merge"]["drift"]
    assert rows["lh/weekly-epic"]["live_state"] == "unset" and rows["lh/weekly-epic"]["effective"] == "off"
    assert rows["BRAND_SWEEP_ENABLED"]["in_map"] is False and rows["BRAND_SWEEP_ENABLED"]["effective"] == "off"
    assert "NODE_VERSION" not in rows
    ij = switches_of(body, "o/ij")
    assert ij["ij/daily"]["live_state"] == "unset" and ij["ij/daily"]["effective"] == "on"  # opt-out, unset
    assert ij["ij/links"]["effective"] == "off"  # its group is off
    assert {"QUEST_FIX_ENABLED", "CONTENT_AUTOMERGE_ENABLED"} <= set(ij)
    sent = [c.request for c in github.calls if "variables" in c.request.url.path]
    assert sent and all(r.headers["Authorization"] == f"Bearer {TOKEN}" for r in sent)


def test_variables_are_read_page_by_page(api, credential, github):
    many = {f"LOOP_{i:02d}_ENABLED": "true" for i in range(35)}
    pages = list(many.items())
    first = {"total_count": 35, "variables": [{"name": k, "value": v} for k, v in pages[:30]]}
    second = {"total_count": 35, "variables": [{"name": k, "value": v} for k, v in pages[30:]]}
    paged = github.get("/repos/o/lh/actions/variables").mock(
        side_effect=lambda request: httpx.Response(200, json=first if request.url.params["page"] == "1" else second)
    )
    rows = switches_of(board(api), "o/lh")
    assert sum(1 for name in rows if name.startswith("LOOP_")) == 35
    assert [c.request.url.params["per_page"] for c in paged.calls] == ["30", "30"]


def test_an_outlet_github_will_not_answer_is_unreadable_never_off(api, credential, github):
    github.get("/repos/o/lh/actions/variables").respond(403, json={"message": "Resource not accessible"})
    github.get("/repos/o/ij/actions/variables").respond(404, json={"message": "Not Found"})
    body = board(api)
    for outlet in body["outlets"]:
        assert not outlet["readable"] and "HTTP 40" in outlet["error"]
        assert all(s["effective"] in ("unknown", "on", "off") for s in outlet["switches"])
    rows = switches_of(body, "o/lh")
    assert rows["lh/factory"]["effective"] == "unknown" and rows["lh/factory"]["live_state"] == "unreadable"
    assert switches_of(body, "o/ij")["ij/daily"]["effective"] == "unknown"


def test_a_map_that_cannot_be_read_leaves_the_unmapped_variables(api, credential, github):
    github.get(HUB).respond(404, json={"message": "Not Found"})
    body = board(api)
    assert body["hub"]["read"] is False and "could not be read (HTTP 404" in body["hub"]["error"]
    rows = switches_of(body, "o/lh")
    assert all(not s["in_map"] for s in rows.values()) and "CONTENT_FACTORY_ENABLED" in rows
    github.get(HUB).respond(200, text="switches: {schema: switches/v0}\n")
    assert "schema switches/v1" in board(api)["hub"]["error"]


def test_a_local_hub_checkout_is_read_instead_of_github(api, credential, github, tmp_path, settings):
    (tmp_path / "_data").mkdir()
    (tmp_path / "_data" / "fleet.yml").write_text(MAP.replace("lh/factory", "lh/factory-local"))
    settings.SWITCHES_HUB_CHECKOUT = str(tmp_path)
    body = board(api)
    assert body["hub"]["read_from"] == "checkout" and body["hub"]["read"]
    assert "lh/factory-local" in switches_of(body, "o/lh")
    assert all(c.request.url.path != HUB for c in github.calls)


# ── the configuration ───────────────────────────────────────────────────────


def test_the_credential_goes_in_encrypted_and_never_comes_back(api, config):
    answer = api.patch("/api/v2/switches/config/", {"credential": TOKEN}, format="json")
    assert answer.status_code == 200 and answer.json()["has_credential"] is True
    assert TOKEN not in json.dumps(answer.json()) and "credential" not in answer.json()
    stored = SwitchConfig.objects.get()
    assert stored.credential_encrypted and TOKEN not in stored.credential_encrypted
    assert stored.get_credential() == TOKEN and stored.updated_by.username == "manager"
    assert TOKEN not in json.dumps(api.get("/api/v2/switches/config/").json())
    removed = api.patch("/api/v2/switches/config/", {"credential": ""}, format="json").json()
    assert removed["has_credential"] is False


def test_the_outlets_are_a_list_of_repositories(api, config):
    default = SwitchConfig(pk=99)
    assert default.outlets == ["bash-365/bash-365.com", "bamr87/lifehacker.dev", "bamr87/it-journey"]
    changed = api.patch("/api/v2/switches/config/", {"outlets": ["bamr87/lifehacker.dev"]}, format="json").json()
    assert changed["outlets"] == ["bamr87/lifehacker.dev"]
    for bad in (["not a repo"], ["a/b", "A/B"], ["../x/y"]):
        refused = api.patch("/api/v2/switches/config/", {"outlets": bad}, format="json")
        assert refused.status_code == 422, refused.json()


def test_rotating_the_ai_keys_rotates_the_credential(credential, settings):
    before = SwitchConfig.objects.get().credential_encrypted
    settings.AI_CREDENTIAL_KEYS = ["k2dwlHlI2m3e9CVhEZ6x2Gdhm8E0Gq4CWZB4HnNy6ug="]
    call_command("rotate_ai_credentials", verbosity=0)
    after = SwitchConfig.objects.get()
    assert after.credential_encrypted != before and after.get_credential() == TOKEN


# ── preview ─────────────────────────────────────────────────────────────────


def test_a_preview_of_one_switch_says_what_would_be_written_and_writes_nothing(api, credential, github):
    body = preview(api, repo="o/lh", switch="WEEKLY_EPIC_ENABLED", target="on")
    assert body["scope"] == "switch" and body["writes"] == 1 and len(body["digest"]) == 64
    [change] = body["changes"]
    assert change | {"hold": None} == {
        "name": "WEEKLY_EPIC_ENABLED",
        "loops": ["lh/weekly-epic"],
        "in_map": True,
        "current": None,
        "current_state": "unset",
        "new": "true",
        "action": "create",
        "why": "then record it in the hub map",
        "hold": None,
    }
    assert all(c.request.method == "GET" for c in github.calls)


def test_a_preview_of_an_outlet_covers_each_variable_once(api, credential, github):
    body = preview(api, repo="o/lh", target="on", reason="switch them all on")
    changes = {c["name"]: c for c in body["changes"]}
    assert body["scope"] == "outlet" and body["reason"] == "switch them all on"
    assert changes["ISSUE_FACTORY_ENABLED"]["loops"] == ["lh/issue-1", "lh/issue-2"]
    assert changes["ISSUE_FACTORY_ENABLED"]["action"] == "update"
    assert changes["CONTENT_FACTORY_ENABLED"]["action"] == "none"
    assert changes["AUTO_MERGE_ENABLED"]["action"] == "none"  # already true: nothing to refuse
    assert changes["BRAND_SWEEP_ENABLED"]["why"] == "not in the hub map: record it there"
    assert "lh/nightly" not in json.dumps(changes)  # no switch to flip
    assert body["writes"] == 3  # issue factory, weekly epic, brand sweep


def test_switching_on_what_merges_without_a_person_is_refused_and_off_is_a_brake(api, credential, github):
    github.get("/repos/o/ij/actions/variables").respond(200, json=variables_of({"CONTENT_AUTOMERGE_ENABLED": "false"}))
    on = preview(api, repo="o/ij", switch="CONTENT_AUTOMERGE_ENABLED", target="on")
    assert on["changes"][0]["action"] == "refused" and on["writes"] == 0
    assert "merges without a person" in on["changes"][0]["why"]
    github.get("/repos/o/lh/actions/variables").respond(200, json=variables_of(LH))
    off = preview(api, repo="o/lh", switch="AUTO_MERGE_ENABLED", target="off")
    assert off["changes"][0]["action"] == "update" and off["changes"][0]["hold"]["name"] == "HUB_ORIGINATION_HOLD"


def test_a_preview_without_a_credential_cannot_read_what_it_would_change(api, config, github):
    body = preview(api, repo="o/lh", switch="CONTENT_FACTORY_ENABLED", target="off")
    assert body["changes"][0]["action"] == "unreadable" and body["writes"] == 0
    assert body["credential"]["set"] is False


def test_a_preview_names_what_it_cannot_do(api, credential, github):
    for body, message in (
        ({"repo": "o/elsewhere", "target": "on"}, "not one of the outlets"),
        ({"repo": "o/lh", "switch": "NOPE_ENABLED", "target": "on"}, "has no switch NOPE_ENABLED"),
        ({"repo": "o/lh", "target": "sideways"}, "target"),
    ):
        refused = api.post("/api/v2/switches/preview/", body, format="json")
        assert refused.status_code == 422 and message in json.dumps(refused.json()), refused.json()


# ── apply ───────────────────────────────────────────────────────────────────


def test_apply_needs_a_confirmation_a_reason_and_a_credential(api, config, github, django_capture_on_commit_callbacks):
    planned = preview(api, repo="o/lh", switch="WEEKLY_EPIC_ENABLED", target="on")
    flip = {"repo": "o/lh", "switch": "WEEKLY_EPIC_ENABLED", "target": "on", "digest": planned["digest"]}
    for body, message in (
        ({**flip, "reason": "why not", "confirm": False}, "only when confirmed"),
        ({**flip, "reason": "why not"}, "confirm"),
        ({**flip, "confirm": True}, "reason"),
        ({**flip, "reason": "   ", "confirm": True}, "reason"),
        ({**flip, "reason": "why not", "confirm": True}, "no credential"),
    ):
        refused = apply(api, django_capture_on_commit_callbacks, **body)
        assert refused.status_code == 422 and message in json.dumps(refused.json()), refused.json()
    assert not Job.objects.exists() and all(c.request.method == "GET" for c in github.calls)


def test_apply_is_refused_when_the_switches_changed_since_the_preview(
    api, credential, github, django_capture_on_commit_callbacks
):
    planned = preview(api, repo="o/lh", switch="WEEKLY_EPIC_ENABLED", target="on")
    github.get("/repos/o/lh/actions/variables").respond(200, json=variables_of({**LH, "WEEKLY_EPIC_ENABLED": "false"}))
    stale = apply(
        api,
        django_capture_on_commit_callbacks,
        repo="o/lh",
        switch="WEEKLY_EPIC_ENABLED",
        target="on",
        reason="start the epic",
        confirm=True,
        digest=planned["digest"],
    )
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "switches.changed"
    assert not Job.objects.exists()


def test_apply_with_nothing_to_write_is_refused(api, credential, github, django_capture_on_commit_callbacks):
    planned = preview(api, repo="o/lh", switch="CONTENT_FACTORY_ENABLED", target="on")
    body = {"repo": "o/lh", "switch": "CONTENT_FACTORY_ENABLED", "target": "on", "reason": "x", "confirm": True}
    refused = apply(api, django_capture_on_commit_callbacks, **body, digest=planned["digest"])
    assert refused.status_code == 422 and "nothing to write" in refused.json()["error"]["message"]


def test_an_applied_flip_sets_reads_back_and_is_recorded(api, credential, github, django_capture_on_commit_callbacks):
    planned = preview(api, repo="o/lh", target="off", reason="pause lifehacker")
    assert {c["name"] for c in planned["changes"] if c["action"] == "update"} == {
        "CONTENT_FACTORY_ENABLED",
        "AUTO_MERGE_ENABLED",
    }
    updated = github.patch("/repos/o/lh/actions/variables/CONTENT_FACTORY_ENABLED").respond(204)
    missing = github.patch("/repos/o/lh/actions/variables/AUTO_MERGE_ENABLED").respond(
        404, json={"message": "Not Found"}
    )
    created = github.post("/repos/o/lh/actions/variables").respond(201)
    for name in ("CONTENT_FACTORY_ENABLED", "AUTO_MERGE_ENABLED"):
        github.get(f"/repos/o/lh/actions/variables/{name}").respond(200, json={"name": name, "value": "false"})
    answer = apply(
        api,
        django_capture_on_commit_callbacks,
        repo="o/lh",
        target="off",
        reason="pause lifehacker",
        confirm=True,
        digest=planned["digest"],
    )
    assert answer.status_code == 202, answer.json()
    job = Job.objects.get(public_id=answer.json()["job"]["id"])
    assert job.kind == "switches" and job.status == Job.Status.SUCCEEDED, (job.error, list(job.lines.values("text")))
    assert job.created_by.username == "manager" and job.params["reason"] == "pause lifehacker"
    assert json.loads(updated.calls.last.request.content) == {"name": "CONTENT_FACTORY_ENABLED", "value": "false"}
    assert missing.called and json.loads(created.calls.last.request.content) == {
        "name": "AUTO_MERGE_ENABLED",
        "value": "false",
    }
    event = OutboxEvent.objects.get(type="content.switches.flipped")
    check_data(event.type, event.version, event.data)
    assert event.subject == "repo:o/lh" and event.data["by"] == "manager" and event.data["scope"] == "outlet"
    assert event.data["job"] == str(job.public_id) and event.data["reason"] == "pause lifehacker"
    assert {(c["name"], c["old"], c["new"], c["result"], c["verified"]) for c in event.data["changes"]} == {
        ("CONTENT_FACTORY_ENABLED", "true", "false", "updated", True),
        ("AUTO_MERGE_ENABLED", "true", "false", "created", True),
    }
    assert TOKEN not in json.dumps(event.data) and TOKEN not in " ".join(job.lines.values_list("text", flat=True))
    assert any("record the flip there" in line for line in job.lines.values_list("text", flat=True))


def test_a_write_that_did_not_hold_fails_the_job_and_is_still_recorded(
    api, credential, github, django_capture_on_commit_callbacks
):
    planned = preview(api, repo="o/lh", switch="WEEKLY_EPIC_ENABLED", target="on")
    github.patch("/repos/o/lh/actions/variables/WEEKLY_EPIC_ENABLED").respond(404)
    github.post("/repos/o/lh/actions/variables").respond(403, json={"message": "Resource not accessible"})
    github.get("/repos/o/lh/actions/variables/WEEKLY_EPIC_ENABLED").respond(404)
    answer = apply(
        api,
        django_capture_on_commit_callbacks,
        repo="o/lh",
        switch="WEEKLY_EPIC_ENABLED",
        target="on",
        reason="start the epic",
        confirm=True,
        digest=planned["digest"],
    )
    job = Job.objects.get(public_id=answer.json()["job"]["id"])
    assert job.status == Job.Status.FAILED and "did not hold: WEEKLY_EPIC_ENABLED" in job.error
    [change] = OutboxEvent.objects.get(type="content.switches.flipped").data["changes"]
    assert change["result"] == "failed" and change["verified"] is False and "HTTP 403" in change["error"]
    assert change["old"] is None
