"""Automations as a consumer of the platform's own events (outbox/consumers.py).

The relay writes this plane's events to its stream (`EVENTS_STREAM`, `zer0:content`); `manage.py consume_events --own
--group platform` reads them through a consumer group — the compose `events` service, beside distribution's drafts —
and `handle_envelope` runs this handler once per event (`ProcessedEvent`, consumer `automations`), in the transaction
that records it, so the runs an event fires commit with that record or not at all. Registration is a call, not an
import side effect: a test registers and removes it around the events it hands over, so no other consumer's test sees
it.
"""

from outbox.consumers import HANDLERS, handler

from . import services, spec

CONSUMER = "automations"


def on_event(envelope: dict) -> None:
    services.on_event(envelope)


def register() -> None:
    for event_type in spec.EVENTS:
        handler(event_type, consumer=CONSUMER)(on_event)


def unregister() -> None:
    for event_type in spec.EVENTS:
        HANDLERS.get(event_type, {}).pop(CONSUMER, None)
