"""`/api/v2/outbox/trials/` and `claim-checks/` (outboxdesk/views.py): a trial runs the harness's arena on a task
card in the worker (202, then the row is read again) and keeps its scored result and the arena's ledger; a claim
check races two verifiers per claim and gives a verdict each, and once a person gives the truth the worker resolves
it into Brier scores that calibration averages per verifier and per author. Cards and claim sets are validated
before the worker sees them; the desk never touches a page. The harness's policy agents run offline."""

import copy

import pytest
from wagtail.models import Page

from outboxdesk.models import ClaimCheck, Trial

from .conftest import CARD, CLAIMS, TIMELINE

BASE = "/api/v2/outbox"


@pytest.mark.django_db
def test_runs_are_for_people_who_hold_the_models_permissions(api, ed, reader, nobody):
    for path in ("trials/", "claim-checks/", "claim-checks/calibration/"):
        assert api().get(f"{BASE}/{path}").status_code == 401
        assert api(nobody).get(f"{BASE}/{path}").status_code == 403
        assert api(reader).get(f"{BASE}/{path}").status_code == 200
    assert api(reader).post(f"{BASE}/trials/", {"task": CARD}, format="json").status_code == 403
    assert (
        api(reader).post(f"{BASE}/claim-checks/", {"claims": CLAIMS, "timeline": TIMELINE}, format="json").status_code
        == 403
    )
    assert not Trial.objects.exists() and not ClaimCheck.objects.exists()


@pytest.mark.django_db
def test_a_trial_runs_in_the_worker_and_keeps_its_scored_result_and_ledger(api, ed, worker, desk_dirs):
    started = worker(api(ed).post, f"{BASE}/trials/", {"task": CARD}, format="json", HTTP_IDEMPOTENCY_KEY="t-1")
    assert started.status_code == 202 and started.json()["status"] == "queued"
    trial = api(ed).get(f"{BASE}/trials/{started.json()['id']}/").json()
    assert trial["status"] == "succeeded" and trial["requested_by"] == "ed"
    result = trial["result"]
    assert (result["task_id"], result["resolved"], result["latest_env_seq"]) == ("T-stale-fact", True, 2)
    assert result["winner"]["answer"] == "green" and result["correct"] is True
    assert (desk_dirs / trial["run_dir"] / "result.json").is_file()
    ledger = trial["ledger"]
    assert ledger[0]["type"] == "task_open" and [r["tick"] for r in ledger if r.get("event") == "tick"] == list(
        range(9)
    )
    assert {r["from"] for r in ledger if r.get("type") == "claim"} == {"claimant-a", "claimant-b"}
    again = api(ed).post(f"{BASE}/trials/", {"task": CARD}, format="json", HTTP_IDEMPOTENCY_KEY="t-1")
    assert again.headers["Idempotent-Replayed"] == "true" and Trial.objects.count() == 1

    # The race widened: claimant-b reads too late, and the card's judge is left open.
    open_card = {**copy.deepcopy(CARD), "id": "T-open"}
    del open_card["expected_answer"]
    widened = worker(api(ed).post, f"{BASE}/trials/", {"task": open_card, "lag_b": 9}, format="json")
    row = Trial.objects.get(public_id=widened.json()["id"])
    assert (row.lag_b, row.result["resolved"], row.result["correct"]) == (9, False, None)
    assert "claimant-b" not in row.result["claims_per_agent"]
    listed = api(ed).get(f"{BASE}/trials/").json()
    assert [t["task"]["id"] for t in listed["results"]] == ["T-open", "T-stale-fact"]


@pytest.mark.django_db
def test_a_card_the_arena_could_not_read_is_refused_and_a_harness_failure_is_kept_on_the_row(
    api, ed, worker, monkeypatch
):
    def refused(task):
        response = api(ed).post(f"{BASE}/trials/", {"task": task}, format="json")
        assert response.status_code == 422
        return {d["field"] for d in response.json()["error"]["details"]}

    assert refused({k: v for k, v in CARD.items() if k != "question"}) == {"task.question"}
    assert refused({**CARD, "closes_at_tick": 0}) == {"task.closes_at_tick"}
    assert refused({**CARD, "env_schedule": [{"tick": 1, "fact": "no seq"}]}) == {"task.env_schedule.0.env_seq"}

    from outboxdesk import harness

    arena = harness.module("arena")
    monkeypatch.setattr(arena.Arena, "run", lambda self: (_ for _ in ()).throw(RuntimeError("the arena fell over")))
    started = worker(api(ed).post, f"{BASE}/trials/", {"task": CARD}, format="json")
    failed = api(ed).get(f"{BASE}/trials/{started.json()['id']}/").json()
    assert (
        failed["status"] == "failed"
        and failed["error"] == "RuntimeError: the arena fell over"
        and failed["result"] is None
    )


@pytest.mark.django_db
def test_a_claim_check_gives_a_verdict_per_claim_and_never_touches_the_page(api, ed, worker, article):
    before = Page.objects.get(pk=article.pk).latest_revision_id
    body = {"title": "Hydra explainer", "author": "rhea", "page": article.pk, "claims": CLAIMS, "timeline": TIMELINE}
    started = worker(api(ed).post, f"{BASE}/claim-checks/", body, format="json")
    assert started.status_code == 202 and started.json()["claim_count"] == 2
    check = api(ed).get(f"{BASE}/claim-checks/{started.json()['id']}/").json()
    assert (check["status"], check["passed"], check["page"]) == (
        "succeeded",
        False,
        {"id": article.pk, "title": "Nightly backups"},
    )
    verdicts = {v["claim_id"]: v for v in check["report"]["claims"]}
    assert check["report"]["pass"] is False
    assert (verdicts["hydra-status"]["verdict"], verdicts["hydra-status"]["reason"]) == ("block", "sources_disagree")
    assert verdicts["hydra-status"]["supported_answer"] == "green"
    assert (verdicts["hydra-region"]["verdict"], verdicts["hydra-region"]["reason"]) == ("pass", "sources_agree")
    assert all("arena" not in v for v in check["report"]["claims"])  # no server path in the API
    assert Page.objects.get(pk=article.pk).latest_revision_id == before


@pytest.mark.django_db
def test_a_claim_set_is_validated_before_the_worker_sees_it(api, ed):
    def refused(**body):
        response = api(ed).post(
            f"{BASE}/claim-checks/", {"claims": CLAIMS, "timeline": TIMELINE, **body}, format="json"
        )
        assert response.status_code == 422
        return {d["field"] for d in response.json()["error"]["details"]}

    assert refused(claims=[]) == {"claims"}
    assert refused(claims=[CLAIMS[0], CLAIMS[0]]) == {"claims"}
    assert refused(claims=[{**CLAIMS[0], "id": "../escape"}]) == {"claims.0.id"}  # a claim's id names a directory
    assert refused(claims=[CLAIMS[0], {**CLAIMS[1], "confidence": 2}]) == {"claims.1.confidence"}
    assert refused(timeline=[{"tick": -1, "source": "probe", "says": "x"}]) == {"timeline.0.tick"}
    assert refused(closes_at_tick=0) == {"closes_at_tick"}
    assert not ClaimCheck.objects.exists()


@pytest.mark.django_db
def test_a_resolved_check_scores_its_verifiers_and_its_author_and_calibration_averages_them(api, ed, worker):
    def check(author, truth):
        started = worker(
            api(ed).post,
            f"{BASE}/claim-checks/",
            {"author": author, "claims": CLAIMS, "timeline": TIMELINE},
            format="json",
        )
        url = f"{BASE}/claim-checks/{started.json()['id']}/"
        if truth is not None:
            assert worker(api(ed).post, f"{url}resolve/", {"truth": truth}, format="json").status_code == 202
        return api(ed).get(url).json()

    rhea = check("rhea", {"hydra-status": "green", "hydra-region": "eu-west"})
    assert rhea["resolution_status"] == "succeeded" and rhea["truth"] == {
        "hydra-status": "green",
        "hydra-region": "eu-west",
    }
    scored = {r["task_id"]: r for r in rhea["resolutions"]}
    assert scored["C-hydra-status"]["draft_correct"] is False and scored["C-hydra-status"]["draft_brier"] == 0.64
    assert scored["C-hydra-region"]["winner_correct"] is True and set(scored["C-hydra-region"]["brier"]) == {
        "claimant-a",
        "claimant-b",
    }
    check("edge", {"hydra-status": "amber", "hydra-region": "eu-west"})  # the same claim ids, another author
    check("unresolved", None)

    calibration = api(ed).get(f"{BASE}/claim-checks/calibration/").json()
    assert calibration["resolved"] == 4 and calibration["winner_accuracy"] == 0.75
    authors = {row["name"]: row for row in calibration["authors"]}
    assert authors["rhea"] == {"name": "rhea", "n": 2, "brier": 0.325} and authors["edge"]["n"] == 2
    assert [row["name"] for row in calibration["verifiers"]] == ["claimant-a", "claimant-b"]

    url = f"{BASE}/claim-checks/{rhea['id']}/resolve/"
    wrong = api(ed).post(url, {"truth": {"hydra-status": "green"}}, format="json")
    assert wrong.status_code == 422 and wrong.json()["error"]["details"][0]["message"] == "no truth for hydra-region"
    extra = api(ed).post(url, {"truth": {"hydra-status": "green", "hydra-region": "x", "other": 1}}, format="json")
    assert extra.status_code == 422


@pytest.mark.django_db
def test_a_check_is_resolved_only_after_it_has_run(api, ed, reader):
    started = api(ed).post(
        f"{BASE}/claim-checks/", {"claims": CLAIMS, "timeline": TIMELINE}, format="json"
    )  # not run: no worker
    url = f"{BASE}/claim-checks/{started.json()['id']}/resolve/"
    assert api(reader).post(url, {"truth": {}}, format="json").status_code == 403
    early = api(ed).post(url, {"truth": {"hydra-status": "green", "hydra-region": "eu-west"}}, format="json")
    assert early.status_code == 409 and early.json()["error"]["code"] == "claimcheck.not_checked"
