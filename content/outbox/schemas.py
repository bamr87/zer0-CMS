"""Loading and checking the shared event schemas in `schemas/events/`.

One validator per (type, version), cached. An event whose data does not match
its schema is refused at `emit()` — before it reaches the outbox — because a
malformed event in a stream is a bug in every consumer at once.
"""

import json
from functools import lru_cache
from pathlib import Path

from django.conf import settings
from jsonschema import Draft202012Validator, FormatChecker


class EventSchemaError(ValueError):
    pass


@lru_cache(maxsize=64)
def validator(name: str) -> Draft202012Validator:
    path = Path(settings.EVENTS_SCHEMA_DIR) / f"{name}.json"
    if not path.is_file():
        raise EventSchemaError(f"no schema {path.name} in {settings.EVENTS_SCHEMA_DIR}")
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def errors(name: str, instance) -> list[str]:
    return [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(root)'}: {e.message}"
        for e in sorted(validator(name).iter_errors(instance), key=lambda e: list(e.absolute_path))
    ]


def check_data(event_type: str, version: int, data: dict) -> None:
    problems = errors(f"{event_type}.v{version}", data)
    if problems:
        raise EventSchemaError(f"{event_type} v{version}: " + "; ".join(problems))


def check_envelope(envelope: dict) -> None:
    """The envelope and its data, the way a consumer on either plane checks it."""
    problems = errors("cloudevent.v1", envelope)
    if problems:
        raise EventSchemaError("envelope: " + "; ".join(problems))
    name = envelope["dataschema"].rsplit("/", 1)[-1].removesuffix(".json")
    problems = errors(name, envelope["data"])
    if problems:
        raise EventSchemaError(f"{name}: " + "; ".join(problems))
