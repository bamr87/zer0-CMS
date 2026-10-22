"""The contract every model provider implements, and the shapes it speaks.

A provider takes a model id, a system prompt, provider-neutral messages and
tool specs, and returns a `Completion` — text, tool calls, tokens, cost. The
messages are the agent runner's own shape (agents/runner.py):

    {"role": "user" | "assistant", "content": "…"}
    {"role": "assistant", "content": "…", "tool_calls": [{"id", "name", "arguments"}]}
    {"role": "tool", "tool_call_id": "…", "name": "…", "content": "<json>"}

`complete` is the one method an adapter must write. `stream` yields text as it
arrives (one chunk unless the adapter can do better), `structured` is a
completion whose JSON is parsed and validated against a JSON Schema with
`jsonschema` here, whatever the vendor promised, `list_models` returns the
catalog `ModelEntry` is synced from, and `health` is a one-word completion.
Each adapter declares what it can do in `capabilities`, the `extra` options
it reads in `options` (a row's `extra` is validated against them — nothing
else reaches the adapter), and the vendor prefixes a LiteLLM-style model id
may carry (`anthropic/claude-sonnet-5-5` is `claude-sonnet-5-5` here).

An environment credential is the deployment's: it is never sent to a base URL
a provider row chose — such a row needs its own credential.

Vendor SDKs are imported inside each adapter's methods, never at module
level, so none of them is needed to import, configure or test the platform.
"""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, ClassVar

from jsonschema import Draft202012Validator, validators
from referencing import Registry
from referencing.exceptions import Unresolvable

# What an adapter can declare: plain completions, streaming, native structured
# output, the runner's tool calls, a live model catalog, embeddings.
CAPABILITIES = ("complete", "stream", "structured", "tools", "models", "embed")
FENCED = re.compile(r"^```[\w-]*\s*\n?(.*?)\n?```$", re.DOTALL)
EFFORT = {"enum": ["low", "medium", "high", "xhigh", "max"]}
CLIENT_OPTIONS = {
    "max_retries": {"type": "integer", "minimum": 0, "maximum": 10},
    "timeout": {"type": "number", "exclusiveMinimum": 0, "maximum": 3600},
}


class ProviderError(Exception):
    """A provider could not answer: unreachable, refused, rate limited, or it
    returned something unusable. `retryable` says whether trying again may help."""

    def __init__(self, message: str, *, provider: str = "", retryable: bool = False):
        super().__init__(message)
        self.provider = provider
        self.retryable = retryable


class NotConfigured(ProviderError):
    """The adapter's SDK is not installed, or it has no credential."""


class InvalidOutput(ProviderError):
    """Structured output that is not JSON, or does not match its schema."""


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
    data: Any = None
    stop_reason: str = ""

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out


@dataclass(frozen=True)
class ModelInfo:
    """One model a provider runs, as the catalog stores it."""

    id: str
    display_name: str = ""
    capabilities: dict = field(default_factory=dict)
    input_usd_per_mtok: Decimal | None = None
    output_usd_per_mtok: Decimal | None = None


@dataclass
class Settings:
    """What a `ProviderConfig` row (or nothing but the environment) says about
    one provider. `prices` maps a model id to (input, output) dollars per
    million tokens, from the catalog."""

    slug: str
    credential: str = ""
    base_url: str = ""
    organization: str = ""
    project: str = ""
    default_model: str = ""
    extra: dict = field(default_factory=dict)
    prices: dict = field(default_factory=dict)


class Provider:
    slug: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    capabilities: ClassVar[frozenset[str]] = frozenset({"complete", "stream"})
    # Environment variables consulted for a credential when the row has none, first match wins.
    credential_env: ClassVar[tuple[str, ...]] = ()
    default_model: ClassVar[str] = ""
    # The models known to work, for when the vendor cannot be asked.
    static_models: ClassVar[tuple[ModelInfo, ...]] = ()
    # The `extra` keys this adapter reads, as JSON Schema properties.
    options: ClassVar[dict] = {}
    # Vendor prefixes a LiteLLM-style model id may carry (`anthropic/…`), stripped by `model_for`.
    model_prefixes: ClassVar[tuple[str, ...]] = ()

    def __init__(self, *, settings: Settings | None = None):
        self.settings = settings or Settings(slug=self.slug)

    @property
    def name(self) -> str:
        """What a run records as its backend (`AgentRun.llm_backend`)."""
        return self.slug

    @classmethod
    def options_schema(cls) -> dict:
        return {"type": "object", "properties": cls.options, "additionalProperties": False}

    # ── configuration ──────────────────────────────────────────────────────
    def credential(self) -> str:
        """The row's credential; else, unless the row chose its own base URL, the environment's."""
        if self.settings.credential:
            return self.settings.credential
        if self.settings.base_url:
            return ""
        return next((os.environ[name] for name in self.credential_env if os.environ.get(name)), "")

    def credential_source(self) -> str:
        """`database`, the environment variable it came from, or ''."""
        if self.settings.credential:
            return "database"
        if self.settings.base_url:
            return ""
        return next((name for name in self.credential_env if os.environ.get(name)), "")

    def model_for(self, requested: str = "") -> str:
        model = requested or self.settings.default_model or self.default_model
        vendor, _, bare = model.partition("/")
        return bare if bare and vendor in self.model_prefixes else model

    def cost(self, model: str, tokens_in: int, tokens_out: int) -> Decimal:
        """Dollars for a call, from the catalog's prices or the static list; 0 when unpriced."""
        price = self.settings.prices.get(model)
        if price is None:
            known = next((m for m in self.static_models if m.id == model), None)
            price = (known.input_usd_per_mtok, known.output_usd_per_mtok) if known else (None, None)
        rate_in, rate_out = (Decimal(str(p)) if p is not None else Decimal("0") for p in price)
        return (rate_in * tokens_in + rate_out * tokens_out) / Decimal(1_000_000)

    # ── the contract ───────────────────────────────────────────────────────
    def complete(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None) -> Completion:
        raise NotImplementedError

    def stream(self, **request) -> Iterator[str]:
        yield self.complete(**request).text

    def structured(self, *, schema: dict, **request) -> Completion:
        completion = self.complete(schema=schema, **request)
        completion.data = validate(
            completion.data if completion.data is not None else parse_json(completion.text), schema
        )
        return completion

    def list_models(self) -> list[ModelInfo]:
        return list(self.static_models)

    def health(self) -> dict:
        started = time.monotonic()
        completion = self.complete(
            model=self.model_for(),
            system="Reply with the single word OK.",
            messages=[{"role": "user", "content": "Health check."}],
            params={"max_tokens": 16},
        )
        return {
            "ok": True,
            "model": completion.model,
            "reply": completion.text.strip()[:80],
            "latency_ms": int((time.monotonic() - started) * 1000),
            "tokens": completion.tokens,
            "cost_usd": str(completion.cost_usd),
        }

    def embed(self, texts: list[str], *, model: str = "") -> list[list[float]]:
        raise ProviderError(f"{self.slug} does not embed text", provider=self.slug)


# ── structured output ──────────────────────────────────────────────────────


def parse_json(text: str):
    """JSON from a model's text, tolerating the code fence some models add."""
    candidate = (text or "").strip()
    fenced = FENCED.match(candidate)
    if fenced:
        candidate = fenced.group(1)
    try:
        return json.loads(candidate)
    except ValueError as e:
        raise InvalidOutput(f"the model did not return JSON: {e}") from e


def validate(data, schema: dict):
    """`data`, if it matches `schema` (the draft the schema names, else 2020-12).
    The validator gets an empty registry, so a `$ref` outside the schema is an
    error here rather than a request the worker makes."""
    cls = validators.validator_for(schema, default=Draft202012Validator)
    try:
        errors = sorted(cls(schema, registry=Registry()).iter_errors(data), key=lambda e: list(e.path))
    except Unresolvable as e:
        raise InvalidOutput(f"the schema refers to {e} outside itself") from e
    if errors:
        where = "/".join(str(p) for p in errors[0].path) or "(root)"
        raise InvalidOutput(f"the result does not match its schema at {where}: {errors[0].message}")
    return data


# ── wire helpers shared by the OpenAI-format adapters (openai, litellm) ────
# Vendors allow [a-zA-Z0-9_-] in a function name; the registry's names have dots.


def wire_name(name: str) -> str:
    return name.replace(".", "__")


def tool_name(wire: str) -> str:
    return wire.replace("__", ".")


def openai_messages(system: str, messages: list[dict]) -> list[dict]:
    wire = [{"role": "system", "content": system}] if system else []
    for m in messages:
        if m["role"] == "tool":
            wire.append({"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]})
        elif m.get("tool_calls"):
            calls = [
                {
                    "id": c["id"],
                    "type": "function",
                    "function": {"name": wire_name(c["name"]), "arguments": json.dumps(c["arguments"])},
                }
                for c in m["tool_calls"]
            ]
            wire.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
        else:
            wire.append({"role": m["role"], "content": m["content"]})
    return wire


def openai_tools(tools) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": wire_name(t["name"]),
                "description": t["description"],
                "parameters": t["input_schema"],
            },
        }
        for t in tools
    ]


def openai_tool_calls(calls) -> list[ToolCall]:
    return [
        ToolCall(id=c.id, name=tool_name(c.function.name), arguments=json.loads(c.function.arguments or "{}"))
        for c in calls or []
    ]


def openai_response_format(schema: dict) -> dict:
    return {"type": "json_schema", "json_schema": {"name": "result", "schema": schema}}
