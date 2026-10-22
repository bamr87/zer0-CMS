"""`openai`: OpenAI chat completions — function calling for the runner's tools,
`response_format` with a JSON Schema for structured output (validated locally
like every provider's), the organization and project from the row. The SDK is
imported lazily (`requirements-providers.txt`).
"""

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


class OpenAIProvider(Provider):
    slug = "openai"
    display_name = "OpenAI"
    capabilities = frozenset({"complete", "stream", "structured", "tools", "models"})
    credential_env = ("OPENAI_API_KEY",)
    default_model = "gpt-4o-mini"
    static_models = (
        ModelInfo("gpt-4o-mini", "GPT-4o mini", {"structured_output": True, "tools": True}),
        ModelInfo("gpt-4o", "GPT-4o", {"structured_output": True, "tools": True, "vision": True}),
    )

    def _client(self):
        try:
            import openai  # noqa: PLC0415 — optional, deployment-time dependency
        except ImportError as e:
            raise NotConfigured("openai is not installed: pip install -r requirements-providers.txt") from e
        credential = self.credential()
        if not credential:
            raise NotConfigured("no OpenAI credential: set one on the provider or OPENAI_API_KEY", provider=self.slug)
        extra = self.settings.extra
        kwargs = {
            "api_key": credential,
            "max_retries": int(extra.get("max_retries", 2)),
            "timeout": float(extra.get("timeout", 600)),
        }
        for key, value in (
            ("organization", self.settings.organization),
            ("project", self.settings.project),
            ("base_url", self.settings.base_url),
        ):
            if value:
                kwargs[key] = value
        return openai, openai.OpenAI(**kwargs)

    def _request(self, model, system, messages, tools, schema, params) -> dict:
        params = params or {}
        kwargs = {"model": self.model_for(model), "messages": openai_messages(system, messages)}
        if tools:
            kwargs["tools"] = openai_tools(tools)
        if schema is not None:
            kwargs["response_format"] = openai_response_format(schema)
        kwargs.update({k: params[k] for k in ("temperature", "top_p") if params.get(k) is not None})
        if params.get("max_tokens"):
            kwargs["max_completion_tokens"] = params["max_tokens"]
        return kwargs

    def complete(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None) -> Completion:
        sdk, client = self._client()
        kwargs = self._request(model, system, messages, tools, schema, params)
        try:
            response = client.chat.completions.create(**kwargs)
        except sdk.APIStatusError as e:
            raise ProviderError(
                f"OpenAI API error {e.status_code}: {e}",
                provider=self.slug,
                retryable=e.status_code in (408, 409, 429) or e.status_code >= 500,
            ) from e
        except sdk.APIConnectionError as e:
            raise ProviderError(f"could not reach OpenAI: {e}", provider=self.slug, retryable=True) from e
        if not response.choices:
            raise ProviderError("OpenAI returned no choices", provider=self.slug)
        choice = response.choices[0]
        if getattr(choice.message, "refusal", None) or choice.finish_reason == "content_filter":
            raise ProviderError(
                f"OpenAI declined the request: {choice.message.refusal or 'content filter'}", provider=self.slug
            )
        usage = response.usage
        tokens_in, tokens_out = getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0
        return Completion(
            text=choice.message.content or "",
            tool_calls=openai_tool_calls(choice.message.tool_calls),
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self.cost(kwargs["model"], tokens_in, tokens_out),
            model=getattr(response, "model", "") or kwargs["model"],
            stop_reason=choice.finish_reason or "",
        )

    def stream(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None):
        _, client = self._client()
        kwargs = self._request(model, system, messages, tools, schema, params)
        for chunk in client.chat.completions.create(stream=True, **kwargs):
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta

    def list_models(self) -> list[ModelInfo]:
        if not self.credential():
            return list(self.static_models)
        _, client = self._client()
        found = sorted((ModelInfo(m.id, m.id) for m in client.models.list()), key=lambda m: m.id)
        return found or list(self.static_models)
