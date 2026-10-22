"""`recorded`: replay model responses from files — what CI and the evals run.

A recording lives at `<LLM_RECORDINGS_DIR>/<agent>/<scenario>/<step>.json` and
is keyed by *where* it is in a run rather than by a hash of the prompt, because
prompts carry database ids that differ between SQLite and Postgres. Each
recording stores the digest of the system prompt, the tool list (and the output
schema, when the call had one) it was made with, and replaying it against a
changed prompt fails loudly: a changed prompt needs a new recording, which is
the point of having them. Tool-call arguments may use `{{target.id}}`,
`{{results.N.path}}` or `{{input.key}}` placeholders, filled from the run, so a
recording does not hard-code an id either.

`Recorder` wraps a live provider and writes what it returns as recordings
(`ZER0_LLM_RECORD=1`); replace the ids in the written tool-call arguments with
placeholders before committing them (agents/README.md § Recordings).
"""

import json
import re
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from cms.models import stable_hash

from .base import Completion, Provider, ToolCall

PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


class RecordingMissing(LookupError):
    pass


class RecordingStale(LookupError):
    pass


def prompt_digest(system: str, tools: list[dict], schema: dict | None = None) -> str:
    payload = {"system": system, "tools": sorted(t["name"] for t in tools)}
    if schema is not None:
        payload["schema"] = schema
    return stable_hash(payload)[:16]


def completion_from(data: dict, model: str) -> Completion:
    return Completion(
        text=data.get("text", ""),
        tool_calls=[
            ToolCall(id=c.get("id") or f"call_{i}", name=c["name"], arguments=c.get("arguments", {}))
            for i, c in enumerate(data.get("tool_calls", []))
        ],
        tokens_in=int(data.get("tokens_in", 0)),
        tokens_out=int(data.get("tokens_out", 0)),
        cost_usd=Decimal(str(data.get("cost_usd", "0"))),
        model=data.get("model", model),
    )


def _lookup(context: dict, path: str):
    value = context
    for part in path.split("."):
        if isinstance(value, list):
            value = value[int(part)]
        elif isinstance(value, dict):
            value = value[part]
        else:
            raise KeyError(path)
    return value


def fill(value, context: dict):
    """Replace {{path}} placeholders; a string that is only a placeholder takes
    the value's own type (so `"{{target.id}}"` becomes an int)."""
    if isinstance(value, dict):
        return {k: fill(v, context) for k, v in value.items()}
    if isinstance(value, list):
        return [fill(v, context) for v in value]
    if isinstance(value, str):
        whole = PLACEHOLDER.fullmatch(value.strip())
        if whole:
            return _lookup(context, whole.group(1))
        return PLACEHOLDER.sub(lambda m: str(_lookup(context, m.group(1))), value)
    return value


class RecordedProvider(Provider):
    slug = "recorded"
    display_name = "Recorded (replays fixtures, for CI)"
    capabilities = frozenset({"complete", "stream", "structured", "tools"})
    default_model = "recorded"

    def __init__(self, directory=None, *, settings=None):
        super().__init__(settings=settings)
        self.directory = directory

    def path(self, agent: str, scenario: str, step: int) -> Path:
        return Path(self.directory or settings.LLM_RECORDINGS_DIR) / agent / scenario / f"{step:02d}.json"

    def complete(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None) -> Completion:
        meta = metadata or {}
        path = self.path(meta.get("agent", "unknown"), meta.get("scenario", "default"), int(meta.get("step", 0)))
        if not path.is_file():
            raise RecordingMissing(
                f"no recording at {path}: record this step with a live backend (LLM_BACKEND=litellm "
                f"ZER0_LLM_RECORD=1) or write it by hand — see agents/README.md § Recordings"
            )
        recording = json.loads(path.read_text(encoding="utf-8"))
        digest = prompt_digest(system, list(tools), schema)
        if recording.get("prompt_digest") not in (None, digest):
            raise RecordingStale(
                f"{path} was recorded against prompt {recording['prompt_digest']}, the run now sends {digest}: "
                "the system prompt or the tool list changed, so the recording must be redone"
            )
        return completion_from(fill(recording["response"], meta.get("context", {})), model)


class Recorder:
    """A live provider whose every completion is also written as a recording."""

    name = "recording"

    def __init__(self, inner, directory=None):
        self.inner = inner
        self.recorded = RecordedProvider(directory)

    def complete(self, *, model, system, messages, tools=(), metadata=None, **options) -> Completion:
        meta = metadata or {}
        result = self.inner.complete(
            model=model, system=system, messages=messages, tools=tools, metadata=metadata, **options
        )
        path = self.recorded.path(
            meta.get("agent", "unknown"), meta.get("scenario", "default"), int(meta.get("step", 0))
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        response = {
            "text": result.text,
            "tool_calls": [{"id": c.id, "name": c.name, "arguments": c.arguments} for c in result.tool_calls],
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "cost_usd": str(result.cost_usd),
            "model": result.model,
        }
        digest = prompt_digest(system, list(tools), options.get("schema"))
        path.write_text(json.dumps({"prompt_digest": digest, "response": response}, indent=2) + "\n", encoding="utf-8")
        return result
