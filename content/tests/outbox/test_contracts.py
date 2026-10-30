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


@pytest.mark.django_db
def test_runs_and_suggestions_are_announced_by_their_public_ids(article, agent):
    """P-D6: v2 names a run and a suggestion by the UUIDs every API gives, never their integer keys; an envelope
    already in a stream under v1 still validates."""
    from django.contrib.auth import get_user_model

    from agents.runner import _finish, start_run
    from suggestions.services import propose

    run = start_run(agent("seo"), trigger="manual", target=article, enqueue=False)
    seo = get_user_model().objects.get(username="agent:seo")
    made = propose(target=article, user=seo, run=run, op="meta", field="seo_title", payload={"value": "x"})
    _finish(run, "succeeded")
    proposed = OutboxEvent.objects.get(type="content.suggestion.created", subject=f"page:{article.pk}")
    completed = OutboxEvent.objects.get(type="agent.run.completed", subject=f"run:{run.public_id}")
    assert (proposed.version, completed.version) == (2, 2)
    assert proposed.data["suggestion_id"] == str(made.public_id) and proposed.data["run_id"] == str(run.public_id)
    assert completed.data["run_id"] == str(run.public_id) and completed.data["suggestions"] == 1
    for event in (proposed, completed):
        check_envelope(event.envelope())
    v1 = {**completed.envelope(), "dataschema": completed.envelope()["dataschema"].replace(".v2.", ".v1.")}
    with pytest.raises(EventSchemaError, match="run_id"):
        check_envelope(v1)  # v2's data is not v1's
    check_envelope({**v1, "data": {**v1["data"], "run_id": run.pk}})
