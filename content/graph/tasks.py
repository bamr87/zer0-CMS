"""Celery tasks for the graph: the nightly behavioural-edge build."""

from celery import shared_task

from .behavioural import build_viewed_together


@shared_task(name="graph.tasks.build_viewed_together")
def nightly_viewed_together(days: int = 30, min_count: int = 2) -> int:
    return build_viewed_together(days=days, min_count=min_count)
