"""Celery task: the worker side of `jobs.services.start`."""

from celery import shared_task

from .services import execute


@shared_task(name="jobs.tasks.run_job")
def run_job(job_id: int) -> str:
    job = execute(job_id)
    return job.status if job is not None else "missing"
