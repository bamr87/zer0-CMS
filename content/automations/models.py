"""The automations tables (TARGET.md § Pipelines and workflows; PLAN G16).

| Model           | What |
|-----------------|------|
| `Automation`    | A trigger, a condition and ordered actions, owned by the person whose permissions its actions run with; paused when it is made (`enabled` is false), rate-limited per hour, with a secret that signs its webhooks |
| `AutomationRun` | One firing: the trigger's payload, the condition's verdict, each action's outcome (with the runs and rows it made), the timings and the error — every firing is one, a limited or a skipped one included |

An automation is an owned row with the AI layer's rules (`ai.models.Owned`): a UUID public id, owner, site,
visibility and `visible_to(user, site)`, the one place rows are scoped. Unlike an assistant, it acts — as its owner
— so only its owner (or a superuser) changes, enables, tests or exports its secret (`can_edit`); staff may pause one
(`can_pause`). Its trigger and actions are JSON validated against `spec.py`'s schemas, which is also how they export
and import as YAML. A run is seen by whoever sees its automation.
"""

import secrets
import uuid

from django.core.serializers.json import DjangoJSONEncoder
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from ai import crypto
from ai.models import Owned, is_staff

from . import spec


class Automation(Owned):
    STOP, CONTINUE = "stop", "continue"
    ON_ERROR = [(STOP, "Stop at the first action that fails"), (CONTINUE, "Record the failure and go on")]

    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    enabled = models.BooleanField(default=False, help_text="A new automation is paused until a person enables it.")
    trigger = models.JSONField(help_text="{kind: event|schedule|webhook|source|hook, …} (automations/spec.py).")
    condition = models.TextField(blank=True, help_text="A JMESPath expression over the payload; empty always runs.")
    actions = models.JSONField(default=list, blank=True, help_text="In order: [{kind, …}] (automations/spec.py).")
    on_error = models.CharField(max_length=8, choices=ON_ERROR, default=STOP)
    max_runs_per_hour = models.PositiveSmallIntegerField(
        default=60, validators=[MinValueValidator(1), MaxValueValidator(1000)], help_text="Further firings are limited."
    )
    secret_encrypted = models.TextField(blank=True, editable=False)
    scheduled_at = models.DateTimeField(
        null=True, blank=True, editable=False, help_text="A schedule's last tick (or when it was enabled)."
    )
    last_run = models.ForeignKey(
        "AutomationRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+", editable=False
    )

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name

    def clean(self):
        super().clean()
        spec.check(self.trigger, self.condition, self.actions)
        if self.owner_id is not None:
            spec.check_rows(self.trigger, self.actions, self.owner)

    def save(self, *args, **kwargs):
        """Every automation has a secret from the start, shown once (`new_secret`)."""
        if not self.secret_encrypted:
            self.rotate_secret()
        super().save(*args, **kwargs)

    def rotate_secret(self) -> str:
        self.new_secret = secrets.token_urlsafe(32)
        self.secret_encrypted = crypto.encrypt(self.new_secret)
        return self.new_secret

    def get_secret(self) -> str:
        """The secret, decrypted (ai/crypto.py's keys); ValueError when no key there reads it any more."""
        try:
            return crypto.decrypt(self.secret_encrypted)
        except crypto.InvalidToken as e:
            raise ValueError(f"the secret of automation {self.public_id} was encrypted with a key that is gone") from e

    def can_edit(self, user) -> bool:
        """Its actions run with its owner's permissions, so only its owner — or a superuser — changes it."""
        signed_in = getattr(user, "is_authenticated", False)
        return signed_in and (user.is_superuser or (self.owner_id is not None and self.owner_id == user.pk))

    def can_pause(self, user) -> bool:
        return self.can_edit(user) or is_staff(user)


class RunQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(automation__in=Automation.objects.visible_to(user, site))


class AutomationRun(models.Model):
    QUEUED, RUNNING, SUCCEEDED, FAILED, SKIPPED, LIMITED = (
        "queued",
        "running",
        "succeeded",
        "failed",
        "skipped",
        "limited",
    )
    STATUSES = [
        (QUEUED, "Queued"),
        (RUNNING, "Running"),
        (SUCCEEDED, "Succeeded"),
        (FAILED, "Failed"),
        (SKIPPED, "Skipped — the condition said no, or it was paused"),
        (LIMITED, "Limited — over its runs per hour"),
    ]
    FINAL = (SUCCEEDED, FAILED, SKIPPED, LIMITED)
    TRIGGERS = [(kind, kind) for kind in (*spec.TRIGGERS, "test")]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    automation = models.ForeignKey(Automation, on_delete=models.CASCADE, related_name="runs")
    trigger = models.CharField(max_length=12, choices=TRIGGERS)
    payload = models.JSONField(default=dict, blank=True, encoder=DjangoJSONEncoder)
    key = models.CharField(max_length=200, blank=True, help_text="What it fired for, once: an event, a source, a tick.")
    status = models.CharField(max_length=10, choices=STATUSES, default=QUEUED, db_index=True)
    matched = models.BooleanField(null=True, blank=True, help_text="The condition's verdict, once evaluated.")
    outcomes = models.JSONField(default=list, blank=True, encoder=DjangoJSONEncoder)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    objects = RunQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["automation", "key"], condition=~Q(key=""), name="automations_once_per_key")
        ]
        indexes = [models.Index(fields=["automation", "created_at"])]

    def __str__(self):
        return f"{self.automation} at {self.created_at:%Y-%m-%d %H:%M} ({self.status})"
