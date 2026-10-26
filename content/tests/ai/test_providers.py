"""The provider registry and its six adapters (ADR 0006 decision 7): one way to
reach a model, configured from `ProviderConfig`; nothing outside
`ai/providers/` imports a vendor SDK; structured output is validated here,
whatever the vendor promised, and never by fetching a reference. Each vendor
adapter runs against a stand-in SDK module put in `sys.modules` — what it sends
and how it reads the answer — so no SDK is installed and nothing reaches a
network. A row's options are the adapter's declared ones, a vendor-prefixed
model id reaches the vendor bare, and an environment credential never goes to
a base URL a row chose."""

import ast
import contextlib
import json
import sys
import tempfile
import types
import urllib.request
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings
from django.test import override_settings

from agents import llm
from agents.runner import execute, start_run
from ai import providers
from ai.models import ModelEntry, ProviderConfig
from ai.providers.anthropic import AnthropicProvider, anthropic_messages
from ai.providers.base import Completion, InvalidOutput, NotConfigured, ProviderError, Settings, parse_json, validate
from ai.providers.claude_code import ClaudeCodeProvider, transcript
from ai.providers.fake import FakeProvider
from ai.providers.litellm import LiteLLMProvider
from ai.providers.openai import OpenAIProvider
from ai.providers.recorded import RecordedProvider, Recorder, RecordingMissing, prompt_digest
from graph.embeddings import ProviderEmbedder

SDKS = {"anthropic", "openai", "litellm", "claude_agent_sdk"}
CONTENT = Path(settings.BASE_DIR)
SCHEMA = {
    "type": "object",
    "properties": {"headline": {"type": "string"}},
    "required": ["headline"],
    "additionalProperties": False,
}
TOOL = {"name": "content.get_page", "description": "One page.", "input_schema": {"type": "object"}}
HISTORY = [
    {"role": "user", "content": "Read page 3."},
    {
        "role": "assistant",
        "content": "",
        "tool_calls": [{"id": "t1", "name": "content.get_page", "arguments": {"page_id": 3}}],
    },
    {"role": "tool", "tool_call_id": "t1", "name": "content.get_page", "content": '{"title": "Backups"}'},
]


def sdk_imports(root: Path, allowed: Path) -> list[str]:
    """Every `import <vendor SDK>` under `root`, outside `allowed`."""
    found = []
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root)
        if allowed in path.parents or any(part.startswith(".") for part in relative.parts):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            found += [f"{relative}:{node.lineno} imports {n}" for n in names if n.split(".")[0] in SDKS]
    return found


def test_no_module_outside_the_providers_imports_a_provider_sdk():
    assert sdk_imports(CONTENT, CONTENT / "ai" / "providers") == []


def test_the_import_scan_catches_an_sdk_import(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "sneaky.py").write_text(
        "def f():\n    from anthropic import Anthropic\n    import openai.types\n"
    )
    assert sdk_imports(tmp_path, tmp_path / "providers") == [
        "pkg/sneaky.py:2 imports anthropic",
        "pkg/sneaky.py:3 imports openai.types",
    ]


def test_the_providers_themselves_import_their_sdk_only_inside_methods():
    """Module level stays importable without any SDK installed."""
    for name in ("anthropic", "openai", "litellm", "claude_code"):
        tree = ast.parse((CONTENT / "ai" / "providers" / f"{name}.py").read_text(encoding="utf-8"))
        top = [n for n in tree.body if isinstance(n, ast.Import | ast.ImportFrom)]
        assert not [n for n in top if isinstance(n, ast.Import) and n.names[0].name.split(".")[0] in SDKS], name


# ── the registry ───────────────────────────────────────────────────────────


def test_the_registry_has_six_adapters_and_takes_more_from_settings():
    assert providers.available() == ["anthropic", "claude_code", "fake", "litellm", "openai", "recorded"]
    with override_settings(AI_PROVIDERS={"echo": "ai.providers.fake.FakeProvider", "openai": ""}):
        assert "echo" in providers.available() and "openai" not in providers.available()
        assert isinstance(providers.provider_class("echo")(), FakeProvider)
    with pytest.raises(ProviderError, match="unknown provider"):
        providers.provider_class("nope")


@pytest.mark.django_db
def test_get_builds_an_adapter_from_its_row_with_the_catalog_prices():
    row = ProviderConfig.objects.get(slug="anthropic")
    row.set_credential("sk-ant-api-secret")
    row.base_url, row.default_model = "https://proxy.example", "claude-sonnet-5-5"
    row.save()
    ModelEntry.objects.create(
        provider=row, model_id="claude-sonnet-5-5", input_usd_per_mtok=Decimal("3"), output_usd_per_mtok=Decimal("9")
    )
    adapter = providers.get("anthropic")
    assert isinstance(adapter, AnthropicProvider)
    assert adapter.settings.credential == "sk-ant-api-secret" and adapter.credential_source() == "database"
    assert adapter.model_for() == "claude-sonnet-5-5"
    assert adapter.cost("claude-sonnet-5-5", 1_000_000, 1_000_000) == Decimal("12")
    assert adapter.cost("claude-opus-5-5", 1_000_000, 0) == Decimal("4")  # the static list
    assert adapter.cost("unknown", 10, 10) == 0


@pytest.mark.django_db
def test_the_default_provider_is_the_flagged_row_then_the_setting():
    assert providers.default_slug() == settings.AI_DEFAULT_PROVIDER == "fake"
    ProviderConfig.objects.filter(slug="openai").update(is_default=True)
    assert providers.default_slug() == "openai"
    ProviderConfig.objects.filter(slug="openai").update(enabled=False)
    assert providers.default_slug() == "fake"


def test_override_swaps_one_slug_for_a_block():
    fake = FakeProvider()
    with providers.override(fake, "anthropic"):
        assert providers.get("anthropic", config=Settings(slug="anthropic")) is fake
    assert isinstance(providers.get("anthropic", config=Settings(slug="anthropic")), AnthropicProvider)


# ── structured output ──────────────────────────────────────────────────────


def test_structured_output_is_parsed_and_validated_locally():
    assert parse_json('```json\n{"headline": "Hi"}\n```') == {"headline": "Hi"}
    assert validate({"headline": "Hi"}, SCHEMA) == {"headline": "Hi"}
    with pytest.raises(InvalidOutput, match="did not return JSON"):
        parse_json("Sure! Here it is.")
    with pytest.raises(InvalidOutput, match="at headline"):
        validate({"headline": 3}, SCHEMA)
    fake = FakeProvider([{"text": '{"headline": "Hi"}'}, {"text": '{"title": "wrong"}'}])
    request = {"model": "m", "system": "s", "messages": [{"role": "user", "content": "go"}]}
    assert fake.structured(schema=SCHEMA, **request).data == {"headline": "Hi"}
    assert fake.calls[0]["schema"] == SCHEMA
    with pytest.raises(InvalidOutput):
        fake.structured(schema=SCHEMA, **request)


def test_the_fake_is_scripted_records_calls_raises_and_streams():
    boom = ProviderError("down", retryable=True)
    fake = FakeProvider(
        [Completion(text="one"), lambda call: {"text": f"saw {call['model']}"}, boom, {"text": "streamed text"}]
    )
    ask = {"system": "s", "messages": [{"role": "user", "content": "q"}]}
    assert fake.complete(model="a", **ask).text == "one"
    assert fake.complete(model="b", **ask).text == "saw b"
    with pytest.raises(ProviderError):
        fake.complete(model="c", **ask)
    assert "".join(fake.stream(model="d", **ask)) == "streamed text"
    assert fake.complete(model="e", **ask).text == ""  # an empty script answers empty
    assert [c["model"] for c in fake.calls] == ["a", "b", "c", "d", "e"]
    assert {"complete", "stream", "structured", "tools", "models"} == fake.capabilities


def test_health_is_a_one_word_completion_with_its_cost():
    fake = FakeProvider([{"text": "OK", "tokens_in": 5, "tokens_out": 1, "cost_usd": "0.0001"}])
    health = fake.health()
    assert health["ok"] and health["reply"] == "OK" and health["tokens"] == 6 and health["cost_usd"] == "0.0001"
    assert fake.calls[0]["params"] == {"max_tokens": 16}


def test_recorded_includes_the_schema_in_its_digest(tmp_path):
    (tmp_path / "a" / "s").mkdir(parents=True)
    digest = prompt_digest("sys", [], SCHEMA)
    assert digest != prompt_digest("sys", []) == prompt_digest("sys", [], None)
    (tmp_path / "a" / "s" / "00.json").write_text(json.dumps({"prompt_digest": digest, "response": {"text": "{}"}}))
    recorded = RecordedProvider(tmp_path)
    meta = {"agent": "a", "scenario": "s", "step": 0}
    assert recorded.complete(model="m", system="sys", messages=[], metadata=meta, schema=SCHEMA).text == "{}"
    with pytest.raises(RecordingMissing):
        recorded.complete(model="m", system="sys", messages=[], metadata={**meta, "step": 1})


def test_the_recorder_writes_what_a_live_provider_answers(tmp_path):
    live = FakeProvider([{"text": '{"headline": "Hi"}', "tokens_in": 3}])
    meta = {"agent": "a", "scenario": "s", "step": 0}
    Recorder(live, tmp_path).complete(model="m", system="sys", messages=[], metadata=meta, schema=SCHEMA)
    written = json.loads((tmp_path / "a" / "s" / "00.json").read_text())
    assert written["prompt_digest"] == prompt_digest("sys", [], SCHEMA) and written["response"]["tokens_in"] == 3


# ── agents.llm, the front the runner uses ──────────────────────────────────


@pytest.mark.django_db
def test_get_llm_is_the_registry_adapter_named_by_llm_backend():
    assert isinstance(llm.get_llm(), RecordedProvider) and llm.get_llm().name == "recorded"
    with override_settings(LLM_BACKEND="fake"):
        assert isinstance(llm.get_llm(), llm.FakeLLM)
    with override_settings(LLM_BACKEND="litellm", LLM_RECORD=True):
        recorder = llm.get_llm()
        assert isinstance(recorder, llm.RecordingLLM) and isinstance(recorder.inner, llm.LiteLLMClient)
    with override_settings(LLM_BACKEND="nope"), pytest.raises(ValueError, match="unknown LLM_BACKEND"):
        llm.get_llm()
    assert llm.FakeLLM is FakeProvider and llm.RecordedLLM is RecordedProvider


@pytest.mark.django_db
def test_graph_embeddings_go_through_the_registry():
    class Embeds(FakeProvider):
        slug = "litellm"

        def embed(self, texts, *, model=""):
            return [[float(len(t)), 1.0] for t in texts]

    with override_settings(EMBEDDING_BACKEND="litellm"), providers.override(Embeds()):
        assert ProviderEmbedder().embed("four") == [4.0, 1.0]
    with pytest.raises(ProviderError, match="does not embed"):
        FakeProvider().embed(["x"])


# ── anthropic ──────────────────────────────────────────────────────────────


class StatusError(Exception):
    def __init__(self, message, status_code):
        super().__init__(message)
        self.message, self.status_code = message, status_code


def anthropic_sdk(response, models=()):
    calls = []

    class Messages:
        def __init__(self, surface):
            self.surface = surface

        def create(self, **kwargs):
            calls.append((self.surface, kwargs))
            if isinstance(response, Exception):
                raise response
            return response

        @contextlib.contextmanager
        def stream(self, **kwargs):
            calls.append((f"{self.surface}.stream", kwargs))
            yield SimpleNamespace(text_stream=iter(["Hel", "lo"]))

    class Anthropic:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))
            self.messages = Messages("messages")
            self.beta = SimpleNamespace(messages=Messages("beta"))
            self.models = SimpleNamespace(list=lambda: list(models))

    module = types.ModuleType("anthropic")
    module.Anthropic, module.APIStatusError = Anthropic, StatusError
    module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    return module, calls


def claude_says(*blocks, stop="end_turn", model="claude-opus-5-5"):
    return SimpleNamespace(
        content=list(blocks),
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200),
        model=model,
        stop_reason=stop,
        stop_details=SimpleNamespace(category="cyber") if stop == "refusal" else None,
    )


def test_anthropic_maps_tools_schema_and_history_and_reads_tool_use_back(monkeypatch):
    response = claude_says(
        SimpleNamespace(type="text", text="Looking."),
        SimpleNamespace(type="tool_use", id="t2", name="content__get_page", input={"page_id": 4}),
    )
    module, calls = anthropic_sdk(response)
    monkeypatch.setitem(sys.modules, "anthropic", module)
    adapter = AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-api-x"))
    got = adapter.complete(
        model="claude-opus-5-5",
        system="Be brief.",
        messages=HISTORY,
        tools=[TOOL],
        schema=SCHEMA,
        params={"temperature": 0.2, "max_tokens": 500},
    )
    assert (
        got.text == "Looking."
        and got.tool_calls[0].name == "content.get_page"
        and got.tool_calls[0].arguments == {"page_id": 4}
    )
    assert (got.tokens_in, got.tokens_out, got.cost_usd) == (1000, 200, Decimal("0.008"))
    assert calls[0] == ("client", {"max_retries": 2, "timeout": 600.0, "api_key": "sk-ant-api-x"})
    surface, sent = calls[1]
    assert surface == "beta" and sent["betas"] == ["server-side-fallback-2026-07-01"] and sent["fallbacks"] == "default"
    assert sent["system"] == "Be brief." and sent["max_tokens"] == 500 and "extra_body" not in sent
    assert sent["tools"] == [
        {"name": "content__get_page", "description": "One page.", "input_schema": {"type": "object"}}
    ]
    assert sent["output_config"] == {"format": {"type": "json_schema", "schema": SCHEMA}}
    assert sent["messages"][1]["content"][0] == {
        "type": "tool_use",
        "id": "t1",
        "name": "content__get_page",
        "input": {"page_id": 3},
    }
    assert sent["messages"][2] == {
        "role": "user",
        "content": [{"type": "tool_result", "tool_use_id": "t1", "content": '{"title": "Backups"}'}],
    }


def test_anthropic_older_models_get_sampling_and_no_fallbacks_and_oauth_tokens_ride_as_bearer(monkeypatch):
    module, calls = anthropic_sdk(claude_says(SimpleNamespace(type="text", text="ok"), model="claude-haiku-4-5"))
    monkeypatch.setitem(sys.modules, "anthropic", module)
    adapter = AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-oat-token"))
    adapter.complete(
        model="claude-haiku-4-5", system="", messages=[{"role": "user", "content": "hi"}], params={"temperature": 0.5}
    )
    client, (surface, sent) = calls[0][1], calls[1]
    assert client["auth_token"] == "sk-ant-oat-token" and client["default_headers"] == {
        "anthropic-beta": "oauth-2025-04-20"
    }
    assert surface == "messages" and sent["extra_body"] == {"temperature": 0.5} and "temperature" not in sent
    assert "system" not in sent and "betas" not in sent


def test_anthropic_refusals_errors_and_missing_credentials(monkeypatch):
    module, _ = anthropic_sdk(claude_says(stop="refusal"))
    monkeypatch.setitem(sys.modules, "anthropic", module)
    adapter = AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-api-x"))
    ask = {"model": "claude-opus-5-5", "system": "", "messages": [{"role": "user", "content": "hi"}]}
    with pytest.raises(ProviderError, match="declined the request \\(category: cyber\\)"):
        adapter.complete(**ask)
    module, _ = anthropic_sdk(StatusError("overloaded", 529))
    monkeypatch.setitem(sys.modules, "anthropic", module)
    with pytest.raises(ProviderError, match="529") as raised:
        adapter.complete(**ask)
    assert raised.value.retryable
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)
    with pytest.raises(NotConfigured, match="no Anthropic credential"):
        AnthropicProvider().complete(**ask)
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(NotConfigured, match="not installed"):
        adapter.complete(**ask)


def test_anthropic_streams_and_lists_models(monkeypatch):
    listed = [SimpleNamespace(id="claude-opus-5-5", display_name="Claude Opus 5.5", max_input_tokens=1_000_000)]
    module, calls = anthropic_sdk(claude_says(), models=listed)
    monkeypatch.setitem(sys.modules, "anthropic", module)
    adapter = AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-api-x"))
    ask = {"model": "claude-haiku-4-5", "system": "", "messages": [{"role": "user", "content": "hi"}]}
    assert "".join(adapter.stream(**ask)) == "Hello" and calls[-1][0] == "messages.stream"
    [model] = adapter.list_models()
    assert model.id == "claude-opus-5-5" and model.input_usd_per_mtok == Decimal("4") and model.capabilities["context"]


def test_anthropic_tool_results_in_a_row_share_one_user_turn():
    two = HISTORY + [{"role": "tool", "tool_call_id": "t9", "name": "x", "content": "{}"}]
    assert [len(m["content"]) for m in anthropic_messages(two) if m["role"] == "user"][-1] == 2


# ── openai ─────────────────────────────────────────────────────────────────


def openai_sdk(message, finish="stop"):
    calls = []

    class Completions:
        def create(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get("stream"):
                return iter(
                    [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=c))]) for c in ("a", "b")]
                )
            return SimpleNamespace(
                choices=[SimpleNamespace(message=message, finish_reason=finish)],
                usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                model="gpt-4o-mini",
            )

    class OpenAI:
        def __init__(self, **kwargs):
            calls.append(("client", kwargs))
            self.chat = SimpleNamespace(completions=Completions())
            self.models = SimpleNamespace(list=lambda: [SimpleNamespace(id="gpt-b"), SimpleNamespace(id="gpt-a")])

    module = types.ModuleType("openai")
    module.OpenAI, module.APIStatusError = OpenAI, StatusError
    module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    return module, calls


def test_openai_maps_function_calls_and_response_format(monkeypatch):
    call = SimpleNamespace(id="c1", function=SimpleNamespace(name="content__get_page", arguments='{"page_id": 4}'))
    module, calls = openai_sdk(SimpleNamespace(content="", tool_calls=[call], refusal=None), finish="tool_calls")
    monkeypatch.setitem(sys.modules, "openai", module)
    adapter = OpenAIProvider(settings=Settings(slug="openai", credential="sk-x", organization="org", project="p"))
    got = adapter.complete(
        model="", system="Be brief.", messages=HISTORY, tools=[TOOL], schema=SCHEMA, params={"max_tokens": 9}
    )
    assert got.tool_calls[0].name == "content.get_page" and got.tool_calls[0].arguments == {"page_id": 4}
    assert (got.tokens, got.model) == (15, "gpt-4o-mini")
    assert calls[0][1]["organization"] == "org" and calls[0][1]["project"] == "p"
    sent = calls[1]
    assert sent["model"] == "gpt-4o-mini" and sent["max_completion_tokens"] == 9
    assert sent["messages"][0] == {"role": "system", "content": "Be brief."}
    assert sent["messages"][2]["tool_calls"][0]["function"] == {
        "name": "content__get_page",
        "arguments": '{"page_id": 3}',
    }
    assert sent["messages"][3] == {"role": "tool", "tool_call_id": "t1", "content": '{"title": "Backups"}'}
    assert sent["tools"][0]["function"]["name"] == "content__get_page"
    assert sent["response_format"]["json_schema"]["schema"] == SCHEMA
    assert "".join(adapter.stream(model="", system="", messages=[{"role": "user", "content": "q"}])) == "ab"
    assert [m.id for m in adapter.list_models()] == ["gpt-a", "gpt-b"]


def test_openai_refusals_are_errors(monkeypatch):
    module, _ = openai_sdk(SimpleNamespace(content=None, tool_calls=None, refusal="no"))
    monkeypatch.setitem(sys.modules, "openai", module)
    with pytest.raises(ProviderError, match="declined"):
        OpenAIProvider(settings=Settings(slug="openai", credential="k")).complete(
            model="", system="", messages=[{"role": "user", "content": "q"}]
        )


# ── litellm ────────────────────────────────────────────────────────────────


def test_litellm_routes_anything_and_embeds(monkeypatch):
    calls = []
    module = types.ModuleType("litellm")

    def completion(**kwargs):
        calls.append(kwargs)
        message = SimpleNamespace(content='{"headline": "Hi"}', tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message, finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=7, completion_tokens=3),
        )

    module.completion = completion
    module.completion_cost = lambda completion_response: 0.0021
    module.embedding = lambda model, input: SimpleNamespace(data=[{"embedding": [0.5, 0.25]} for _ in input])
    module.model_cost = {
        "gemini/flash": {"input_cost_per_token": 1e-7, "output_cost_per_token": 4e-7, "max_input_tokens": 1000}
    }
    monkeypatch.setitem(sys.modules, "litellm", module)
    adapter = LiteLLMProvider(settings=Settings(slug="litellm", credential="key", extra={"models": ["gemini/flash"]}))
    got = adapter.structured(
        model="gemini/flash", system="s", messages=[{"role": "user", "content": "q"}], schema=SCHEMA
    )
    assert got.data == {"headline": "Hi"} and got.cost_usd == Decimal("0.0021") and got.tokens == 10
    assert calls[0]["api_key"] == "key" and calls[0]["response_format"]["json_schema"]["schema"] == SCHEMA
    assert adapter.embed(["a", "b"]) == [[0.5, 0.25], [0.5, 0.25]]
    [model] = adapter.list_models()
    assert (
        model.id == "gemini/flash"
        and model.input_usd_per_mtok == Decimal("0.1")
        and model.capabilities["context"] == 1000
    )


def test_litellm_failures_are_provider_errors(monkeypatch):
    module = types.ModuleType("litellm")

    def completion(**kwargs):
        raise RuntimeError("rate limited")

    module.completion = completion
    monkeypatch.setitem(sys.modules, "litellm", module)
    with pytest.raises(ProviderError, match="rate limited"):
        LiteLLMProvider().complete(model="x/y", system="", messages=[{"role": "user", "content": "q"}])


# ── claude_code ────────────────────────────────────────────────────────────


def claude_agent_sdk(result):
    seen = {}
    module = types.ModuleType("claude_agent_sdk")

    class Options:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)
            seen["options"] = kwargs

    class AssistantMessage:
        def __init__(self, content):
            self.content = content

    class TextBlock:
        def __init__(self, text):
            self.text = text

    class ResultMessage:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    async def query(prompt, options):
        seen["prompt"] = prompt
        yield AssistantMessage([TextBlock("thinking out loud")])
        yield ResultMessage(**result)

    module.ClaudeAgentOptions, module.AssistantMessage, module.TextBlock = Options, AssistantMessage, TextBlock
    module.ResultMessage, module.query = ResultMessage, query
    module.ClaudeSDKError = type("ClaudeSDKError", (Exception,), {})
    return module, seen


def test_claude_code_runs_one_tool_less_query_with_the_stored_credential(monkeypatch):
    result = {
        "is_error": False,
        "subtype": "success",
        "result": '{"headline": "Hi"}',
        "structured_output": {"headline": "Hi"},
        "usage": {"input_tokens": 40, "output_tokens": 8},
        "total_cost_usd": 0.0031,
        "model_usage": {"claude-opus-5-5": {}},
        "stop_reason": "end_turn",
    }
    module, seen = claude_agent_sdk(result)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    adapter = ClaudeCodeProvider(settings=Settings(slug="claude_code", credential="sk-ant-oat-token"))
    turns = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply"},
        {"role": "user", "content": "second"},
    ]
    got = adapter.structured(model="", system="Be brief.", messages=turns, schema=SCHEMA)
    assert got.data == {"headline": "Hi"} and got.cost_usd == Decimal("0.0031") and got.tokens == 48
    options = seen["options"]
    assert options["tools"] == [] and options["allowed_tools"] == [] and options["setting_sources"] == []
    assert options["env"]["CLAUDE_CODE_OAUTH_TOKEN"] == "sk-ant-oat-token" and options["env"]["ANTHROPIC_API_KEY"] == ""
    assert options["env"]["ANTHROPIC_AUTH_TOKEN"] == "" and options["cwd"] == tempfile.gettempdir()
    assert (
        options["output_format"] == {"type": "json_schema", "schema": SCHEMA} and options["model"] == "claude-opus-5-5"
    )
    assert seen["prompt"].startswith("<conversation>") and seen["prompt"].endswith("second")
    assert "tools" not in adapter.capabilities
    assert transcript([{"role": "user", "content": "only"}]) == "only"


def test_claude_code_failures_are_provider_errors(monkeypatch):
    module, _ = claude_agent_sdk({"is_error": True, "subtype": "error_max_turns", "result": None})
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    with pytest.raises(ProviderError, match="error_max_turns"):
        ClaudeCodeProvider().complete(model="", system="", messages=[{"role": "user", "content": "q"}])
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", None)
    with pytest.raises(NotConfigured, match="not installed"):
        ClaudeCodeProvider().complete(model="", system="", messages=[{"role": "user", "content": "q"}])


def test_claude_code_takes_no_process_settings_from_its_row(monkeypatch):
    ok = {"is_error": False, "subtype": "success", "result": "ok", "usage": {}, "total_cost_usd": 0}
    module, seen = claude_agent_sdk(ok)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "worker-key")
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    extra = {"cli_path": "/tmp/anything", "env": {"LD_PRELOAD": "/tmp/x.so"}, "cwd": "/"}
    ask = {"model": "", "system": "", "messages": [{"role": "user", "content": "q"}]}
    ClaudeCodeProvider(settings=Settings(slug="claude_code", extra=extra)).complete(**ask)
    options = seen["options"]
    assert "cli_path" not in options and "LD_PRELOAD" not in options["env"] and options["cwd"] == tempfile.gettempdir()
    assert (options["env"]["ANTHROPIC_API_KEY"], options["env"]["CLAUDE_CODE_OAUTH_TOKEN"]) == ("worker-key", "")
    with pytest.raises(NotConfigured, match="its own credential"):
        ClaudeCodeProvider(settings=Settings(slug="claude_code", base_url="https://elsewhere.example")).complete(**ask)


def test_an_environment_credential_never_goes_to_a_base_url_a_row_chose(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-worker")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-worker")
    elsewhere = {"base_url": "https://elsewhere.example"}
    for cls in (AnthropicProvider, OpenAIProvider, ClaudeCodeProvider):
        assert cls(settings=Settings(slug=cls.slug, **elsewhere)).credential() == "", cls
        assert cls(settings=Settings(slug=cls.slug, credential="its-own", **elsewhere)).credential() == "its-own"
    assert AnthropicProvider().credential() == "sk-ant-api-worker"  # the deployment's own endpoint
    module, calls = anthropic_sdk(claude_says())
    monkeypatch.setitem(sys.modules, "anthropic", module)
    ask = {"model": "claude-haiku-4-5", "system": "", "messages": [{"role": "user", "content": "q"}]}
    with pytest.raises(NotConfigured):
        AnthropicProvider(settings=Settings(slug="anthropic", **elsewhere)).complete(**ask)
    assert calls == []  # refused before a client was built
    litellm = types.ModuleType("litellm")
    litellm.completion = lambda **kwargs: pytest.fail("LiteLLM was called")
    monkeypatch.setitem(sys.modules, "litellm", litellm)
    with pytest.raises(NotConfigured, match="its own credential"):
        LiteLLMProvider(settings=Settings(slug="litellm", **elsewhere)).complete(**ask)


def test_anthropic_oauth_keeps_its_beta_beside_the_fallback_one(monkeypatch):
    """A request's `betas` replace the client's `anthropic-beta` header, so an
    OAuth token's beta rides in the list on the models with fallbacks."""
    module, calls = anthropic_sdk(claude_says(SimpleNamespace(type="text", text="ok")))
    monkeypatch.setitem(sys.modules, "anthropic", module)
    adapter = AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-oat01-token"))
    adapter.complete(model="claude-opus-5-5", system="", messages=[{"role": "user", "content": "hi"}])
    client, (surface, sent) = calls[0][1], calls[1]
    assert client["auth_token"] == "sk-ant-oat01-token" and surface == "beta"
    assert sent["betas"] == ["server-side-fallback-2026-07-01", "oauth-2025-04-20"] and sent["fallbacks"] == "default"
    plain = AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-api-key"))
    plain.complete(model="claude-opus-5-5", system="", messages=[{"role": "user", "content": "hi"}])
    assert calls[-1][1]["betas"] == ["server-side-fallback-2026-07-01"]


def test_a_vendor_prefixed_model_id_reaches_the_vendor_bare():
    assert AnthropicProvider().model_for("anthropic/claude-sonnet-5-5") == "claude-sonnet-5-5"
    assert ClaudeCodeProvider().model_for("anthropic/claude-haiku-5-5") == "claude-haiku-5-5"
    assert OpenAIProvider().model_for("openai/gpt-4o") == "gpt-4o"
    assert OpenAIProvider().model_for("anthropic/claude-x") == "anthropic/claude-x"  # not its vendor's: as given
    assert LiteLLMProvider().model_for("anthropic/claude-sonnet-5-5") == "anthropic/claude-sonnet-5-5"


@pytest.mark.django_db
def test_a_shipped_agent_runs_on_the_anthropic_backend(monkeypatch, agent, article):
    module, calls = anthropic_sdk(
        claude_says(SimpleNamespace(type="text", text="Looks fine."), model="claude-haiku-5-5")
    )
    monkeypatch.setitem(sys.modules, "anthropic", module)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api-test")
    with override_settings(LLM_BACKEND="anthropic"):
        run = execute(start_run(agent("seo"), trigger="manual", target=article, enqueue=False))
    assert run.status == "succeeded", run.error
    surface, sent = calls[1]
    assert agent("seo").model == "anthropic/claude-haiku-5-5" and sent["model"] == "claude-haiku-5-5"
    assert sent["tools"] and run.llm_backend == "anthropic"


@pytest.mark.django_db
def test_a_tool_using_agent_is_refused_on_a_backend_without_tool_calls(agent, article):
    class NoTools(FakeProvider):
        capabilities = frozenset({"complete"})

    with llm.use_llm(NoTools([{"text": "never asked"}])) as client:
        run = execute(start_run(agent("seo"), trigger="manual", target=article, enqueue=False))
    assert run.status == "failed" and "no tool calls" in run.error and client.calls == []


def test_validation_never_fetches_a_reference(monkeypatch):
    fetched = []

    def urlopen(*args, **kwargs):
        fetched.append(args)
        raise AssertionError("fetched")

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    remote = {"type": "object", "properties": {"a": {"$ref": "http://169.254.169.254/latest/meta-data"}}}
    with pytest.raises(InvalidOutput, match="outside itself"):
        validate({"a": 1}, remote)
    assert fetched == []
