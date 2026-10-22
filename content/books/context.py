"""What a book task's model is given: the book's own material, assembled as
bookshelf's assistant assembled it (packages/books/src/bookshelf/ai.py), so a
suggestion is grounded in the book rather than in generic craft advice.

- the **brief**, true of the whole book: its facts (status, genre, logline,
  point of view, tense, era, protagonist, acts, chapters, themes, the cast as
  the only names to use), the outline, the character bible, the continuity
  ledger and the chapters so far — and the style guide, which bookshelf had no
  file for;
- the **local** material for one chapter: the act guide whose file name covers
  its number (`guides/act-2-chapters-06-09.md`) and the prose of the chapters
  either side;
- the **chapter** under work: its number, title, point of view, status and its
  whole file, outline section included;
- the **task**: the instruction, then the person's own and, for a revision,
  the passage marked SELECTION.

It reads the book's rendered file set (books/files.py), the text a writer sees
in `library/<slug>/`. The house rules are the bundled assistants' instructions
(books/data/), so a person may run a task with an assistant of their own and
the book still comes with it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .library import CHARACTERS, CONTINUITY, OUTLINE, STYLE_GUIDE, Book, Chapter, as_list

GUIDE_RANGE = re.compile(r"chapters?[-_](\d+)[-_](\d+)")


@dataclass(frozen=True)
class Task:
    key: str
    label: str
    description: str
    instruction: str
    chapter: bool  # needs a chapter to work on
    assistant: str  # the bundled assistant's key (books/data/bundled.yaml)


FINDINGS_SCHEMA_KEY = "book-continuity-findings"
OUTLINE_SCHEMA_KEY = "book-outline"

TASKS = {
    task.key: task
    for task in (
        Task(
            "draft",
            "Draft",
            "Write the chapter body from its outline, the act guide and the neighbouring chapters.",
            "Write the narrative prose for this chapter. Follow the plot beats in the chapter's own 'Outline and "
            "Contextual Alignment' section and the act guide. Open where the previous chapter left off and end "
            "somewhere the next chapter can pick up.\n\nReturn only the prose. No headings, no front matter, no "
            "commentary, no outline references.",
            True,
            "book-drafter",
        ),
        Task(
            "continue",
            "Continue",
            "Carry on from where the chapter currently stops, in its voice.",
            "Continue this chapter from exactly where it stops. Match the voice and pacing of what is already "
            "written; do not restate or summarise it.\n\nReturn only the new prose.",
            True,
            "book-continuer",
        ),
        Task(
            "revise",
            "Revise",
            "Rewrite a passage of the chapter to an instruction you give.",
            "Revise the passage marked SELECTION below according to the instruction. Keep everything that is "
            "working; change only what the instruction asks for.\n\nReturn only the revised passage, ready to "
            "replace the selection.",
            True,
            "book-reviser",
        ),
        Task(
            "check",
            "Continuity check",
            "Read the chapter against the brief and report what breaks, quoting the text at fault.",
            "Read this chapter against the book brief, the character bible, the continuity ledger and the "
            "neighbouring chapters. Report every place the chapter contradicts them or drifts from the outline.\n\n"
            "Report facts, not taste. A finding needs a concrete contradiction or a concrete drift from the stated "
            "plan -- not a preference about how a scene could be better. Quote the exact text at fault. If the "
            "chapter is consistent, return an empty findings list and say so in the summary.",
            True,
            "book-continuity-checker",
        ),
        Task(
            "critique",
            "Critique",
            "An editor's read of the chapter: what works, and what to fix next.",
            "Give an editorial read of this chapter. Say what is working and why, then the two or three changes "
            "that would most improve it, most important first. Be specific and quote the text. Do not rewrite the "
            "chapter.",
            True,
            "book-editor",
        ),
        Task(
            "outline",
            "Outline",
            "Write or extend the book's outline: synopsis, themes, three acts, the arc, the chapter plan.",
            "Write or extend this book's outline: a synopsis, the key themes, a three-act structure with numbered "
            "beats, the protagonist's arc as a phase table, and a chapter plan.",
            False,
            "book-outliner",
        ),
    )
}


def _section(title: str, body: str) -> str:
    body = (body or "").strip()
    return f"## {title}\n\n{body}\n" if body else ""


def brief(book: Book) -> str:
    """Everything true of the whole book."""
    facts = [f"- Title: {book.title}", f"- Status: {book.status}"]
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
    themes = book.meta.get("themes")
    if themes:
        facts.append("- Themes: " + "; ".join(as_list(themes)))
    if book.cast:
        facts.append("- Cast (the only names you may use): " + ", ".join(book.cast))
    chapters = [
        f"- ch{c.number:02d} ({c.status}, act {c.act or '?'}, {c.word_count:,} words): {c.title}"
        for c in book.chapters
        if c.number
    ]
    parts = [
        f"# Book brief: {book.title}\n",
        _section("Facts", "\n".join(facts)),
        _section("Outline", book.text(OUTLINE)),
        _section("Character bible", book.text(CHARACTERS)),
        _section("Continuity ledger", book.text(CONTINUITY)),
        _section("Style guide", book.text(STYLE_GUIDE)),
        _section("Chapters so far", "\n".join(chapters)),
    ]
    return "\n".join(part for part in parts if part)


def guide_for(book: Book, chapter: Chapter) -> str:
    """The act guide whose file name covers the chapter's number."""
    if chapter.number is None:
        return ""
    for path in sorted(p for p in book.tree if p.startswith("guides/") and p.count("/") == 1 and p.endswith(".md")):
        match = GUIDE_RANGE.search(path.rsplit("/", 1)[1][:-3])
        if match and int(match.group(1)) <= chapter.number <= int(match.group(2)):
            return book.tree[path]
    return ""


def local(book: Book, chapter: Chapter | None) -> str:
    """The act guide and the neighbouring chapters' prose for one chapter."""
    if chapter is None:
        return ""
    parts = []
    guide = guide_for(book, chapter)
    if guide:
        parts.append(_section(f"Drafting guide covering chapter {chapter.number}", guide))
    for offset, label in ((-1, "Previous chapter"), (1, "Next chapter")):
        neighbour = book.chapter(chapter.number + offset) if chapter.number is not None else None
        if neighbour is not None:
            parts.append(_section(f"{label}: {neighbour.title}", neighbour.prose.strip()))
    return "\n".join(parts)


def request(book: Book, chapter: Chapter | None, task: Task, *, instruction: str = "", selection: str = "") -> str:
    """The one user turn a task sends: the brief, the nearby material, the chapter and the task."""
    parts = [brief(book)]
    nearby = local(book, chapter)
    if nearby:
        parts.append("# Nearby material\n\n" + nearby)
    if chapter is not None:
        parts.append(
            "# The chapter you are working on\n\n"
            f"Number: {chapter.number}\nTitle: {chapter.title}\n"
            f"Point of view: {chapter.pov or book.pov}\nStatus: {chapter.status}\n\n"
            f"Its full file, including the outline section:\n\n{chapter.body.strip()}\n"
        )
    parts.append("# Task\n\n" + task.instruction)
    extra = f"SELECTION:\n\n{selection}\n\n{instruction}".strip() if selection else instruction.strip()
    if extra:
        parts.append("# Additional instruction\n\n" + extra)
    return "\n\n".join(parts)
