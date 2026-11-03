"""Celery tasks: the worker side of `runner.start_run`, and beat's sweep of the runs no worker will finish.

`run_agent` has default limits (AGENT_RUN_SOFT_SECONDS, the hard one 30 seconds later), so a hung provider call never
holds a worker for good; a caller may pass its own through `start_run(options=…)`.
"""

from celery import shared_task
from django.conf import settings

from .models import AgentRun
from .runner import execute, settle_stale


@shared_task(
    name="agents.tasks.run_agent",
    soft_time_limit=settings.AGENT_RUN_SOFT_SECONDS,
    time_limit=settings.AGENT_RUN_SOFT_SECONDS + 30,
)
def run_agent(run_id: int) -> str:
    run = AgentRun.objects.select_related("agent", "revision").get(pk=run_id)
    return execute(run).status


@shared_task(name="agents.tasks.settle_stale_runs")
def settle_stale_runs() -> int:
    return settle_stale()
