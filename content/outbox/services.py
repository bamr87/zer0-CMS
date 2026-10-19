"""`emit()`: write an event into the outbox, inside the caller's transaction.

`emit` refuses to run outside a transaction. That is the whole guarantee of an
outbox — the event and the change it describes commit together — so a call
that could commit the one without the other is a bug to surface, not to paper
over. Every request is atomic (`ATOMIC_REQUESTS`), and management commands
and tasks that write wrap their own work in `transaction.atomic()`.
"""

from django.conf import settings
from django.db import connection
from django.utils import timezone

from agents.tracing import current_trace_id

from .models import OutboxEvent
from .schemas import check_data


class OutboxError(RuntimeError):
    pass


def emit(event_type: str, data: dict, subject: str = "", version: int = 1) -> OutboxEvent:
    if not connection.in_atomic_block:
        raise OutboxError(f"emit({event_type!r}) must run inside the transaction that made the change")
    check_data(event_type, version, data)
    return OutboxEvent.objects.create(
        type=event_type,
        version=version,
        source=settings.EVENTS_SOURCE,
        subject=subject,
        time=timezone.now(),
        data=data,
        trace_id=current_trace_id() or "",
    )
