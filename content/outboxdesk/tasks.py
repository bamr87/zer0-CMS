"""The outbox desk's Celery tasks: the belt's relay — on Celery beat (`CELERY_BEAT_SCHEDULE["outbox-belt"]`) and on
a person's request — and the trials, claim checks and resolutions people start from the studio. Each runs the
harness in the worker, never in a request, under a time limit; a run's outcome is written to its row
(outboxdesk/services.py)."""

from celery import shared_task

from . import services

# An arena is a few hundred file writes; a card or a claim set big enough to run longer than this is stopped.
LIMITS = {"soft_time_limit": 300, "time_limit": 330}


@shared_task
def deliver_belt() -> int:
    """One relay pass; returns how many messages it delivered."""
    return len(services.deliver())


@shared_task(**LIMITS)
def run_trial(pk: int) -> str:
    trial = services.run_trial(pk)
    return trial.status if trial is not None else "taken"


@shared_task(**LIMITS)
def run_claim_check(pk: int) -> str:
    check = services.run_claim_check(pk)
    return check.status if check is not None else "taken"


@shared_task(**LIMITS)
def resolve_claim_check(pk: int) -> str:
    check = services.resolve_claim_check(pk)
    return check.resolution_status if check is not None else "taken"
