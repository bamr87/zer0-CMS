"""Shared fixtures, plus a src/ path fallback.

The shared CI gate installs the package with `pip install -e . || true`, so a
failed install would otherwise turn into a wall of import errors rather than a
test result. Adding src/ to the path keeps the suite runnable either way.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SRC = REPO_ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bookshelf import frontmatter  # noqa: E402
from bookshelf.scaffold import _CHAPTER_BODY  # noqa: E402

BOOK_YML = """\
slug: sample
title: A Sample Book
status: drafting
logline: Someone wants something and cannot have it.
pov: Third person limited
acts: 3
planned_chapters: 4
target_word_count: 1000
tags: [sample, test]
cast: [Ana, Boris]
"""


def write_chapter(directory: Path, file_number: int, **overrides) -> Path:
    """Write ``ch<file_number>.md``. Overrides may set a *different* front
    matter ``number``, which is how the mismatch checks are exercised."""
    meta = {
        "title": f"Chapter {file_number}",
        "subtitle": "A subtitle",
        "number": file_number,
        "act": 1,
        "status": "draft",
        "pov": "Third person limited",
        "characters": ["Ana"],
        "setting": ["A room"],
        "era": "Now",
        "tone": ["Wry"],
        "style": "Observational",
    }
    meta.update(overrides)
    body = _CHAPTER_BODY.format(title=meta["title"]).replace(
        f"_{meta['title']} is not written yet._",
        "Ana opened the door and counted the empty chairs one final time.",
    )
    path = directory / f"ch{file_number:02d}.md"
    path.write_text(frontmatter.render(meta, body), encoding="utf-8")
    return path


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A minimal repository: library/ with one valid two-chapter book."""
    chapters = tmp_path / "library" / "sample" / "chapters"
    chapters.mkdir(parents=True)
    book_dir = chapters.parent
    (book_dir / "book.yml").write_text(BOOK_YML, encoding="utf-8")
    (book_dir / "outline.md").write_text("# A Sample Book\n\nAn outline.\n", encoding="utf-8")
    for number in (1, 2):
        write_chapter(chapters, number)
    _add_nav(chapters / "ch01.md", next_target="ch02.md")
    _add_nav(chapters / "ch02.md", prev_target="ch01.md")

    template = tmp_path / "library" / "_template"
    (template / "chapters").mkdir(parents=True)
    (template / "book.yml").write_text(
        "slug: x\ntitle: x\nstatus: idea\nacts: 3\nplanned_chapters: 3\n", encoding="utf-8"
    )
    (template / "outline.md").write_text("# {{title}}\n\nOutline for {{slug}}.\n", encoding="utf-8")
    return tmp_path


def _add_nav(path: Path, prev_target: str = "", next_target: str = "") -> None:
    lines = []
    if prev_target:
        lines.append(f"- [Previous Chapter: Earlier]({prev_target})")
    if next_target:
        lines.append(f"- [Next Chapter: Later]({next_target})")
    path.write_text(path.read_text(encoding="utf-8") + "\n" + "\n".join(lines) + "\n", encoding="utf-8")
