"""`anthropic`: Claude through the Messages API, with an API key (or an OAuth token).

Structured output uses `output_config.format` (a JSON Schema), so Claude
returns a JSON document; it is still validated locally like every provider's.
Tool calls travel as `tool_use` / `tool_result` blocks. On the models that run
safety classifiers (Opus 5+, Sonnet 5.5, Fable) a decline is retried on
Anthropic's recommended fallback model inside the same call
(`fallbacks="default"`), unless the row's `extra.server_side_fallbacks` is
false; a decline that survives is a `ProviderError`. An OAuth token needs its
own beta, which a request's `betas` would replace, so it rides in that list
too. Current models reject sampling parameters and the SDK no longer takes
them, so `temperature` and `top_p` reach only the older models that accept
them, in the request body. The SDK is imported lazily
(`requirements-providers.txt`).

`search` is Anthropic's server-side web search tool, in its basic version
(`web_search_20250305`): research wants the result list itself, not results
Claude has already filtered with code, and the basic version runs on every
platform. Each result keeps what Claude quoted from it; a search costs $10 per
1,000 on top of the tokens.
"""

import re
from decimal import Decimal

from .base import (
    CLIENT_OPTIONS,
    EFFORT,
    Completion,
    ModelInfo,
    NotConfigured,
    Provider,
    ProviderError,
    SearchResult,
    ToolCall,
    tool_name,
    wire_name,
)

WEB_SEARCH = {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
SEARCH_USD = Decimal("0.01")
OAUTH_PREFIX = "sk-ant-oat"
OAUTH_BETA = "oauth-2025-04-20"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
NO_SAMPLING = re.compile(r"^claude-(fable|mythos|opus-5|opus-4-[78]|sonnet-5|haiku-5)")
FALLBACKS = re.compile(r"^claude-(fable|opus-5|sonnet-5-5)")
CAPS = {"structured_output": True, "tools": True, "vision": True, "context": 1_000_000}


class AnthropicProvider(Provider):
    slug = "anthropic"
    display_name = "Anthropic (Claude API)"
    capabilities = frozenset({"complete", "stream", "structured", "tools", "models", "search", "vision"})
    credential_env = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")
    default_model = "claude-opus-5-5"
    static_models = (
        ModelInfo("claude-opus-5-5", "Claude Opus 5.5", CAPS, Decimal("4"), Decimal("20")),
        ModelInfo("claude-sonnet-5-5", "Claude Sonnet 5.5", CAPS, Decimal("2"), Decimal("10")),
        ModelInfo("claude-haiku-5-5", "Claude Haiku 5.5", CAPS, Decimal("0.10"), Decimal("0.50")),
        ModelInfo("claude-fable-5-1", "Claude Fable 5.1", CAPS, Decimal("10"), Decimal("50")),
    )
    options = {
        **CLIENT_OPTIONS,
        "max_tokens": {"type": "integer", "minimum": 1, "maximum": 128000},
        "effort": EFFORT,
        "server_side_fallbacks": {"type": "boolean"},
    }
    model_prefixes = ("anthropic",)

    def _oauth(self) -> bool:
        return self.credential().startswith(OAUTH_PREFIX) or self.credential_source() == "ANTHROPIC_AUTH_TOKEN"

    def _client(self):
        try:
            import anthropic  # noqa: PLC0415 — optional, deployment-time dependency
        except ImportError as e:
            raise NotConfigured("anthropic is not installed: pip install -r requirements-providers.txt") from e
        credential = self.credential()
        if not credential:
            raise NotConfigured(
                "no Anthropic credential: set one on the provider (a row with its own base URL needs one) "
                "or ANTHROPIC_API_KEY",
                provider=self.slug,
            )
        extra = self.settings.extra
        kwargs = {"max_retries": int(extra.get("max_retries", 2)), "timeout": float(extra.get("timeout", 600))}
        if self._oauth():
            kwargs.update(auth_token=credential, default_headers={"anthropic-beta": OAUTH_BETA})
        else:
            kwargs["api_key"] = credential
        if self.settings.base_url:
            kwargs["base_url"] = self.settings.base_url
        return anthropic, anthropic.Anthropic(**kwargs)

    def _request(self, model, system, messages, tools, schema, params) -> dict:
        params, extra = params or {}, self.settings.extra
        model = self.model_for(model)
        kwargs = {
            "model": model,
            "max_tokens": int(params.get("max_tokens") or extra.get("max_tokens", 16000)),
            "messages": anthropic_messages(messages),
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": wire_name(t["name"]), "description": t["description"], "input_schema": t["input_schema"]}
                for t in tools
            ]
        output_config = {}
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        if params.get("effort") or extra.get("effort"):
            output_config["effort"] = params.get("effort") or extra["effort"]
        if output_config:
            kwargs["output_config"] = output_config
        sampling = {k: params[k] for k in ("temperature", "top_p") if params.get(k) is not None}
        if sampling and not NO_SAMPLING.match(model):
            kwargs["extra_body"] = sampling
        if FALLBACKS.match(model) and extra.get("server_side_fallbacks", True):
            # A request's betas replace the client's anthropic-beta header, the OAuth beta with it.
            kwargs.update(betas=[FALLBACK_BETA, *([OAUTH_BETA] if self._oauth() else [])], fallbacks="default")
        return kwargs

    @staticmethod
    def _messages(client, kwargs):
        """The beta surface carries server-side fallbacks; everything else is the plain one."""
        return client.beta.messages if "betas" in kwargs else client.messages

    def complete(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None) -> Completion:
        sdk, client = self._client()
        kwargs = self._request(model, system, messages, tools, schema, params)
        return self._completion(self._create(sdk, self._messages(client, kwargs), kwargs), kwargs["model"])

    def _create(self, sdk, messages, kwargs):
        try:
            return messages.create(**kwargs)
        except sdk.APIStatusError as e:
            raise ProviderError(
                f"Anthropic API error {e.status_code}: {e.message}",
                provider=self.slug,
                retryable=e.status_code in (408, 409, 429) or e.status_code >= 500,
            ) from e
        except sdk.APIConnectionError as e:
            raise ProviderError(f"could not reach Anthropic: {e}", provider=self.slug, retryable=True) from e

    def search(self, query: str, *, max_results: int = 5) -> Completion:
        """One web search: the results the tool returned, each with what Claude quoted from it."""
        sdk, client = self._client()
        model = self.model_for()
        ask = f"Search the web for: {query}\n\nThen name the most relevant results, quoting each one."
        kwargs = {
            "model": model,
            "max_tokens": 4000,
            "tools": [WEB_SEARCH],
            "messages": [{"role": "user", "content": ask}],
        }
        response = self._create(sdk, client.messages, kwargs)
        completion = self._completion(response, model)
        found, quoted = {}, {}
        for block in response.content or []:
            if block.type == "web_search_tool_result":
                if not isinstance(block.content, list):  # an error is an object, and arrives with HTTP 200
                    code = getattr(block.content, "error_code", "unknown")
                    raise ProviderError(f"web search failed: {code}", provider=self.slug)
                for hit in block.content:
                    found.setdefault(hit.url, (hit.title or "", getattr(hit, "page_age", None) or ""))
            for citation in getattr(block, "citations", None) or []:
                if getattr(citation, "url", None):
                    quoted.setdefault(citation.url, getattr(citation, "cited_text", "") or "")
        searches = getattr(getattr(response.usage, "server_tool_use", None), "web_search_requests", 0) or 0
        completion.cost_usd += SEARCH_USD * searches
        completion.data = [
            SearchResult(url=url, title=title, snippet=quoted.get(url, ""), published=age)
            for url, (title, age) in list(found.items())[:max_results]
        ]
        return completion

    def _completion(self, response, model) -> Completion:
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            raise ProviderError(
                f"Claude declined the request (category: {getattr(details, 'category', None) or 'unspecified'})",
                provider=self.slug,
            )
        blocks = response.content or []
        tokens_in, tokens_out = response.usage.input_tokens or 0, response.usage.output_tokens or 0
        served = getattr(response, "model", "") or model
        return Completion(
            text="".join(b.text for b in blocks if b.type == "text"),
            tool_calls=[ToolCall(b.id, tool_name(b.name), dict(b.input)) for b in blocks if b.type == "tool_use"],
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=self.cost(served, tokens_in, tokens_out),
            model=served,
            stop_reason=response.stop_reason or "",
        )

    def stream(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None):
        _, client = self._client()
        kwargs = self._request(model, system, messages, tools, schema, params)
        with self._messages(client, kwargs).stream(**kwargs) as stream:
            yield from stream.text_stream

    def list_models(self) -> list[ModelInfo]:
        if not self.credential():
            return list(self.static_models)
        _, client = self._client()
        priced = {m.id: m for m in self.static_models}
        found = []
        for m in client.models.list():
            known = priced.get(m.id)
            found.append(
                ModelInfo(
                    m.id,
                    getattr(m, "display_name", "") or m.id,
                    {**CAPS, "context": getattr(m, "max_input_tokens", None)},
                    known.input_usd_per_mtok if known else None,
                    known.output_usd_per_mtok if known else None,
                )
            )
        return found or list(self.static_models)


def anthropic_messages(messages: list[dict]) -> list[dict]:
    """The runner's messages as Messages API turns: tool calls as `tool_use`
    blocks, consecutive tool results gathered into one user turn."""
    wire: list[dict] = []
    for m in messages:
        if m["role"] == "tool":
            block = {"type": "tool_result", "tool_use_id": m["tool_call_id"], "content": m["content"]}
            last = wire[-1] if wire else None
            if last and last["role"] == "user" and isinstance(last["content"], list):
                last["content"].append(block)
            else:
                wire.append({"role": "user", "content": [block]})
        elif m.get("tool_calls"):
            content = [{"type": "text", "text": m["content"]}] if m.get("content") else []
            content += [
                {"type": "tool_use", "id": c["id"], "name": wire_name(c["name"]), "input": c["arguments"]}
                for c in m["tool_calls"]
            ]
            wire.append({"role": "assistant", "content": content})
        elif isinstance(m["content"], list):
            wire.append({"role": m["role"], "content": [_part(part) for part in m["content"]]})
        else:
            wire.append({"role": m["role"], "content": m["content"]})
    return wire


def _part(part: dict) -> dict:
    """A message part as a Messages API block: an image as base64, the rest as text."""
    if part.get("type") == "image":
        return {"type": "image", "source": {"type": "base64", "media_type": part["media_type"], "data": part["data"]}}
    return {"type": "text", "text": part.get("text", "")}
