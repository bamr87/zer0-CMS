"""Claude-backed authoring assistance.

The rest of ``bookshelf`` has no required dependencies. This module is the one
exception: it needs the official Anthropic SDK, declared as the ``ai`` extra.
Import it lazily so ``books list``, ``books validate`` and the editor all work
in a checkout that never installs it.

What the assistant is given is as important as the prompt. Every request is
built from the book's own material -- the outline, the act guide covering the
chapter, the character bible, the continuity ledger, and the adjacent chapters
-- so suggestions are grounded in the book rather than in generic craft advice.
That context is a stable prefix and is cached; only the task and the chapter
under work vary between requests.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

from .models import Book, Chapter

#: Default model. Override per request or with BOOKSHELF_MODEL.
DEFAULT_MODEL = "claude-opus-5-5"

#: Reasoning depth. Drafting prose benefits from the default; quick checks do not.
DEFAULT_EFFORT = "high"

#: Streamed drafts can be long, so give them room.
DEFAULT_MAX_TOKENS = 32000

#: Opus 5's safety classifiers can decline a request. Opting into server-side
#: fallbacks means a declined request is retried on Anthropic's recommended
#: model in the same call rather than surfacing as an empty response.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(Exception):
    """Raised when the assistant cannot run: no SDK, no credentials, no API."""


def _client(api_key: str | None = None):
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover - depends on the environment
        raise AIError(
            "the Anthropic SDK is not installed; run `pip install -e \".[ai]\"` to enable AI features"
        ) from exc
    try:
        return anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    except Exception as exc:  # pragma: no cover - SDK raises on missing credentials
        raise AIError(f"could not create an Anthropic client: {exc}") from exc


# -- context assembly -----------------------------------------------------
_HOUSE_RULES = """\
You are an editorial assistant working inside a book project. You help draft, revise and \
check prose against the book's own material.

Rules that always apply:

- Write in the book's established point of view, tense and voice. They are stated in the \
book brief; if a chapter's own front matter differs, follow the chapter and say so.
- Never write outline bookkeeping into narrative prose. No "(Chapter 8)", no "(Ch. 2)", no \
quoting another chapter's title inside a scene. The reader cannot see the outline.
- Never invent a name for something the book has left unnamed. If a fact you need is missing \
from the brief, say which fact and stop -- do not fill it with a placeholder like \
[Company Name] and do not silently choose one.
- Only use character names that appear in the cast. If you need someone new, say so.
- Prose is one paragraph per line, with no soft wrapping. Markdown headings and lists follow \
the surrounding file's conventions.
- Match the register of the surrounding chapters. You are continuing someone's book, not \
starting your own.
"""


@dataclass
class BookContext:
    """The stable material an assistant needs to work on one book."""

    book: Book
    brief: str
    #: Per-chapter material: guides plus the neighbouring chapters.
    local: str = ""
    chapter: Chapter | None = None

    def system_blocks(self) -> list[dict[str, Any]]:
        """System prompt, with the cache breakpoint on the book brief.

        House rules are identical for every book and the brief is identical for
        every request against one book, so the pair caches as a single prefix.
        Anything that varies per chapter belongs in the user turn instead.
        """
        return [
            {"type": "text", "text": _HOUSE_RULES},
            {"type": "text", "text": self.brief, "cache_control": {"type": "ephemeral"}},
        ]


def _section(title: str, body: str) -> str:
    body = (body or "").strip()
    return f"## {title}\n\n{body}\n" if body else ""


def _read(path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_brief(book: Book) -> str:
    """Everything true of the whole book: identity, outline, cast, continuity."""
    facts = [
        f"- Title: {book.title}",
        f"- Status: {book.status}",
    ]
    for label, value in (
        ("Genre", book.genre),
        ("Logline", book.logline),
        ("Point of view", book.pov),
        ("Tense", str(book.meta.get("tense") or "")),
        ("Era", str(book.meta.get("era") or "")),
        ("Protagonist", str(book.meta.get("protagonist") or "")),
    ):
        if value:
            facts.append(f"- {label}: {value}")
    facts.append(f"- Acts: {book.acts}")
    facts.append(f"- Chapters: {len(book.chapters)} of {book.planned_chapters} planned")
    if book.themes:
        facts.append("- Themes: " + "; ".join(book.themes))
    if book.cast:
        facts.append("- Cast (the only names you may use): " + ", ".join(book.cast))

    parts = [
        f"# Book brief: {book.title}\n",
        _section("Facts", "\n".join(facts)),
        _section("Outline", _read(book.outline_path)),
    ]

    notes = book.root / "notes"
    parts.append(_section("Character bible", _read(notes / "characters.md")))
    parts.append(_section("Continuity ledger", _read(notes / "continuity.md")))

    chapters = [
        f"- ch{chapter.number:02d} ({chapter.status}, act {chapter.act or '?'}, "
        f"{chapter.word_count:,} words): {chapter.title}"
        for chapter in book.chapters
        if chapter.number
    ]
    parts.append(_section("Chapters so far", "\n".join(chapters)))

    return "\n".join(part for part in parts if part)


def build_local(book: Book, chapter: Chapter | None) -> str:
    """The act guide and neighbouring chapters for one chapter."""
    if chapter is None:
        return ""
    parts: list[str] = []

    guide = _guide_for(book, chapter)
    if guide:
        parts.append(_section(f"Drafting guide covering chapter {chapter.number}", guide))

    for offset, label in ((-1, "Previous chapter"), (1, "Next chapter")):
        if chapter.number is None:
            continue
        neighbour = book.chapter(chapter.number + offset)
        if neighbour is not None:
            prose = neighbour.prose.strip()
            parts.append(_section(f"{label}: {neighbour.title}", prose))

    return "\n".join(parts)


#: ``act-2-chapters-06-09.md`` -> chapters 6 through 9. Anchored on the word
#: "chapter" so a leading act number is never mistaken for a range bound.
_GUIDE_RANGE = re.compile(r"chapters?[-_](\d+)[-_](\d+)")


def _guide_for(book: Book, chapter: Chapter) -> str:
    """Find the guide in ``guides/`` whose filename covers this chapter number."""
    directory = book.root / "guides"
    if not directory.is_dir() or chapter.number is None:
        return ""
    for path in sorted(directory.glob("*.md")):
        match = _GUIDE_RANGE.search(path.stem)
        if not match:
            continue
        low, high = int(match.group(1)), int(match.group(2))
        if low <= chapter.number <= high:
            return _read(path)
    return ""


def context_for(book: Book, chapter: Chapter | None = None) -> BookContext:
    return BookContext(
        book=book,
        brief=build_brief(book),
        local=build_local(book, chapter),
        chapter=chapter,
    )


# -- tasks ----------------------------------------------------------------
@dataclass
class Task:
    """One thing the assistant can be asked to do."""

    key: str
    label: str
    description: str
    instruction: str
    #: When set, the model must return JSON matching this schema.
    schema: dict[str, Any] | None = None
    effort: str = DEFAULT_EFFORT
    max_tokens: int = DEFAULT_MAX_TOKENS


FINDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "severity": {"type": "string", "enum": ["high", "medium", "low"]},
                    "kind": {
                        "type": "string",
                        "enum": [
                            "continuity",
                            "character",
                            "timeline",
                            "pov",
                            "plot",
                            "prose",
                            "outline-drift",
                        ],
                    },
                    "quote": {"type": "string", "description": "The exact text at fault, or an empty string."},
                    "problem": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": ["severity", "kind", "quote", "problem", "suggestion"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": ["findings", "summary"],
    "additionalProperties": False,
}


TASKS: dict[str, Task] = {
    "draft": Task(
        key="draft",
        label="Draft",
        description="Write the chapter body from the outline, the act guide and the neighbouring chapters.",
        instruction=(
            "Write the narrative prose for this chapter. Follow the plot beats in the chapter's own "
            "'Outline and Contextual Alignment' section and the act guide. Open where the previous "
            "chapter left off and end somewhere the next chapter can pick up.\n\n"
            "Return only the prose. No headings, no front matter, no commentary, no outline references."
        ),
    ),
    "continue": Task(
        key="continue",
        label="Continue",
        description="Carry on from where the chapter currently stops.",
        instruction=(
            "Continue this chapter from exactly where it stops. Match the voice and pacing of what is "
            "already written; do not restate or summarise it.\n\n"
            "Return only the new prose."
        ),
    ),
    "revise": Task(
        key="revise",
        label="Revise",
        description="Rewrite the selected passage against an instruction you give.",
        instruction=(
            "Revise the passage marked SELECTION below according to the instruction. Keep everything "
            "that is working; change only what the instruction asks for.\n\n"
            "Return only the revised passage, ready to replace the selection."
        ),
    ),
    "check": Task(
        key="check",
        label="Continuity check",
        description="Read the chapter against the brief and report what breaks.",
        instruction=(
            "Read this chapter against the book brief, the character bible, the continuity ledger and "
            "the neighbouring chapters. Report every place the chapter contradicts them or drifts from "
            "the outline.\n\n"
            "Report facts, not taste. A finding needs a concrete contradiction or a concrete drift from "
            "the stated plan -- not a preference about how a scene could be better. Quote the exact text "
            "at fault. If the chapter is consistent, return an empty findings list and say so in the "
            "summary."
        ),
        schema=FINDINGS_SCHEMA,
        max_tokens=16000,
    ),
    "outline": Task(
        key="outline",
        label="Outline",
        description="Expand a premise into a three-act outline.",
        instruction=(
            "Write or extend this book's outline: a synopsis, the key themes, a three-act structure with "
            "numbered beats, the protagonist's arc as a phase table, and a chapter plan.\n\n"
            "Return markdown only, one paragraph per line."
        ),
    ),
    "critique": Task(
        key="critique",
        label="Critique",
        description="An editor's read of the chapter: what works, what to fix next.",
        instruction=(
            "Give an editorial read of this chapter. Say what is working and why, then the two or three "
            "changes that would most improve it, most important first. Be specific and quote the text. "
            "Do not rewrite the chapter."
        ),
        max_tokens=8000,
    ),
}


# -- the assistant --------------------------------------------------------
@dataclass
class Studio:
    """A configured Claude client, scoped to one library."""

    model: str = DEFAULT_MODEL
    api_key: str | None = None
    use_fallbacks: bool = True
    _client: Any = field(default=None, repr=False)

    def client(self):
        if self._client is None:
            self._client = _client(self.api_key)
        return self._client

    # -- request construction ---------------------------------------------
    def _user_turn(self, context: BookContext, task: Task, extra: str) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        if context.local:
            blocks.append(
                {
                    "type": "text",
                    "text": "# Nearby material\n\n" + context.local,
                    "cache_control": {"type": "ephemeral"},
                }
            )

        current = ""
        if context.chapter is not None:
            chapter = context.chapter
            current = (
                f"# The chapter you are working on\n\n"
                f"Number: {chapter.number}\nTitle: {chapter.title}\n"
                f"Point of view: {chapter.pov or context.book.pov}\n"
                f"Status: {chapter.status}\n\n"
                f"Its full file, including the outline section:\n\n{chapter.body.strip()}\n"
            )
        blocks.append({"type": "text", "text": current + "\n# Task\n\n" + task.instruction})
        if extra.strip():
            blocks.append({"type": "text", "text": "# Additional instruction\n\n" + extra.strip()})
        return blocks

    def _params(self, context: BookContext, task: Task, extra: str) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": self.model,
            "max_tokens": task.max_tokens,
            "system": context.system_blocks(),
            "messages": [{"role": "user", "content": self._user_turn(context, task, extra)}],
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": task.effort},
        }
        if task.schema is not None:
            params["output_config"]["format"] = {"type": "json_schema", "schema": task.schema}
        return params

    # -- execution --------------------------------------------------------
    def stream(self, context: BookContext, task: Task, extra: str = "") -> Iterator[str]:
        """Yield response text as it arrives.

        Streams even for short tasks: a long `max_tokens` on a non-streaming
        request risks an HTTP timeout, and the editor wants tokens as they land.
        """
        params = self._params(context, task, extra)
        client = self.client()

        for attempt in self._attempts():
            try:
                with client.beta.messages.stream(**params, **attempt) as stream:
                    yield from stream.text_stream
                    final = stream.get_final_message()
                self._check_refusal(final)
                return
            except AIError:
                raise
            except Exception as exc:
                if self._retry_without_fallbacks(exc, attempt):
                    continue
                raise AIError(_explain(exc)) from exc

    def run(self, context: BookContext, task: Task, extra: str = "") -> str:
        return "".join(self.stream(context, task, extra))

    def run_structured(self, context: BookContext, task: Task, extra: str = "") -> dict[str, Any]:
        """Run a task whose schema forces JSON, and parse the result."""
        if task.schema is None:
            raise AIError(f"task {task.key!r} does not return structured output")
        text = self.run(context, task, extra)
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIError(f"the model did not return valid JSON: {exc}") from exc

    # -- fallbacks and errors ---------------------------------------------
    def _attempts(self) -> list[dict[str, Any]]:
        """Request variants to try, best first.

        Server-side fallbacks are beta and not enabled for every account, so a
        rejection falls back to a plain request rather than failing the edit.
        """
        if not self.use_fallbacks:
            return [{}]
        return [{"betas": [FALLBACK_BETA], "fallbacks": "default"}, {}]

    def _retry_without_fallbacks(self, exc: Exception, attempt: dict[str, Any]) -> bool:
        """Should this failure be retried as a plain request?

        Two ways the opt-in can fail: the account does not have the beta (a 4xx
        naming it), or the installed SDK predates the parameter and rejects the
        keyword outright. Both mean "fall back to a plain request", and neither
        should surface to someone who just wanted a paragraph rewritten.
        """
        if not attempt:
            return False
        message = str(exc).lower()
        if isinstance(exc, TypeError) and "unexpected keyword" in message:
            self.use_fallbacks = False
            return True
        if getattr(exc, "status_code", None) not in (400, 403, 404):
            return False
        if "fallback" in message or "beta" in message:
            self.use_fallbacks = False
            return True
        return False

    @staticmethod
    def _check_refusal(message: Any) -> None:
        """Opus 5 returns HTTP 200 with ``stop_reason: refusal`` when declined."""
        if getattr(message, "stop_reason", None) != "refusal":
            return
        details = getattr(message, "stop_details", None)
        category = getattr(details, "category", None)
        suffix = f" (category: {category})" if category else ""
        raise AIError(f"the model declined this request{suffix}")


def _explain(exc: Exception) -> str:
    status = getattr(exc, "status_code", None)
    if status == 401:
        return "authentication failed; check ANTHROPIC_API_KEY"
    if status == 429:
        return "rate limited by the API; wait and try again"
    if status is not None and status >= 500:
        return f"the API returned {status}; try again shortly"
    return str(exc)
