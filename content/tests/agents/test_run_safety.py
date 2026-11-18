"""Agent runs execute once and always end (#62, W1-9): a worker claims a queued run in one conditional update, so a
duplicate or redelivered task never runs its handler or model loop a second time and never fails a run another worker
is running; run_agent has default time limits; and a sweep on beat fails the runs no worker will finish, so the brief or
reply each was filling settles."""

from datetime import datetime, timedelta

import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.conf import settings
from django.utils import timezone

from agents.handlers import reviews
from agents.llm import Completion, FakeLLM, use_llm
from agents.models import AgentDefinition, AgentRun, AgentStep
from agents.runner import execute, start_run
from agents.tasks import run_agent, settle_stale_runs
from ai.models import Brief
from outbox.models import OutboxEvent


class WorkerDied(BaseException):
    """What a worker killed mid-call looks like to the run: nothing below it catches this."""


def completed_events(run: AgentRun) -> int:
    return OutboxEvent.objects.filter(type="agent.run.completed", subject=f"run:{run.public_id}").count()


def past_the_stale_line() -> datetime:
    return timezone.now() - timedelta(seconds=settings.AGENT_RUN_STALE_SECONDS + 60)


@pytest.mark.django_db
def test_run_agent_stops_at_its_default_limits():
    assert run_agent.soft_time_limit == settings.AGENT_RUN_SOFT_SECONDS
    assert run_agent.time_limit == settings.AGENT_RUN_SOFT_SECONDS + 30
    # The stale line outlasts every hard limit, AIEO's own included, so it never fails a run a worker still holds.
    assert settings.AGENT_RUN_STALE_SECONDS > max(run_agent.time_limit, settings.AIEO_RUN_TIME_LIMIT + 30)


@pytest.mark.django_db
def test_a_run_past_its_soft_limit_ends_failed(agent, article):
    with use_llm(FakeLLM([SoftTimeLimitExceeded()])):
        run = execute(start_run(agent("seo"), trigger="manual", target=article, enqueue=False))
    assert run.status == AgentRun.FAILED and "SoftTimeLimitExceeded" in run.error


# ── the claim: one delivery runs a run ───────────────────────────────────────


@pytest.mark.django_db
def test_a_second_delivery_holding_a_stale_queued_copy_calls_no_model_and_adds_no_step(agent, article):
    run = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    first, second = AgentRun.objects.get(pk=run.pk), AgentRun.objects.get(pk=run.pk)  # both read it while it was queued
    with use_llm(FakeLLM([Completion(text="done"), Completion(text="billed twice")])) as fake:
        assert execute(first).status == AgentRun.SUCCEEDED
        steps = AgentStep.objects.filter(run=run).count()
        assert second.status == AgentRun.QUEUED  # its copy still says queued
        assert execute(second).status == AgentRun.SUCCEEDED  # the run as the first delivery left it
    assert len(fake.calls) == 1, "the duplicate called the model again"
    assert AgentStep.objects.filter(run=run).count() == steps
    run.refresh_from_db()
    assert run.output["text"] == "done" and completed_events(run) == 1


@pytest.mark.django_db
def test_a_second_delivery_never_calls_a_handler_again(agent, article, monkeypatch):
    calls = []
    monkeypatch.setattr(reviews, "a11y", lambda run, ctx: calls.append(run.pk) or {"comments": []})
    run = start_run(agent("a11y"), trigger="manual", target=article, enqueue=False)
    first, second = AgentRun.objects.get(pk=run.pk), AgentRun.objects.get(pk=run.pk)
    assert execute(first).status == AgentRun.SUCCEEDED
    assert execute(second).status == AgentRun.SUCCEEDED
    assert calls == [run.pk] and completed_events(run) == 1


@pytest.mark.django_db
def test_a_duplicate_delivery_of_a_run_another_worker_is_running_leaves_it_running(agent, article):
    run = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    duplicate = AgentRun.objects.get(pk=run.pk)  # the second delivery read the run while it was still queued
    seen = {}

    def meanwhile(call):
        # The duplicate arrives while the first worker waits on the model.
        seen["status"] = execute(duplicate).status
        seen["steps"] = AgentStep.objects.filter(run=run).count()
        return Completion(text="done")

    with use_llm(FakeLLM([meanwhile, Completion(text="billed twice")])) as fake:
        assert execute(run).status == AgentRun.SUCCEEDED, run.error
    assert seen == {"status": AgentRun.RUNNING, "steps": 0}  # left to the worker that claimed it, not failed
    assert len(fake.calls) == 1 and completed_events(run) == 1
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED and run.error == ""


@pytest.mark.django_db
def test_a_redelivered_run_is_left_to_its_worker_until_it_is_past_the_stale_line(agent, article):
    run = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    with use_llm(FakeLLM([WorkerDied(), Completion(text="never asked")])) as fake:
        with pytest.raises(WorkerDied):
            run_agent(run.pk)  # the first delivery: the worker dies inside the model call, the task is never acked
        run.refresh_from_db()
        assert run.status == AgentRun.RUNNING and len(fake.calls) == 1
        # Redelivered at once (a duplicate, or a worker that may still be alive): not this delivery's to run or fail.
        assert run_agent(run.pk) == AgentRun.RUNNING
        # Redelivered once it has been running longer than any run may: its worker is gone.
        AgentRun.objects.filter(pk=run.pk).update(started_at=past_the_stale_line())
        assert run_agent(run.pk) == AgentRun.FAILED
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and run.error.startswith("worker lost")
    assert len(fake.calls) == 1  # no second model call, no second bill
    assert run_agent(run.pk) == AgentRun.FAILED  # and a final run stays as it ended
    assert completed_events(run) == 1


# ── the sweep: runs no worker will finish ────────────────────────────────────


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
    assert completed_events(queued) == 1 and completed_events(running) == 1


@pytest.mark.django_db
def test_a_task_that_comes_after_the_sweep_failed_its_run_does_nothing(agent, article):
    run = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    AgentRun.objects.filter(pk=run.pk).update(created_at=past_the_stale_line())
    assert settle_stale_runs() == 1
    with use_llm(FakeLLM([Completion(text="too late")])) as fake:
        assert run_agent(run.pk) == AgentRun.FAILED
    assert fake.calls == [] and AgentStep.objects.filter(run=run).count() == 0


@pytest.mark.django_db
def test_the_sweep_runs_on_beat():
    entries = [e for e in settings.CELERY_BEAT_SCHEDULE.values() if e["task"] == "agents.tasks.settle_stale_runs"]
    assert len(entries) == 1 and entries[0]["schedule"] < settings.AGENT_RUN_STALE_SECONDS
