"""The provider registry: the platform's one way to reach a model.

Adapters are keyed by slug. The six built in are `claude_code`, `anthropic`,
`openai`, `litellm` (any other vendor), `recorded` and `fake` (tests);
`settings.AI_PROVIDERS` (slug → dotted path) is merged over them, so a
deployment adds a provider with one module and one setting, and disables a
built-in by mapping its slug to "". `get(slug)` builds an adapter from the
slug's `ProviderConfig` row (credential, base URL, default model, extras and
the catalog's prices), falling back to the environment when there is no row.
The default provider is the enabled row flagged default, else
`settings.AI_DEFAULT_PROVIDER`.

Nothing outside this package imports a vendor SDK (asserted by
tests/ai/test_providers.py); everything else asks the registry.
"""

import contextlib

from django.conf import settings
from django.utils.module_loading import import_string

from .base import Completion, ModelInfo, NotConfigured, Provider, ProviderError, SearchResult, Settings, ToolCall

BUILTIN = {
    "claude_code": "ai.providers.claude_code.ClaudeCodeProvider",
    "anthropic": "ai.providers.anthropic.AnthropicProvider",
    "openai": "ai.providers.openai.OpenAIProvider",
    "litellm": "ai.providers.litellm.LiteLLMProvider",
    "recorded": "ai.providers.recorded.RecordedProvider",
    "fake": "ai.providers.fake.FakeProvider",
}

__all__ = [
    "Completion",
    "ModelInfo",
    "NotConfigured",
    "Provider",
    "ProviderError",
    "SearchResult",
    "Settings",
    "ToolCall",
    "available",
    "default_slug",
    "get",
    "provider_class",
    "override",
]

_overrides: dict[str, Provider] = {}


def _paths() -> dict[str, str]:
    return {slug: path for slug, path in {**BUILTIN, **getattr(settings, "AI_PROVIDERS", {})}.items() if path}


def available() -> list[str]:
    return sorted(_paths())


def provider_class(slug: str) -> type[Provider]:
    path = _paths().get(slug)
    if path is None:
        raise ProviderError(f"unknown provider {slug!r}; known: {', '.join(available())}", provider=slug)
    return import_string(path)


def default_slug() -> str:
    from ai.models import ProviderConfig  # noqa: PLC0415 — the registry is imported before the app registry is ready

    row = ProviderConfig.objects.filter(is_default=True, enabled=True).first()
    return row.slug if row is not None else settings.AI_DEFAULT_PROVIDER


def load_settings(slug: str) -> Settings:
    from ai.models import ProviderConfig  # noqa: PLC0415

    row = ProviderConfig.objects.filter(slug=slug).first()
    return row.settings() if row is not None else Settings(slug=slug)


def get(slug: str | None = None, *, config: Settings | None = None) -> Provider:
    """The adapter for `slug` (the default provider when None), configured."""
    slug = slug or default_slug()
    if slug in _overrides:
        return _overrides[slug]
    return provider_class(slug)(settings=config or load_settings(slug))


@contextlib.contextmanager
def override(provider: Provider, slug: str | None = None):
    """Tests: make `get(slug)` return this instance (its own slug by default)."""
    key = slug or provider.slug
    previous = _overrides.get(key)
    _overrides[key] = provider
    try:
        yield provider
    finally:
        if previous is None:
            _overrides.pop(key, None)
        else:
            _overrides[key] = previous
