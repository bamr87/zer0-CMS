"""Checks against the real content in this repository, not fixtures.

The fixture suite proves the code works. These prove the shipped library and
the shipped template work -- which is a different question, and the one that
caught an unparseable `{{slug}}` in the template.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from bookshelf import frontmatter
from bookshelf.build import manuscript
from bookshelf.library import Library
from bookshelf.models import Book, chapter_filename
from bookshelf.scaffold import new_book, new_chapter
from bookshelf.validate import ERROR, validate_book
from conftest import REPO_ROOT

#: Findings the impairment draft is known to carry. See docs/reviews/impairment.md.
KNOWN_ERROR_CODES = {"placeholder"}


@pytest.fixture(scope="module")
def library() -> Library:
    return Library.load(REPO_ROOT)


def test_the_shipped_template_parses():
    """`books new` reads this file before it stamps it, so it must be valid YAML."""
    config = REPO_ROOT / "library" / "_template" / "book.yml"
    meta = frontmatter.loads(config.read_text(encoding="utf-8"))
    assert meta["status"] == "idea"
    assert isinstance(meta.get("tags"), list)


def test_a_book_scaffolded_from_the_real_template_validates(tmp_path: Path):
    library_dir = tmp_path / "library"
    library_dir.mkdir()
    shutil.copytree(REPO_ROOT / "library" / "_template", library_dir / "_template")

    root = new_book(library_dir, "brand-new", "Brand New", library_dir / "_template", logline="A pitch.")
    book = Book.load(root)
    assert book.title == "Brand New"
    assert book.status == "idea"
    assert book.chapters == []

    new_chapter(book, "First Light")
    book = Book.load(root)
    assert [chapter.number for chapter in book.chapters] == [1]
    assert (root / "chapters" / chapter_filename(1)).exists()

    issues = validate_book(book)
    assert not [issue for issue in issues if issue.level == ERROR], [i.format(tmp_path) for i in issues]


def test_every_book_on_the_shelf_loads(library: Library):
    assert library.books, "the library should not be empty"
    for book in library.books:
        assert book.load_error is None, f"{book.slug}: {book.load_error}"
        assert book.title
        assert book.status


def test_impairment_is_intact(library: Library):
    book = library.get("impairment")
    assert len(book.chapters) == 14
    assert [chapter.number for chapter in book.chapters] == list(range(1, 15))
    assert all(chapter.path.name == chapter_filename(n) for n, chapter in enumerate(book.chapters, 1))
    assert all(chapter.word_count > 0 for chapter in book.chapters)
    assert book.outline_path.exists()


def test_impairment_carries_only_known_errors(library: Library):
    """New error codes should fail the build; the catalogued ones should not."""
    book = library.get("impairment")
    found = {issue.code for issue in validate_book(book) if issue.level == ERROR}
    assert found <= KNOWN_ERROR_CODES, f"new error kinds appeared: {sorted(found - KNOWN_ERROR_CODES)}"


def test_every_chapter_declares_its_cast_from_the_book(library: Library):
    book = library.get("impairment")
    cast = set(book.cast)
    for chapter in book.chapters:
        unknown = set(chapter.characters) - cast
        assert not unknown, f"{chapter.path.name} names {sorted(unknown)}, absent from book.yml cast"


def test_impairment_compiles_to_a_manuscript(library: Library):
    text = manuscript(library.get("impairment"))
    assert text.startswith("# The Impairment")
    for scaffold in ("Outline and Contextual Alignment", "Links and References", "Suggested Minor Updates"):
        assert scaffold not in text
    for act in ("## Act I", "## Act II", "## Act III"):
        assert act in text
