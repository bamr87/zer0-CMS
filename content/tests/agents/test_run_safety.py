"""Agent runs end, once, and only spend where they may (W1-9): run_agent has default time limits, a redelivered run
that is already running fails instead of calling the model again, a sweep fails runs no worker will finish so what
they were filling settles, and a tool-using agent's provider row is honoured — disabled is 409, a spent budget 429."""

from datetime import timedelta
from decimal import Decimal

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone
from rest_framework.test import APIClient

from agents.llm import Completion, FakeLLM, RecordedLLM, use_llm
from agents.models import AgentDefinition, AgentRun, AgentStep
from agents.runner import execute, start_run
from agents.tasks import run_agent, settle_stale_runs
from ai import providers
from ai.models import Brief, ProviderConfig

from ..conftest import make_article


class WorkerDied(BaseException):
    """What a worker killed mid-call looks like to the run: nothing below it catches this."""


@pytest.mark.django_db
def test_run_agent_stops_at_its_default_limits():
    assert run_agent.soft_time_limit == settings.AGENT_RUN_SOFT_SECONDS
    assert run_agent.time_limit == settings.AGENT_RUN_SOFT_SECONDS + 30


@pytest.mark.django_db
def test_a_run_past_its_soft_limit_ends_failed(agent, article):
    with use_llm(FakeLLM([SoftTimeLimitExceeded()])):
        run = execute(start_run(agent("seo"), trigger="manual", target=article, enqueue=False))
    assert run.status == AgentRun.FAILED and "SoftTimeLimitExceeded" in run.error


@pytest.mark.django_db
def test_a_redelivered_running_run_ends_failed_without_calling_the_model_again(agent, article):
    run = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    with use_llm(FakeLLM([WorkerDied(), Completion(text="never asked")])) as fake:
        with pytest.raises(WorkerDied):
            run_agent(run.pk)  # the first delivery: the worker dies inside the model call, the task is never acked
        run.refresh_from_db()
        assert run.status == AgentRun.RUNNING and len(fake.calls) == 1
        assert run_agent(run.pk) == AgentRun.FAILED  # acks_late hands the task to another worker
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and run.error.startswith("worker lost")
    assert len(fake.calls) == 1  # no second model call, no second bill
    assert run_agent(run.pk) == AgentRun.FAILED  # and a final run stays as it ended


@pytest.mark.django_db
def test_the_sweep_fails_runs_no_worker_will_finish_and_their_brief_settles(agent, article, editor):
    assistant = AgentDefinition.objects.get(slug="assistant")
    two_hours_ago = timezone.now() - timedelta(hours=2)
    queued = start_run(assistant, trigger="rest", input={"kind": "brief"}, user=editor, enqueue=False)
    brief = Brief.objects.create(owner=editor, prompt="cats", status=Brief.GENERATING, run=queued)
    running = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    fresh = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    AgentRun.objects.filter(pk=queued.pk).update(created_at=two_hours_ago)
    AgentRun.objects.filter(pk=running.pk).update(status=AgentRun.RUNNING, started_at=two_hours_ago)

    assert settle_stale_runs() == 2
    queued.refresh_from_db(), running.refresh_from_db(), fresh.refresh_from_db(), brief.refresh_from_db()
    assert queued.status == AgentRun.FAILED and queued.error.startswith("stale: queued")
    assert running.status == AgentRun.FAILED and running.error.startswith("worker lost")
    assert fresh.status == AgentRun.QUEUED
    assert brief.status == Brief.FAILED and brief.error == queued.error  # run_finished settled it
    assert settle_stale_runs() == 0


@pytest.mark.django_db
def test_the_sweep_runs_on_beat():
    entries = [e for e in settings.CELERY_BEAT_SCHEDULE.values() if e["task"] == "agents.tasks.settle_stale_runs"]
    assert len(entries) == 1 and entries[0]["schedule"] < settings.AGENT_RUN_STALE_SECONDS


# ── the provider row a tool-using agent spends through ───────────────────────


@pytest.fixture
def anthropic(settings):
    """Agents on LLM_BACKEND=anthropic, its adapter a scripted fake: nothing reaches a model."""
    settings.LLM_BACKEND = "anthropic"
    with providers.override(FakeLLM([Completion(text="done")]), "anthropic") as fake:
        yield fake


@pytest.fixture
def api(editor):
    client = APIClient()
    client.force_authenticate(editor)
    return client


def spend(slug: str, usd: str) -> None:
    earlier = AgentRun.objects.create(agent=AgentDefinition.objects.get(slug="seo"), trigger="rest", llm_backend=slug)
    AgentStep.objects.create(run=earlier, idx=0, kind=AgentStep.LLM, name="m", cost_usd=Decimal(usd))


@pytest.mark.django_db
def test_a_disabled_provider_refuses_a_non_eval_agent_run_with_409(anthropic, api, agent, article):
    ProviderConfig.objects.filter(slug="anthropic").update(enabled=False)
    before = AgentRun.objects.count()
    response = api.post("/api/v2/agent-runs/", {"agent": "seo", "page_id": article.pk}, format="json")
    assert response.status_code == 409, response.content
    assert response.json()["error"]["code"] == "resource.conflict" and "disabled" in response.json()["error"]["message"]
    assert AgentRun.objects.count() == before  # refused before anything was queued
    # A run that reached the worker another way (an event, a workflow) is refused there, before any model call.
    run = execute(start_run(agent("seo"), trigger="event", target=article, enqueue=False))
    assert run.status == AgentRun.REFUSED and run.error == "the anthropic provider is disabled"
    assert anthropic.calls == []


@pytest.mark.django_db
def test_a_spent_budget_refuses_a_non_eval_agent_run_with_429(anthropic, api, agent, article):
    ProviderConfig.objects.filter(slug="anthropic").update(monthly_budget_usd=Decimal("1"))
    spend("anthropic", "1")
    response = api.post("/api/v2/agent-runs/", {"agent": "seo", "page_id": article.pk}, format="json")
    assert response.status_code == 429, response.content
    assert response.json()["error"]["code"] == "budget.exceeded"
    run = execute(start_run(agent("seo"), trigger="workflow", target=article, enqueue=False))
    assert run.status == AgentRun.REFUSED and "budget" in run.error
    assert anthropic.calls == []


@pytest.mark.django_db
def test_an_agent_inside_its_budget_runs(anthropic, api, article, django_capture_on_commit_callbacks):
    ProviderConfig.objects.filter(slug="anthropic").update(monthly_budget_usd=Decimal("5"))
    spend("anthropic", "1")
    with django_capture_on_commit_callbacks(execute=True):
        response = api.post("/api/v2/agent-runs/", {"agent": "seo", "page_id": article.pk}, format="json")
    assert response.status_code == 201, response.content
    run = AgentRun.objects.get(public_id=response.json()["id"])
    assert run.status == AgentRun.SUCCEEDED, run.error
    assert len(anthropic.calls) == 1


@pytest.mark.django_db
def test_an_eval_run_still_replays_its_recording(settings, agent, site_root):
    settings.LLM_BACKEND = "anthropic"
    ProviderConfig.objects.filter(slug="anthropic").update(enabled=False)
    page = make_article(
        site_root,
        "How we back up the drsai site",
        body=[{"type": "markdown", "value": "We copy the whole site to a second disk every night."}],
    )
    with providers.override(RecordedLLM(), "anthropic"):
        run = execute(
            start_run(agent("seo"), trigger="eval", target=page, input={"scenario": "meta-for-article"}, enqueue=False)
        )
        refused = execute(
            start_run(agent("seo"), trigger="rest", target=page, input={"scenario": "meta-for-article"}, enqueue=False)
        )
    assert run.status == AgentRun.SUCCEEDED, run.error
    assert run.llm_backend == "recorded"
    assert refused.status == AgentRun.REFUSED


@pytest.mark.django_db
def test_a_fake_or_recorded_backend_spends_nothing_and_is_never_checked(settings, agent, article):
    settings.LLM_BACKEND = "fake"
    ProviderConfig.objects.filter(slug__in=("recorded", "fake")).update(enabled=False)
    with providers.override(FakeLLM([Completion(text="done")]), "fake"):
        run = execute(start_run(agent("seo"), trigger="manual", target=article, enqueue=False))
    assert run.status == AgentRun.SUCCEEDED, run.error
