"""`OutboxEvent` (what this plane announced) and `ProcessedEvent` (what it has
already consumed, so a redelivered event is handled once).

An event row is a CloudEvents 1.0 envelope stored as columns; `envelope()`
rebuilds the JSON a consumer reads. Rows are never updated except to record a
delivery attempt, and never deleted by the relay.
"""

import uuid

from django.conf import settings
from django.db import models


class OutboxEvent(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    type = models.CharField(max_length=120, db_index=True)
    version = models.PositiveSmallIntegerField(default=1)
    source = models.CharField(max_length=120)
    subject = models.CharField(max_length=255, blank=True)
    time = models.DateTimeField()
    data = models.JSONField()
    trace_id = models.CharField(max_length=32, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    dispatched_at = models.DateTimeField(null=True, blank=True, db_index=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)

    class Meta:
        ordering = ["created_at", "id"]
        indexes = [models.Index(fields=["dispatched_at", "created_at"])]

    def __str__(self):
        return f"{self.type} {self.id}"

    def envelope(self) -> dict:
        env = {
            "specversion": "1.0",
            "id": str(self.id),
            "source": self.source,
            "type": self.type,
            "time": self.time.isoformat().replace("+00:00", "Z"),
            "datacontenttype": "application/json",
            "dataschema": f"{settings.EVENTS_SCHEMA_BASE_URI}{self.type}.v{self.version}.json",
            "data": self.data,
        }
        if self.subject:
            env["subject"] = self.subject
        if self.trace_id:
            # The CloudEvents distributed-tracing extension carries a W3C
            # traceparent; the span id is not tracked across planes, only the trace.
            env["traceparent"] = f"00-{self.trace_id}-{'0' * 15}1-01"
        return env


class ProcessedEvent(models.Model):
    """One row per (event, consumer) this plane has handled."""

    event_id = models.UUIDField()
    consumer = models.CharField(max_length=120)
    type = models.CharField(max_length=120)
    processed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event_id", "consumer"], name="processed_once_per_consumer")]
