"""The outbox desk's own rows: what people asked the platform to do with the outbox harness (outboxdesk/README.md).

| Model         | What |
|---------------|------|
| `SentHandoff` | A handoff a person sent onto the belt as the editor station: who, when, and the message's id and trace — and the desk's permissions, which no model's add/change/delete would name |
| `Trial`       | An arena trial a person started from a task card: the card, the lag, where it stands, and its scored result |
| `ClaimCheck`  | A claim desk check a person started from claims and a source timeline: the verdicts, and — once a person gives the truth — the resolutions calibration is computed from |

The belt itself is not here. Its files — the stations' outboxes and inboxes, `ledger.jsonl`, `dead_letter.jsonl` —
are the record, written by senders and the relay and read through the library (ADR 0007); a table that mirrored
them would be a second ledger. The arenas a trial or a check runs in are directories under `OUTBOX_OUT_DIR`, and
these rows keep what the library returned from them.
"""

import uuid

from django.conf import settings
from django.db import models

USER = settings.AUTH_USER_MODEL


class Status(models.TextChoices):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


FINAL = (Status.SUCCEEDED, Status.FAILED)


class SentHandoff(models.Model):
    public_id = models.UUIDField(unique=True, help_text="The handoff's id on the belt.")
    kind = models.CharField(max_length=20)
    subject = models.CharField(max_length=255)
    trace = models.CharField(max_length=32, db_index=True)
    sent_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="sent_handoffs")
    sent_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-sent_at"]
        default_permissions = ()
        permissions = [
            ("view_belt", "Can read the outbox belt"),
            ("send_handoff", "Can send a handoff as the editor station"),
            ("deliver_belt", "Can run the belt's relay now"),
        ]

    def __str__(self):
        return f"{self.kind} {self.public_id}"


class Run(models.Model):
    """What a trial and a check share: who asked, where it stands, and the directory it ran in."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    requested_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.QUEUED, db_index=True)
    error = models.TextField(blank=True)
    run_dir = models.CharField(max_length=255, blank=True, help_text="Under OUTBOX_OUT_DIR.")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["-created_at"]


class Trial(Run):
    task = models.JSONField(help_text="The task card, as the harness reads one (tasks/*.json).")
    lag_b = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Overrides the card's lag_b.")
    result = models.JSONField(null=True, blank=True, help_text="score_trial's answer at close.")

    class Meta(Run.Meta):
        pass

    def __str__(self):
        return f"trial {self.task.get('id', '?')} ({self.status})"


class ClaimCheck(Run):
    title = models.CharField(max_length=255, blank=True)
    author = models.CharField(max_length=120, blank=True, help_text="Whose draft the claims are, for calibration.")
    page = models.ForeignKey("wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    claims = models.JSONField()
    timeline = models.JSONField()
    closes_at_tick = models.PositiveSmallIntegerField(default=8)
    lag_b = models.PositiveSmallIntegerField(default=2)
    report = models.JSONField(null=True, blank=True, help_text="check_claims's answer: pass, and a verdict per claim.")
    passed = models.BooleanField(null=True, blank=True)
    truth = models.JSONField(null=True, blank=True, help_text="Claim id → the answer the truth turned out to be.")
    resolution_status = models.CharField(max_length=16, choices=Status.choices, null=True, blank=True)
    resolution_error = models.TextField(blank=True)
    resolutions = models.JSONField(null=True, blank=True, help_text="resolve's answer per claim: Brier scores.")
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta(Run.Meta):
        pass

    def __str__(self):
        return f"claim check {self.title or self.public_id} ({self.status})"
