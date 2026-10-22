"""Web search through a provider's own tool (ai/providers/): the `anthropic`
adapter declares `search` and runs one server-side `web_search` call, reading
its results back with what Claude quoted from each and the search's price; an
adapter that cannot search says so. The SDK is the stand-in module the AI
layer's provider tests use, so nothing reaches a network."""

import sys
from decimal import Decimal
from types import SimpleNamespace

import pytest

from ai.providers.anthropic import AnthropicProvider
from ai.providers.base import ProviderError, SearchResult, Settings
from ai.providers.openai import OpenAIProvider

from ..ai.test_providers import anthropic_sdk, claude_says


def test_anthropic_searches_with_its_web_search_tool_and_keeps_what_it_quoted(monkeypatch):
    hit = SimpleNamespace(url="https://example.com/backups", title="Backups explained", page_age="2 days ago")
    again = SimpleNamespace(url="https://example.com/backups", title="Backups explained", page_age=None)
    other = SimpleNamespace(url="https://example.org/restores", title="Restores", page_age=None)
    cited = SimpleNamespace(url="https://example.com/backups", cited_text="A nightly backup saves the day.")
    response = claude_says(
        SimpleNamespace(type="server_tool_use", id="s1", name="web_search", input={"query": "backups"}),
        SimpleNamespace(type="web_search_tool_result", tool_use_id="s1", content=[hit, again, other]),
        SimpleNamespace(type="text", text="The first result says so.", citations=[cited]),
    )
    response.usage.server_tool_use = SimpleNamespace(web_search_requests=1)
    module, calls = anthropic_sdk(response)
    monkeypatch.setitem(sys.modules, "anthropic", module)
    adapter = AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-api-x"))
    assert "search" in adapter.capabilities
    found = adapter.search("backups", max_results=5)
    assert found.data == [
        SearchResult(
            "https://example.com/backups", "Backups explained", "A nightly backup saves the day.", "2 days ago"
        ),
        SearchResult("https://example.org/restores", "Restores"),
    ]
    assert found.cost_usd == Decimal("0.008") + Decimal("0.01")  # the tokens, and $10 per 1,000 searches
    surface, sent = calls[1]
    assert surface == "messages" and sent["tools"] == [
        {"type": "web_search_20250305", "name": "web_search", "max_uses": 1}
    ]
    assert "backups" in sent["messages"][0]["content"]
    assert len(adapter.search("backups", max_results=1).data) == 1


def test_a_search_error_and_an_adapter_that_cannot_search_say_so(monkeypatch):
    failed = claude_says(
        SimpleNamespace(type="web_search_tool_result", content=SimpleNamespace(error_code="max_uses_exceeded"))
    )
    module, _ = anthropic_sdk(failed)
    monkeypatch.setitem(sys.modules, "anthropic", module)
    with pytest.raises(ProviderError, match="max_uses_exceeded"):
        AnthropicProvider(settings=Settings(slug="anthropic", credential="sk-ant-api-x")).search("x")
    openai = OpenAIProvider(settings=Settings(slug="openai"))
    assert "search" not in openai.capabilities
    with pytest.raises(ProviderError, match="cannot search the web"):
        openai.search("x")
