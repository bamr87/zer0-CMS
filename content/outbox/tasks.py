"""Celery tasks: the relay runs every few seconds from beat (settings)."""

from celery import shared_task

from .relay import relay_pending


@shared_task(name="outbox.tasks.relay_outbox")
def relay_outbox(batch: int = 100) -> int:
    return relay_pending(batch=batch)
