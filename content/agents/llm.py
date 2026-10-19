"""One way to call a model, three backends (ADR 0001).

`complete()` takes a model id, a system prompt, provider-neutral messages and
tool specs, and returns a `Completion` — text, tool calls, tokens and cost.
The runner never sees a provider SDK.

- `recorded` (the test default) replays files under `LLM_RECORDINGS_DIR`:
  `<agent>/<scenario>/<step>.json`. A recording is keyed by *where* it is in a
  run rather than by a hash of the prompt, because prompts carry database ids
  that differ between SQLite and Postgres; instead each recording stores the
  digest of the system prompt and tool list it was made with, and replaying it
  against a changed prompt fails loudly — a changed prompt needs a new
  recording, which is the point of having them. Tool-call arguments may use
  `{{target.id}}` or `{{results.N.path.to.value}}` placeholders, filled from the
  run, so a recording does not hard-code an id either.
- `fake` replays a list given in code (unit tests).
- `litellm` routes to any provider. It is imported lazily and is not a pinned
  dependency: installing it is a deployment decision, not a test requirement.

Tests never reach a live model (AGENTS.md).
"""

import contextlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from django.conf import settings

from cms.models import stable_hash


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class Completion:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: Decimal = Decimal("0")
    model: str = ""

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


class RecordingMissing(LookupError):
    pass


class RecordingStale(LookupError):
    pass


def prompt_digest(system: str, tools: list[dict]) -> str:
    return stable_hash({"system": system, "tools": sorted(t["name"] for t in tools)})[:16]


def _completion(data: dict, model: str) -> Completion:
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


PLACEHOLDER = re.compile(r"\{\{\s*([a-zA-Z0-9_.]+)\s*\}\}")


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


class RecordedLLM:
    name = "recorded"

    def __init__(self, directory=None):
        self.directory = Path(directory or settings.LLM_RECORDINGS_DIR)

    def path(self, agent: str, scenario: str, step: int) -> Path:
        return self.directory / agent / scenario / f"{step:02d}.json"

    def complete(self, *, model, system, messages, tools, metadata=None) -> Completion:
        meta = metadata or {}
        path = self.path(meta.get("agent", "unknown"), meta.get("scenario", "default"), int(meta.get("step", 0)))
        if not path.is_file():
            raise RecordingMissing(
                f"no recording at {path}: record this step with a live backend (LLM_BACKEND=litellm "
                f"ZER0_LLM_RECORD=1) or write it by hand — see agents/README.md § Recordings"
            )
        recording = json.loads(path.read_text(encoding="utf-8"))
        digest = prompt_digest(system, tools)
        if recording.get("prompt_digest") not in (None, digest):
            raise RecordingStale(
                f"{path} was recorded against prompt {recording['prompt_digest']}, the run now sends {digest}: "
                "the system prompt or the tool list changed, so the recording must be redone"
            )
        response = fill(recording["response"], meta.get("context", {}))
        return _completion(response, model)


class FakeLLM:
    """Scripted completions, for unit tests: each `complete()` pops the next."""

    name = "fake"

    def __init__(self, script):
        self.script = list(script)
        self.calls: list[dict] = []

    def complete(self, *, model, system, messages, tools, metadata=None) -> Completion:
        self.calls.append(
            {"model": model, "system": system, "messages": messages, "tools": tools, "metadata": metadata}
        )
        if not self.script:
            return Completion(text="", model=model)
        nxt = self.script.pop(0)
        if callable(nxt):
            nxt = nxt(self.calls[-1])
        return (
            nxt if isinstance(nxt, Completion) else _completion(fill(nxt, (metadata or {}).get("context", {})), model)
        )


class LiteLLMClient:
    name = "litellm"

    def complete(self, *, model, system, messages, tools, metadata=None) -> Completion:
        import litellm  # noqa: PLC0415 — optional, deployment-time dependency

        wire = [{"role": "system", "content": system}] + [self._message(m) for m in messages]
        functions = [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
            }
            for t in tools
        ]
        response = litellm.completion(model=model, messages=wire, tools=functions or None)
        choice = response.choices[0].message
        calls = [
            ToolCall(id=c.id, name=c.function.name, arguments=json.loads(c.function.arguments or "{}"))
            for c in (choice.tool_calls or [])
        ]
        usage = getattr(response, "usage", None)
        try:
            cost = Decimal(str(litellm.completion_cost(completion_response=response)))
        except Exception:  # noqa: BLE001 — an unpriced model costs "unknown", recorded as 0, never a failed run
            cost = Decimal("0")
        return Completion(
            text=choice.content or "",
            tool_calls=calls,
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            cost_usd=cost,
            model=model,
        )

    @staticmethod
    def _message(m: dict) -> dict:
        if m["role"] == "tool":
            return {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
        if m.get("tool_calls"):
            return {
                "role": "assistant",
                "content": m.get("content") or "",
                "tool_calls": [
                    {
                        "id": c["id"],
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["arguments"])},
                    }
                    for c in m["tool_calls"]
                ],
            }
        return {"role": m["role"], "content": m["content"]}


class RecordingLLM:
    """Wraps a live backend and writes what it returns as recordings
    (`ZER0_LLM_RECORD=1`). Replace hard-coded ids in the written tool-call
    arguments with `{{target.id}}` / `{{results.N…}}` before committing them."""

    name = "recording"

    def __init__(self, inner, directory=None):
        self.inner = inner
        self.recorded = RecordedLLM(directory)

    def complete(self, *, model, system, messages, tools, metadata=None) -> Completion:
        meta = metadata or {}
        result = self.inner.complete(model=model, system=system, messages=messages, tools=tools, metadata=metadata)
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
        path.write_text(
            json.dumps({"prompt_digest": prompt_digest(system, tools), "response": response}, indent=2) + "\n",
            encoding="utf-8",
        )
        return result


_override = None


@contextlib.contextmanager
def use_llm(client):
    """Run the block with `client` as the backend (tests)."""
    global _override
    previous, _override = _override, client
    try:
        yield client
    finally:
        _override = previous


def get_llm():
    if _override is not None:
        return _override
    backend = settings.LLM_BACKEND
    if backend == "recorded":
        return RecordedLLM()
    if backend == "litellm":
        return RecordingLLM(LiteLLMClient()) if settings.LLM_RECORD else LiteLLMClient()
    if backend == "fake":
        return FakeLLM([])
    raise ValueError(f"unknown LLM_BACKEND {backend!r} (recorded | fake | litellm)")
