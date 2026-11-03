"""The agent loop's model client: a thin front over the provider registry
(ai/providers/, ADR 0006 decision 7).

`get_llm(trigger)` returns the provider named by `settings.LLM_BACKEND` —
`recorded` (the test and CI default, replaying `agents/recordings/`), `fake`, or
any adapter the registry knows (`litellm`, `anthropic`, `openai`, `claude_code`);
with `ZER0_LLM_RECORD=1` a live provider's completions are also written as
recordings. A run that is not an eval spends through that provider, so its row
is honoured as the AI layer's runs honour theirs (`check_backend`, which is
`ai.services.check_provider`): disabled is refused (409), and so is a month's
budget already spent (429 `budget.exceeded`); a replay or a script spends
nothing and is not checked. `use_llm()` swaps the client for a block (tests).
The names below are the ones the runner and its tests have always used; the
classes behind them live in `ai/providers/`, the one place a provider SDK is
imported.

Tests never reach a live model (AGENTS.md).
"""

import contextlib

from django.conf import settings

from ai import providers
from ai.providers.base import Completion, ToolCall
from ai.providers.fake import FakeProvider as FakeLLM
from ai.providers.litellm import LiteLLMProvider as LiteLLMClient
from ai.providers.recorded import PLACEHOLDER, RecordingMissing, RecordingStale, fill, prompt_digest
from ai.providers.recorded import RecordedProvider as RecordedLLM
from ai.providers.recorded import Recorder as RecordingLLM

__all__ = [
    "PLACEHOLDER",
    "Completion",
    "FakeLLM",
    "LiteLLMClient",
    "RecordedLLM",
    "RecordingLLM",
    "RecordingMissing",
    "RecordingStale",
    "ToolCall",
    "check_backend",
    "fill",
    "get_llm",
    "prompt_digest",
    "use_llm",
]

_override = None
UNSPENT = ("recorded", "fake")  # backends that replay or script their answers: nothing is billed


@contextlib.contextmanager
def use_llm(client):
    """Run the block with `client` as the backend (tests)."""
    global _override
    previous, _override = _override, client
    try:
        yield client
    finally:
        _override = previous


def check_backend(trigger: str | None = None) -> str:
    """`settings.LLM_BACKEND`, if a run started by `trigger` may spend through it (raises `ApiError`: 409, 429)."""
    backend = settings.LLM_BACKEND
    if backend not in providers.available():
        raise ValueError(f"unknown LLM_BACKEND {backend!r} ({' | '.join(providers.available())})")
    if trigger != "eval" and backend not in UNSPENT:
        from ai.services import check_provider  # noqa: PLC0415 — ai.services imports the runner, which imports this

        check_provider(backend)
    return backend


def get_llm(trigger: str | None = None):
    """The tool-using agents' model client for a run started by `trigger`; anything but an eval is checked."""
    if _override is not None:
        return _override
    backend = check_backend(trigger)
    client = providers.get(backend)
    return RecordingLLM(client) if settings.LLM_RECORD and backend not in ("recorded", "fake") else client
