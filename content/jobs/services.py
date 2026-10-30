"""Starting, running and cancelling jobs (jobs/models.py).

An app registers what a kind of job does:

    @jobs.services.handler("sync", exclusive=True)
    def sync(job, ctx): ...          # ctx.log(), ctx.artifact(), ctx.check(); returns the result dict

`start` makes the row and queues it after the transaction commits; the worker
(`execute`, run by jobs/tasks.py) marks it running, calls the handler and
records how it ended. A handler raises `Failed` to end the job with a reason it
has already logged, and calls `ctx.check()` between steps, which raises
`Cancelled` once someone has asked the job to stop. Exclusive kinds run one at
a time per site: starting one while another exclusive job of the site is queued
or running is a conflict (`Busy`), because a sync and a write-back of one
checkout would race on the same files.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from .models import Job, JobArtifact, JobLine

log = logging.getLogger("jobs")


class Failed(Exception):
    """The job ends as failed with this reason."""


class Cancelled(Exception):
    """Someone asked the job to stop."""


class Busy(Exception):
    """An exclusive job of this kind is already queued or running for the site."""


class NotCancellable(Exception):
    """The job has already ended."""


@dataclass(frozen=True)
class Handler:
    kind: str
    run: Callable
    exclusive: bool


HANDLERS: dict[str, Handler] = {}


def handler(kind: str, *, exclusive: bool = False):
    def register(function):
        HANDLERS[kind] = Handler(kind, function, exclusive)
        return function

    return register


class Context:
    """What a handler writes through: its log, its artifacts, the cancel check."""

    def __init__(self, job: Job):
        self.job = job
        self._next = (JobLine.objects.filter(job=job).aggregate(n=Max("idx"))["n"] or -1) + 1

    def log(self, text: str, level: str = "info") -> None:
        JobLine.objects.create(job=self.job, idx=self._next, level=level, text=str(text))
        self._next += 1

    def artifact(self, name: str, content: str, media_type: str = "text/plain") -> None:
        JobArtifact.objects.update_or_create(
            job=self.job, name=name, defaults={"content": content, "media_type": media_type}
        )

    def check(self) -> None:
        if Job.objects.filter(pk=self.job.pk, cancel_requested=True).exists():
            raise Cancelled


def start(kind: str, *, user=None, site=None, params: dict | None = None, enqueue: bool = True) -> Job:
    """A queued job; it runs on the worker once the caller's transaction commits
    (`enqueue=False`: the caller runs it with `execute`, as a command does)."""
    if kind not in HANDLERS:
        raise KeyError(f"no job handler for {kind!r}")
    with transaction.atomic():
        if HANDLERS[kind].exclusive and site is not None:
            # Lock the site's row, so two requests cannot both see "nothing running".
            type(site).objects.select_for_update().filter(pk=site.pk).first()
            exclusive = [k for k, h in HANDLERS.items() if h.exclusive]
            active = [Job.Status.QUEUED, Job.Status.RUNNING]
            busy = Job.objects.filter(site=site, kind__in=exclusive, status__in=active).first()
            if busy is not None:
                raise Busy(f"a {busy.kind} job is already {busy.status} for this site")
        job = Job.objects.create(kind=kind, site=site, created_by=user, params=params or {})
    if enqueue:
        from .tasks import run_job

        transaction.on_commit(lambda: run_job.delay(job.pk))
    return job


def cancel(job: Job) -> Job:
    """Cancel a queued job at once; ask a running one to stop."""
    with transaction.atomic():
        job = Job.objects.select_for_update().get(pk=job.pk)
        if job.is_final:
            raise NotCancellable(f"the job has already {job.status}")
        if job.status == Job.Status.QUEUED:
            job.status, job.finished_at = Job.Status.CANCELLED, timezone.now()
        job.cancel_requested = True
        job.save(update_fields=["status", "finished_at", "cancel_requested"])
    return job


def execute(job_id: int) -> Job | None:
    """Run a queued job to its end (the worker's half)."""
    with transaction.atomic():
        job = Job.objects.select_for_update().filter(pk=job_id).first()
        if job is None or job.status != Job.Status.QUEUED:
            return job  # cancelled before it started, or already taken
        job.status, job.started_at = Job.Status.RUNNING, timezone.now()
        job.save(update_fields=["status", "started_at"])
    ctx = Context(job)
    try:
        ctx.check()
        job.result = HANDLERS[job.kind].run(job, ctx) or {}
        job.status = Job.Status.SUCCEEDED
    except Cancelled:
        ctx.log("Cancelled.", "warning")
        job.status = Job.Status.CANCELLED
    except Failed as e:
        job.status, job.error = Job.Status.FAILED, str(e)
    except Exception as e:  # noqa: BLE001 — any crash ends the job as failed, with the reason in its log
        log.exception("job %s (%s) crashed", job.public_id, job.kind)
        job.status, job.error = Job.Status.FAILED, f"{type(e).__name__}: {e}"
        ctx.log(job.error, "error")
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "result", "error", "finished_at"])
    return job
