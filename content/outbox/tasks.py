"""Celery task form of the relay, for a deployment that prefers beat to the
`relay_outbox` process; compose runs the process."""

from celery import shared_task

from .relay import relay_pending


@shared_task(name="outbox.tasks.relay_outbox")
def relay_outbox(batch: int = 100) -> int:
    return relay_pending(batch=batch)
