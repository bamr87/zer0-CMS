"""Celery task: the worker side of `runner.start_run`."""

from celery import shared_task

from .models import AgentRun
from .runner import execute


@shared_task(name="agents.tasks.run_agent")
def run_agent(run_id: int) -> str:
    run = AgentRun.objects.select_related("agent", "revision").get(pk=run_id)
    return execute(run).status
