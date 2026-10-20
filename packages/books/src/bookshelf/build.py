"""Compile a book's chapter files into a single manuscript.

The output is markdown with the planning scaffolding stripped: no front
matter, no "Outline and Contextual Alignment", no navigation footers. What
remains is the narrative, in order, behind a title page -- the thing you hand
to a reader or feed to a converter such as pandoc.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import Book

DEFAULT_OUTPUT_DIR = "dist"


def manuscript(book: Book, include_outline: bool = False) -> str:
    """Render *book* as a single markdown manuscript."""
    parts: list[str] = [_title_page(book)]

    if include_outline and book.outline_path.exists():
        parts.append("## Outline\n")
        parts.append(book.outline_path.read_text(encoding="utf-8").strip())
        parts.append("\n---\n")

    current_act: int | None = None
    for chapter in book.chapters:
        if chapter.act is not None and chapter.act != current_act:
            current_act = chapter.act
            parts.append(f"## Act {_roman(current_act)}\n")
        heading = f"### {chapter.number}. {chapter.title}" if chapter.number else f"### {chapter.title}"
        parts.append(heading + "\n")
        if chapter.subtitle:
            parts.append(f"*{chapter.subtitle}*\n")
        prose = chapter.prose.strip()
        parts.append(prose if prose else "_(not yet written)_")
        parts.append("\n---\n")

    return "\n".join(part.rstrip() + "\n" for part in parts if part is not None)


def _title_page(book: Book) -> str:
    lines = [f"# {book.title}"]
    if book.meta.get("subtitle"):
        lines.append(f"\n*{book.meta['subtitle']}*")
    if book.meta.get("author"):
        lines.append(f"\nby {book.meta['author']}")
    if book.logline:
        lines.append(f"\n{book.logline}")
    lines.append("\n---")
    return "\n".join(lines)


def _roman(number: int) -> str:
    numerals = (("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1))
    out = ""
    remaining = number
    for symbol, value in numerals:
        while remaining >= value:
            out += symbol
            remaining -= value
    return out or str(number)


def write_manuscript(book: Book, out_dir: Path, include_outline: bool = False) -> Path:
    """Write ``<out_dir>/<slug>/manuscript.md`` and return its path."""
    target = out_dir / book.slug
    target.mkdir(parents=True, exist_ok=True)
    path = target / "manuscript.md"
    path.write_text(manuscript(book, include_outline=include_outline), encoding="utf-8")
    return path


# -- machine-readable views ----------------------------------------------
def book_to_dict(book: Book, root: Path | None = None) -> dict[str, Any]:
    """A JSON-serialisable snapshot of a book and its chapters."""

    def rel(path: Path) -> str:
        if root is None:
            return str(path)
        try:
            return str(path.relative_to(root))
        except ValueError:
            return str(path)

    return {
        "slug": book.slug,
        "title": book.title,
        "subtitle": book.meta.get("subtitle") or "",
        "status": book.status,
        "genre": book.genre,
        "logline": book.logline,
        "pov": book.pov,
        "tags": book.tags,
        "themes": book.themes,
        "cast": book.cast,
        "acts": book.acts,
        "planned_chapters": book.planned_chapters,
        "target_word_count": book.target_word_count,
        "word_count": book.word_count,
        "progress": round(book.progress, 4),
        "path": rel(book.root),
        "chapters": [
            {
                "number": chapter.number,
                "title": chapter.title,
                "subtitle": chapter.subtitle,
                "act": chapter.act,
                "status": chapter.status,
                "pov": chapter.pov,
                "era": chapter.era,
                "characters": chapter.characters,
                "setting": chapter.setting,
                "tone": chapter.tone,
                "word_count": chapter.word_count,
                "path": rel(chapter.path),
            }
            for chapter in book.chapters
        ],
    }


def write_json(books: list[Book], path: Path, root: Path | None = None) -> Path:
    payload = {
        "books": [book_to_dict(book, root) for book in books],
        "word_count": sum(book.word_count for book in books),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path
