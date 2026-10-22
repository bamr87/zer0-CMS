"""Fixtures for the books app's tests: a small library on disk (the books
package's own test book — a manifest, an outline, two chapters with their
navigation, and a template), the real library under packages/books/library,
and the AI layer's people, scripted provider, worker and API client. Nothing
reaches a model or the network."""

from pathlib import Path

import pytest
import yaml
from django.conf import settings

from books.files import import_library
from tests.ai.conftest import alice, api, bob, fake, staff, worker  # noqa: F401 — shared fixtures

BOOK_YML = """\
# A sample manifest.
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

SKELETON = """
## Outline and Contextual Alignment

### Purpose of the Chapter

- What this chapter has to accomplish.

---

## Chapter Body

{prose}

---

## References & Contextual Alignment

- How this chapter lines up with the outline.

---

## Links and References
"""


def chapter_text(at: int, *, prose="Ana opened the door and counted the empty chairs one final time.", **meta):
    """A chapter file numbered `at`; `meta` overrides its front matter, `number` included."""
    front = {
        "title": f"Chapter {at}",
        "subtitle": "A subtitle",
        "number": at,
        "act": 1,
        "status": "draft",
        "pov": "Third person limited",
        "characters": ["Ana"],
        "setting": ["A room"],
        "era": "Now",
        "tone": ["Wry"],
        "style": "Observational",
        **meta,
    }
    return f"---\n{yaml.safe_dump(front, sort_keys=False)}---\n{SKELETON.format(prose=prose)}"


def write_library(root: Path) -> Path:
    """`root/library`: one valid two-chapter book (`sample`) and the template."""
    book = root / "library" / "sample"
    (book / "chapters").mkdir(parents=True)
    (book / "book.yml").write_text(BOOK_YML, encoding="utf-8")
    (book / "outline.md").write_text("# A Sample Book\n\nAn outline.\n", encoding="utf-8")
    (book / "guides").mkdir()
    (book / "guides" / "act-1-chapters-01-02.md").write_text("# Act I guide\n\nOpen cold.\n", encoding="utf-8")
    (book / "notes").mkdir()
    (book / "notes" / "characters.md").write_text("# Cast\n\nAna is the protagonist.\n", encoding="utf-8")
    (book / "notes" / "continuity.md").write_text("# Ledger\n\nThe door is always green.\n", encoding="utf-8")
    (book / "chapters" / "ch01.md").write_text(chapter_text(1) + "- [Next Chapter: Later](ch02.md)\n", encoding="utf-8")
    (book / "chapters" / "ch02.md").write_text(
        chapter_text(2) + "- [Previous Chapter: Earlier](ch01.md)\n", encoding="utf-8"
    )
    template = root / "library" / "_template"
    (template / "chapters").mkdir(parents=True)
    (template / "chapters" / ".gitkeep").write_text("", encoding="utf-8")
    (template / "book.yml").write_text(
        '# Manifest for one book.\nslug: "{{slug}}"\ntitle: "{{title}}"\nstatus: idea\npov: Third person limited\n'
        "acts: 3\nplanned_chapters: 3\n",
        encoding="utf-8",
    )
    (template / "outline.md").write_text("# {{title}}\n\nOutline for {{slug}}.\n", encoding="utf-8")
    return root / "library"


@pytest.fixture
def library_dir(tmp_path) -> Path:
    return write_library(tmp_path)


@pytest.fixture
def sample(db, library_dir):
    """The small library imported; returns the `sample` book."""
    from books.services import by_slug

    report = import_library(library_dir, site_key=settings.BOOKS_SITE_KEY)
    assert not report.errors and not report.conflicts, report.summary()
    return by_slug("sample")


@pytest.fixture
def impairment(db):
    """The real library (packages/books/library) imported; returns `impairment`."""
    from books.services import by_slug

    report = import_library(settings.BOOKS_LIBRARY_DIR, site_key=settings.BOOKS_SITE_KEY)
    assert not report.errors and not report.conflicts, report.summary()
    return by_slug("impairment")
