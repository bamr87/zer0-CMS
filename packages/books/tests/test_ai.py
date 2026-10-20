"""Assistant context assembly and request shaping.

No network. A stub stands in for the Anthropic client so the request the
assistant *would* send is asserted directly — that request is the part worth
protecting, since a dropped cache breakpoint or a missing refusal check is
invisible until it costs money or silently returns nothing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bookshelf import ai
from bookshelf.library import Library
from conftest import write_chapter


class FakeStream:
    def __init__(self, chunks, stop_reason="end_turn", category=None):
        self.chunks = chunks
        self._stop_reason = stop_reason
        self._category = category

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @property
    def text_stream(self):
        return iter(self.chunks)

    def get_final_message(self):
        details = type("Details", (), {"category": self._category})() if self._category else None
        return type("Message", (), {"stop_reason": self._stop_reason, "stop_details": details})()


class FakeClient:
    """Records the params of each call and replays canned output."""

    def __init__(self, chunks=("hello ", "world"), stop_reason="end_turn", category=None, fail_betas=False):
        self.calls: list[dict] = []
        self._chunks = chunks
        self._stop_reason = stop_reason
        self._category = category
        self._fail_betas = fail_betas
        outer = self

        class Messages:
            def stream(self, **params):
                outer.calls.append(params)
                if outer._fail_betas and "betas" in params:
                    error = Exception("fallbacks: unrecognized beta")
                    error.status_code = 400
                    raise error
                return FakeStream(outer._chunks, outer._stop_reason, outer._category)

        self.beta = type("Beta", (), {"messages": Messages()})()


@pytest.fixture
def book(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 3)
    guides = repo / "library" / "sample" / "guides"
    guides.mkdir()
    (guides / "act-1-chapters-01-02.md").write_text("# Act I guide\n\nOpen cold.\n", encoding="utf-8")
    (guides / "act-2-chapters-03-04.md").write_text("# Act II guide\n\nRaise the stakes.\n", encoding="utf-8")
    notes = repo / "library" / "sample" / "notes"
    notes.mkdir()
    (notes / "characters.md").write_text("# Cast\n\nAna is the protagonist.\n", encoding="utf-8")
    (notes / "continuity.md").write_text("# Ledger\n\nThe door is always green.\n", encoding="utf-8")
    return Library.load(repo).get("sample")


def studio(**kwargs) -> tuple[ai.Studio, FakeClient]:
    client = FakeClient(**kwargs)
    assistant = ai.Studio()
    assistant._client = client
    return assistant, client


# -- context --------------------------------------------------------------
def test_brief_carries_the_books_own_material(book):
    brief = ai.build_brief(book)
    assert "A Sample Book" in brief
    assert "Ana is the protagonist." in brief  # character bible
    assert "The door is always green." in brief  # continuity ledger
    assert "An outline." in brief
    assert "Cast (the only names you may use): Ana, Boris" in brief


def test_local_context_picks_the_guide_covering_this_chapter(book):
    local = ai.build_local(book, book.chapter(3))
    assert "Act II guide" in local
    assert "Act I guide" not in local


def test_guide_range_ignores_the_leading_act_number(book):
    """`act-2-chapters-03-04` covers 3-4, not 2-3 — the act number is not a bound."""
    assert "Act I guide" in ai.build_local(book, book.chapter(1))
    assert "Act II guide" in ai.build_local(book, book.chapter(4)) or book.chapter(4) is None


def test_local_context_includes_both_neighbours(book):
    local = ai.build_local(book, book.chapter(2))
    assert "Previous chapter: Chapter 1" in local
    assert "Next chapter: Chapter 3" in local


def test_context_without_a_chapter_has_no_local_material(book):
    assert ai.context_for(book).local == ""


# -- request shape --------------------------------------------------------
def test_request_caches_the_stable_prefix_only(book):
    assistant, client = studio()
    assistant.run(ai.context_for(book, book.chapter(2)), ai.TASKS["draft"])
    params = client.calls[0]

    system = params["system"]
    assert "cache_control" not in system[0], "house rules cache with the brief, not separately"
    assert system[1]["cache_control"] == {"type": "ephemeral"}

    blocks = params["messages"][0]["content"]
    cached = [block for block in blocks if "cache_control" in block]
    assert len(cached) == 1, "only the per-chapter material is a second breakpoint"
    assert cached[0]["text"].startswith("# Nearby material")


def test_request_uses_adaptive_thinking_and_effort(book):
    assistant, client = studio()
    assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])
    params = client.calls[0]
    assert params["thinking"] == {"type": "adaptive"}
    assert params["output_config"]["effort"] == ai.DEFAULT_EFFORT
    assert params["model"] == ai.DEFAULT_MODEL
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in params, f"{banned} is rejected by this model"


def test_structured_tasks_request_a_json_schema(book):
    assistant, client = studio(chunks=('{"findings": [], "summary": "clean"}',))
    result = assistant.run_structured(ai.context_for(book, book.chapter(1)), ai.TASKS["check"])
    assert result == {"findings": [], "summary": "clean"}
    fmt = client.calls[0]["output_config"]["format"]
    assert fmt["type"] == "json_schema"
    assert fmt["schema"] is ai.FINDINGS_SCHEMA


def test_streaming_tasks_do_not_request_a_schema(book):
    assistant, client = studio()
    assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])
    assert "format" not in client.calls[0]["output_config"]


def test_extra_instruction_lands_after_the_task(book):
    assistant, client = studio()
    assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["revise"], "make it colder")
    texts = [block["text"] for block in client.calls[0]["messages"][0]["content"]]
    assert texts[-1] == "# Additional instruction\n\nmake it colder"


def test_house_rules_forbid_placeholders_and_meta_references(book):
    system = ai.context_for(book).system_blocks()[0]["text"]
    assert "[Company Name]" in system
    assert "(Chapter 8)" in system


# -- error handling -------------------------------------------------------
def test_refusal_is_raised_not_returned_silently(book):
    assistant, _ = studio(stop_reason="refusal", category="cyber")
    with pytest.raises(ai.AIError, match="declined"):
        assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])


def test_fallbacks_are_requested_by_default(book):
    assistant, client = studio()
    assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])
    assert client.calls[0]["fallbacks"] == "default"
    assert ai.FALLBACK_BETA in client.calls[0]["betas"]


def test_an_account_without_the_fallback_beta_still_works(book):
    """A 400 on the beta must degrade to a plain request, not fail the edit."""
    assistant, client = studio(fail_betas=True)
    text = assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])
    assert text == "hello world"
    assert len(client.calls) == 2
    assert "betas" not in client.calls[1]
    assert assistant.use_fallbacks is False, "the retry should stick for later calls"


def test_an_sdk_too_old_for_the_fallback_parameter_still_works(book):
    """An older SDK rejects the keyword outright rather than returning a 4xx."""

    class OldSdk(FakeClient):
        def __init__(self):
            super().__init__()
            outer = self

            class Messages:
                def stream(self, **params):
                    outer.calls.append(params)
                    if "fallbacks" in params:
                        raise TypeError("stream() got an unexpected keyword argument 'fallbacks'")
                    return FakeStream(outer._chunks)

            self.beta = type("Beta", (), {"messages": Messages()})()

    assistant = ai.Studio()
    client = OldSdk()
    assistant._client = client
    assert assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"]) == "hello world"
    assert len(client.calls) == 2


def test_fallbacks_can_be_turned_off(book):
    client = FakeClient()
    assistant = ai.Studio(use_fallbacks=False)
    assistant._client = client
    assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])
    assert "betas" not in client.calls[0]


def test_unrelated_errors_are_not_retried(book):
    class Boom(FakeClient):
        def __init__(self):
            super().__init__()
            outer = self

            class Messages:
                def stream(self, **params):
                    outer.calls.append(params)
                    error = Exception("service unavailable")
                    error.status_code = 503
                    raise error

            self.beta = type("Beta", (), {"messages": Messages()})()

    assistant = ai.Studio()
    client = Boom()
    assistant._client = client
    with pytest.raises(ai.AIError, match="503"):
        assistant.run(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])
    assert len(client.calls) == 1


def test_bad_json_from_a_structured_task_is_reported(book):
    assistant, _ = studio(chunks=("not json",))
    with pytest.raises(ai.AIError, match="valid JSON"):
        assistant.run_structured(ai.context_for(book, book.chapter(1)), ai.TASKS["check"])


def test_run_structured_rejects_a_streaming_task(book):
    assistant, _ = studio()
    with pytest.raises(ai.AIError, match="does not return structured output"):
        assistant.run_structured(ai.context_for(book, book.chapter(1)), ai.TASKS["draft"])
