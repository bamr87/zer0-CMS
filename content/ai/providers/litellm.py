"""`litellm`: any other vendor, through LiteLLM — and the graph's embeddings.

Model ids are LiteLLM's (`anthropic/claude-sonnet-5-5`, `gemini/…`, `ollama/…`);
the vendor's key comes from the row's credential or LiteLLM's own environment
variables — except for a row with its own base URL, which must hold its key,
since LiteLLM would send the environment's there. LiteLLM has no single
catalog, so `list_models` offers the ids a person listed in the row's
`extra.models`, priced from LiteLLM's cost map. LiteLLM is imported lazily and
is not a platform requirement (installing it is a deployment decision:
`requirements-providers.txt`).
"""

from decimal import Decimal

from .base import (
    Completion,
    ModelInfo,
    NotConfigured,
    Provider,
    ProviderError,
    openai_messages,
    openai_response_format,
    openai_tool_calls,
    openai_tools,
)


def _litellm():
    try:
        import litellm  # noqa: PLC0415 — optional, deployment-time dependency
    except ImportError as e:
        raise NotConfigured("litellm is not installed: pip install -r requirements-providers.txt") from e
    return litellm


class LiteLLMProvider(Provider):
    slug = "litellm"
    display_name = "LiteLLM (any other vendor)"
    capabilities = frozenset({"complete", "stream", "structured", "tools", "models", "embed"})
    default_model = "anthropic/claude-sonnet-5-5"
    options = {"models": {"type": "array", "items": {"type": "string", "minLength": 1}}}

    def _request(self, model, system, messages, tools, schema, params) -> dict:
        if self.settings.base_url and not self.settings.credential:
            raise NotConfigured("a litellm row with its own base URL needs its own credential", provider=self.slug)
        params = params or {}
        kwargs = {"model": self.model_for(model), "messages": openai_messages(system, messages)}
        if tools:
            kwargs["tools"] = openai_tools(tools)
        if schema is not None:
            kwargs["response_format"] = openai_response_format(schema)
        for key in ("temperature", "top_p", "max_tokens"):
            if params.get(key) is not None:
                kwargs[key] = params[key]
        for key, value in (
            ("api_key", self.settings.credential),
            ("base_url", self.settings.base_url),
            ("organization", self.settings.organization),
        ):
            if value:
                kwargs[key] = value
        return kwargs

    def complete(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None) -> Completion:
        litellm = _litellm()
        kwargs = self._request(model, system, messages, tools, schema, params)
        try:
            response = litellm.completion(**kwargs)
        except Exception as e:  # noqa: BLE001 — LiteLLM maps every vendor's errors onto its own; all of them mean "no answer"
            raise ProviderError(f"{kwargs['model']}: {e}", provider=self.slug, retryable=True) from e
        choice = response.choices[0]
        usage = getattr(response, "usage", None)
        try:
            cost = Decimal(str(litellm.completion_cost(completion_response=response)))
        except Exception:  # noqa: BLE001 — an unpriced model costs "unknown", recorded as 0, never a failed run
            cost = Decimal("0")
        return Completion(
            text=choice.message.content or "",
            tool_calls=openai_tool_calls(choice.message.tool_calls),
            tokens_in=getattr(usage, "prompt_tokens", 0) or 0,
            tokens_out=getattr(usage, "completion_tokens", 0) or 0,
            cost_usd=cost,
            model=kwargs["model"],
            stop_reason=getattr(choice, "finish_reason", "") or "",
        )

    def stream(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None):
        kwargs = self._request(model, system, messages, tools, schema, params)
        for chunk in _litellm().completion(stream=True, **kwargs):
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def list_models(self) -> list[ModelInfo]:
        costs = getattr(_litellm(), "model_cost", {}) if self.settings.extra.get("models") else {}
        found = []
        for model_id in self.settings.extra.get("models", []):
            known = costs.get(model_id, {})
            found.append(
                ModelInfo(
                    model_id,
                    model_id,
                    {"context": known.get("max_input_tokens"), "tools": known.get("supports_function_calling")},
                    _per_mtok(known.get("input_cost_per_token")),
                    _per_mtok(known.get("output_cost_per_token")),
                )
            )
        return found

    def embed(self, texts: list[str], *, model: str = "") -> list[list[float]]:
        response = _litellm().embedding(model=model or self.model_for(), input=list(texts))
        return [[float(x) for x in item["embedding"]] for item in response.data]


def _per_mtok(per_token) -> Decimal | None:
    return None if per_token is None else Decimal(str(per_token)) * 1_000_000
