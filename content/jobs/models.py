"""`Job`, `JobLine`, `JobArtifact`: background work a person starts and follows
— a site's sync, its write-back, its doctor, and later its render, deploy and
reports (PLAN G4, TARGET.md § Sites — Manage).

A job runs on Celery (jobs/tasks.py) through the handler its `kind` names
(jobs/services.py). Its log is `JobLine` rows, written as the work goes, which
`/api/v2/jobs/<id>/stream/` sends as server-sent events the way an agent run's
steps are sent; what it leaves behind (a findings file, a report) is a
`JobArtifact`. Cancelling is cooperative: a queued job is cancelled at once, a
running one is asked to stop and stops at its handler's next check.

One scope: `Job.objects.visible_to(user)` — a person sees the jobs they started
and the jobs of every site they may manage (sites/access.py).
"""

import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q


class JobQuerySet(models.QuerySet):
    def visible_to(self, user):
        if user is None or not user.is_authenticated:
            return self.none()
        if user.is_superuser:
            return self
        from sites.access import manageable_sites

        return self.filter(Q(created_by=user) | Q(site__in=manageable_sites(user)))


class Job(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        CANCELLED = "cancelled"

    FINAL = (Status.SUCCEEDED, Status.FAILED, Status.CANCELLED)

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    kind = models.CharField(max_length=40, db_index=True, help_text="The handler that runs it: sync, export, doctor, …")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.QUEUED, db_index=True)
    params = models.JSONField(default=dict, blank=True)
    site = models.ForeignKey("wagtailcore.Site", null=True, blank=True, on_delete=models.CASCADE, related_name="jobs")
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    cancel_requested = models.BooleanField(default=False)
    result = models.JSONField(default=dict, blank=True, help_text="What the handler reports when it ends.")
    error = models.TextField(blank=True)

    objects = JobQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["site", "kind", "status"])]

    def __str__(self):
        return f"{self.kind} {self.public_id} ({self.status})"

    @property
    def is_final(self) -> bool:
        return self.status in self.FINAL


class JobLine(models.Model):
    """One line of a job's log, numbered from 0."""

    LEVELS = [("info", "info"), ("warning", "warning"), ("error", "error")]

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="lines")
    idx = models.PositiveIntegerField()
    at = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=8, choices=LEVELS, default="info")
    text = models.TextField()

    class Meta:
        ordering = ["idx"]
        constraints = [models.UniqueConstraint(fields=["job", "idx"], name="one_line_per_job_idx")]


class JobArtifact(models.Model):
    """A file a job leaves behind, served at `/api/v2/jobs/<id>/artifacts/<name>/`."""

    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="artifacts")
    name = models.CharField(max_length=120)
    media_type = models.CharField(max_length=80, default="text/plain")
    content = models.TextField()

    class Meta:
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["job", "name"], name="one_artifact_per_job_name")]
