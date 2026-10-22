"""`claude_code`: Claude through the Claude Agent SDK, with a Claude Code OAuth
token (`claude setup-token`) or an API key.

A Claude Code OAuth token is a Claude Code credential, and the Agent SDK —
Claude Code as a library — is the supported way to drive it. Each completion
is one `query()` with every built-in tool off, no settings files read and
permission prompts denied, so it behaves like a stateless chat completion; a
multi-turn conversation is folded into the one prompt the SDK takes. It has no
tool protocol of the runner's kind (`tools` is not among its capabilities), so
an assistant run on it answers without reading tools. Structured output uses
the SDK's `output_format`; the result is validated locally like every other
provider's. The SDK is imported lazily (`requirements-providers.txt`).
"""

import asyncio
import json
import tempfile
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

from .anthropic import AnthropicProvider
from .base import Completion, NotConfigured, Provider, ProviderError

API_KEY_PREFIX = "sk-ant-api"


def _run(coroutine):
    """Block on a coroutine, on a fresh loop in a thread when one is already running."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coroutine).result()


def transcript(messages: list[dict]) -> str:
    """The conversation as the single prompt the SDK takes."""
    turns = [m for m in messages if m["role"] in ("user", "assistant") and m.get("content")]
    if len(turns) == 1:
        return turns[0]["content"]
    lines = ["<conversation>"]
    lines += [f"[{'User' if m['role'] == 'user' else 'Assistant'}]\n{m['content']}\n" for m in turns[:-1]]
    lines += ["</conversation>", "", "Reply to the final message below, keeping the conversation in mind.", ""]
    return "\n".join(lines + [turns[-1]["content"]])


class ClaudeCodeProvider(Provider):
    slug = "claude_code"
    display_name = "Claude Code (Agent SDK)"
    capabilities = frozenset({"complete", "stream", "structured", "models"})
    credential_env = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
    default_model = "claude-opus-5-5"
    static_models = AnthropicProvider.static_models

    def _options(self, model, system, schema, params):
        try:
            from claude_agent_sdk import ClaudeAgentOptions  # noqa: PLC0415 — optional, deployment-time dependency
        except ImportError as e:
            raise NotConfigured("claude-agent-sdk is not installed: pip install -r requirements-providers.txt") from e
        extra, token = self.settings.extra, self.settings.credential
        env = {
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            **{str(k): str(v) for k, v in extra.get("env", {}).items()},
        }
        if token:
            # The stored credential wins over the process environment; the competing variable is blanked.
            is_key = token.startswith(API_KEY_PREFIX)
            env.update(ANTHROPIC_API_KEY=token if is_key else "", CLAUDE_CODE_OAUTH_TOKEN="" if is_key else token)
        if self.settings.base_url:
            env["ANTHROPIC_BASE_URL"] = self.settings.base_url
        kwargs = {
            "system_prompt": system,
            "model": self.model_for(model),
            "tools": [],
            "allowed_tools": [],
            "permission_mode": "dontAsk",
            "max_turns": int(extra.get("max_turns", 3)),
            "setting_sources": [],
            "cwd": extra.get("cwd") or tempfile.gettempdir(),
            "env": env,
        }
        if (params or {}).get("effort") or extra.get("effort"):
            kwargs["effort"] = (params or {}).get("effort") or extra["effort"]
        if extra.get("cli_path"):
            kwargs["cli_path"] = extra["cli_path"]
        if schema is not None:
            kwargs["output_format"] = {"type": "json_schema", "schema": schema}
        return ClaudeAgentOptions(**kwargs)

    @staticmethod
    async def _collect(prompt, options):
        from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock, query  # noqa: PLC0415

        texts, result = [], None
        async for message in query(prompt=prompt, options=options):
            if isinstance(message, AssistantMessage):
                texts += [b.text for b in message.content if isinstance(b, TextBlock) and b.text]
            elif isinstance(message, ResultMessage):
                result = message
        return texts, result

    def complete(self, *, model, system, messages, tools=(), metadata=None, schema=None, params=None) -> Completion:
        options = self._options(model, system, schema, params)
        from claude_agent_sdk import ClaudeSDKError  # noqa: PLC0415

        try:
            texts, result = _run(self._collect(transcript(messages), options))
        except ClaudeSDKError as e:
            raise ProviderError(f"Claude Code failed: {e}", provider=self.slug, retryable=True) from e
        if result is None or result.is_error or result.subtype != "success":
            detail = getattr(result, "result", None) or getattr(result, "subtype", "no result")
            raise ProviderError(f"Claude Code run failed: {detail}", provider=self.slug)
        data = getattr(result, "structured_output", None) if schema is not None else None
        text = result.result or "\n".join(texts) or (json.dumps(data) if data is not None else "")
        usage = result.usage or {}
        return Completion(
            text=text,
            data=data,
            tokens_in=int(usage.get("input_tokens", 0) or 0),
            tokens_out=int(usage.get("output_tokens", 0) or 0),
            cost_usd=Decimal(str(result.total_cost_usd or 0)),
            model=next(iter(getattr(result, "model_usage", None) or {}), options.model),
            stop_reason=getattr(result, "stop_reason", "") or "",
        )
