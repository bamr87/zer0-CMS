"""The automations' Celery tasks: a queued run executed in the worker (`execute_run`, queued when the firing commits),
and the schedules that came due, fired by Celery beat every minute (`tick`,
`CELERY_BEAT_SCHEDULE["automations-schedule"]`) — one dispatcher reading every automation's cron line with Celery's
own `crontab`, rather than a beat entry per automation kept in step with the rows (django-celery-beat's database
scheduler): no second scheduler to deploy, no copy of each schedule to keep in sync, and the beat's own clock. A run
may call a webhook or a mail provider that waits on someone else's server, so it runs on the `research` queue, whose
own worker does that kind of waiting (CELERY_TASK_ROUTES), and is stopped once it has taken two minutes (soft; the
hard limit is half a minute later) — after `services.RUN_SECONDS`, past which no action starts, so a run ends inside
its limit."""

from celery import shared_task

from . import services

LIMITS = {"soft_time_limit": 120, "time_limit": 150}


@shared_task(name="automations.tasks.execute_run", **LIMITS)
def execute_run(pk: int) -> str:
    run = services.execute(pk)
    return run.status if run is not None else "gone"


@shared_task(name="automations.tasks.tick")
def tick() -> int:
    return len(services.tick())
