"""Citation tracking: a tracked question is asked of every engine — each a provider of the AI layer, asked through
the bundled citation probe in a run of its own — and each answer is recorded with whether it cites the domain, at
what position, and over time (share of voice per engine and by week). Celery beat asks the due questions again,
once each. Every engine here is a scripted provider: the answers are recordings, nothing reaches a model."""

from datetime import timedelta

from django.utils import timezone

from agents.models import AgentRun
from ai import providers
from ai.providers.fake import FakeProvider
from ai.services import stable_id
from aieo import services, tasks
from aieo.models import Audit, CitationCheck, CitationQuery

from .conftest import answer


def probe(sources, text="Use a host that keeps nightly copies."):
    return answer({"answer": text, "sources": [{"url": url, "title": url} for url in sources]})


def test_every_engine_is_asked_and_each_answer_records_whether_it_cites_the_domain(alice, fake, worker):
    query = CitationQuery.objects.create(
        owner=alice, prompt="How should a small site back up?", domain="backups.example.com", engines=["fake", "openai"]
    )
    fake.script = [probe(["https://other.example.org/a", "https://www.backups.example.com/guide"])]
    with providers.override(FakeProvider([probe(["https://other.example.org/a"])]), "openai") as openai:
        checks = worker(services.check_citations, query, user=alice)
    assert [c.engine for c in checks] == ["fake", "openai"]
    by_engine = {c.engine: c for c in CitationCheck.objects.all()}
    hit, miss = by_engine["fake"], by_engine["openai"]
    assert hit.status == miss.status == CitationCheck.READY
    assert hit.cited and hit.position == 2 and hit.cited_urls == ["https://www.backups.example.com/guide"]
    assert miss.cited is False and miss.position is None and miss.answer
    assert "How should a small site back up?" in openai.calls[0]["messages"][0]["content"]
    assert fake.calls[0]["schema"]["required"] == ["answer", "sources"]
    query.refresh_from_db()
    assert query.last_checked_at and query.next_check_at > timezone.now() + timedelta(days=6)

    share = services.share_of_voice(alice)
    assert {row["engine"]: (row["checks"], row["cited"], row["rate"]) for row in share["engines"]} == {
        "fake": (1, 1, 1.0),
        "openai": (1, 0, 0.0),
    }
    assert len(share["weeks"]) == 2 and {row["engine"] for row in share["weeks"]} == {"fake", "openai"}


def test_an_answer_that_names_the_domain_cites_it_and_a_lookalike_does_not():
    assert services.cited("example.com", "See example.com for more.", [])["cited"]
    assert services.cited("https://example.com/", "", [{"url": "https://docs.example.com/x"}])["position"] == 1
    assert not services.cited("example.com", "Try notexample.com or example.com.au.", [{"url": "https://example.co"}])[
        "cited"
    ]


def test_beat_asks_the_due_questions_once_and_a_failed_run_fails_its_check(alice, fake, worker):
    due = CitationQuery.objects.create(
        owner=alice, prompt="Best backup host?", domain="backups.example.com", next_check_at=timezone.now()
    )
    later = CitationQuery.objects.create(
        owner=alice,
        prompt="Backup costs?",
        domain="backups.example.com",
        next_check_at=timezone.now() + timedelta(days=3),
    )
    fake.script = [Exception("rate limited")]
    assert worker(tasks.check_citations) == 1
    assert worker(tasks.check_citations) == 0  # claimed: never asked twice
    check = CitationCheck.objects.get(query=due)
    assert check.status == CitationCheck.FAILED and "rate limited" in check.error
    assert not CitationCheck.objects.filter(query=later).exists()
    assert check.run.trigger == "schedule" and check.run.started_by == alice


def test_the_api_tracks_a_question_checks_it_and_reports_share_of_voice(
    alice, bob, api, fake, worker, django_capture_on_commit_callbacks
):
    made = api(alice).post(
        "/api/v2/aieo/citations/queries/",
        {"prompt": "Who explains backups best?", "domain": "https://www.Backups.Example.com/", "engines": ["fake"]},
        format="json",
    )
    assert made.status_code == 201, made.content
    assert made.json()["domain"] == "backups.example.com" and made.json()["next_check_at"]
    query = made.json()["id"]
    assert api(bob).get(f"/api/v2/aieo/citations/queries/{query}/").status_code == 404
    bad = api(alice).post(
        "/api/v2/aieo/citations/queries/", {"prompt": "x", "domain": "y.com", "engines": ["nope"]}, format="json"
    )
    assert bad.status_code == 422 and "nope" in str(bad.json())
    fake.script = [probe(["https://backups.example.com/"])]
    with django_capture_on_commit_callbacks(execute=True):
        checked = api(alice).post(f"/api/v2/aieo/citations/queries/{query}/check/")
    assert checked.status_code == 202 and checked.json()["checks"][0]["engine"] == "fake"
    listed = api(alice).get("/api/v2/aieo/citations/checks/", {"query": query}).json()["results"]
    assert listed[0]["cited"] is True and listed[0]["position"] == 1
    assert api(bob).get("/api/v2/aieo/citations/checks/").json()["results"] == []
    share = api(alice).get("/api/v2/aieo/citations/share/").json()
    assert share["engines"] == [{"engine": "fake", "checks": 1, "cited": 1, "rate": 1.0}]
    latest = api(alice).get(f"/api/v2/aieo/citations/queries/{query}/").json()["latest"]
    assert latest["fake"]["cited"] is True


def test_a_run_made_by_hand_never_overwrites_a_check_or_redoes_an_audit(
    alice, bob, api, fake, worker, page, django_capture_on_commit_callbacks
):
    """The generic agent-runs endpoint takes any input from someone who edits a page, so an AIEO run kind there could
    name any check or audit its starter sees. Only the run a check or an audit was started with records its answer:
    a crafted run is refused before a model is asked, and the finished check and audit are left as they were."""
    query = CitationQuery.objects.create(
        owner=bob, prompt="Who explains backups?", domain="backups.example.com", visibility="shared"
    )
    fake.script = [probe(["https://other.example.org/"])]
    [check] = worker(services.check_citations, query, user=bob)
    audit = worker(services.audit, alice, kind="text", content="# Backups\n\nCopies.", method="heuristic")
    before = Audit.objects.values().get(pk=audit.pk)
    probe_id = str(stable_id("bundled-assistant", services.PROBE))
    fake.script = [probe(["https://backups.example.com/"], text="alice's answer")]
    crafted = (
        {"kind": "aieo.citation", "check": str(check.public_id), "assistant": probe_id},
        {"kind": "aieo.audit", "audit": str(audit.public_id)},  # her own audit, by a run it was not started with
    )
    for data in crafted:
        with django_capture_on_commit_callbacks(execute=True):
            made = api(alice).post(
                "/api/v2/agent-runs/", {"agent": "assistant", "page_id": page.pk, "input": data}, format="json"
            )
        assert made.status_code == 201, made.content
        run = AgentRun.objects.get(public_id=made.json()["id"])
        assert run.status == AgentRun.FAILED and "PermissionError" in run.error
    check.refresh_from_db()
    assert check.status == CitationCheck.READY and check.cited is False and check.answer != "alice's answer"
    assert Audit.objects.values().get(pk=audit.pk) == before and len(fake.calls) == 1  # no model was asked again


def test_a_model_chosen_for_the_probe_goes_to_its_own_provider_only(alice, fake, worker):
    """The probe's model is its provider's: an engine it is not is asked with that engine's own default model, never
    with a model it does not have."""
    from ai.models import Assistant, ModelEntry, ProviderConfig

    config, _ = ProviderConfig.objects.get_or_create(slug="fake")
    entry = ModelEntry.objects.create(provider=config, model_id="fake-only-model")
    Assistant.objects.filter(public_id=stable_id("bundled-assistant", services.PROBE)).update(model=entry)
    query = CitationQuery.objects.create(
        owner=alice, prompt="Who explains backups?", domain="backups.example.com", engines=["fake", "openai"]
    )
    fake.script = [probe([])]
    with providers.override(FakeProvider([probe([])]), "openai") as openai:
        worker(services.check_citations, query, user=alice)
    assert fake.calls[0]["model"] == "fake-only-model" and openai.calls[0]["model"] == "fake-1"


def test_a_question_is_scheduled_whenever_it_is_switched_to_a_schedule_and_only_its_keepers_move_it(
    alice, bob, api, fake, worker, django_capture_on_commit_callbacks
):
    """A question made to be asked on request and given an interval later — or switched back on — joins beat's queue;
    switched off, it leaves it. Asking it now is open to everyone it is shared with, but only its owner's asking (or
    beat's) moves its schedule."""
    made = (
        api(alice)
        .post(
            "/api/v2/aieo/citations/queries/",
            {
                "prompt": "Who explains backups?",
                "domain": "backups.example.com",
                "interval_days": 0,
                "visibility": "shared",
            },
            format="json",
        )
        .json()
    )
    url = f"/api/v2/aieo/citations/queries/{made['id']}/"
    assert made["next_check_at"] is None
    assert api(alice).patch(url, {"interval_days": 7}, format="json").json()["next_check_at"]
    assert api(alice).patch(url, {"active": False}, format="json").json()["next_check_at"] is None
    scheduled = api(alice).patch(url, {"active": True}, format="json").json()
    assert scheduled["next_check_at"] and services.due_queries().filter(public_id=made["id"]).exists()
    fake.script = [probe([])]
    with django_capture_on_commit_callbacks(execute=True):
        assert api(bob).post(f"{url}check/").status_code == 202
    after = api(alice).get(url).json()
    assert (after["next_check_at"], after["last_checked_at"]) == (scheduled["next_check_at"], None)
