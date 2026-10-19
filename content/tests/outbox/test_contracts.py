"""The shared event contracts (schemas/events/): every example validates, and
every event this plane emits validates as the consumer on the other plane will
check it — envelope first, then data against the schema `dataschema` names."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from jsonschema import Draft202012Validator

from outbox.models import OutboxEvent
from outbox.schemas import EventSchemaError, check_envelope

SCHEMAS = Path(settings.EVENTS_SCHEMA_DIR)
TYPES = ["content.page.published", "content.suggestion.created", "agent.run.completed", "app.user.interaction"]


@pytest.mark.parametrize("path", sorted(SCHEMAS.glob("*.json")), ids=lambda p: p.name)
def test_every_schema_is_a_valid_2020_12_schema(path):
    Draft202012Validator.check_schema(json.loads(path.read_text()))


@pytest.mark.parametrize("event_type", TYPES)
def test_every_type_has_a_v1_schema_and_a_valid_example(event_type):
    assert (SCHEMAS / f"{event_type}.v1.json").is_file()
    check_envelope(json.loads((SCHEMAS / "examples" / f"{event_type}.json").read_text()))


def test_a_malformed_envelope_is_refused():
    envelope = json.loads((SCHEMAS / "examples" / "content.page.published.json").read_text())
    del envelope["data"]["content_hash"]
    with pytest.raises(EventSchemaError, match="content_hash"):
        check_envelope(envelope)


@pytest.mark.django_db
def test_events_this_plane_emits_pass_the_consumer_check(article, agent):
    from agents.runner import execute, start_run

    run = start_run(agent("brand"), trigger="manual", target=article, enqueue=False)
    execute(run)
    emitted = OutboxEvent.objects.filter(type__in=TYPES)
    assert {"content.page.published", "agent.run.completed"} <= set(emitted.values_list("type", flat=True))
    for event in emitted:
        check_envelope(event.envelope())
