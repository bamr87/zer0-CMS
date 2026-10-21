"""End-to-end CLI behaviour, including build, scaffold and dashboard output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bookshelf.build import manuscript
from bookshelf.cli import main
from bookshelf.library import Library, LibraryError, find_root
from bookshelf.scaffold import ScaffoldError, new_book, slugify


def run(repo: Path, *args: str) -> int:
    return main(["--root", str(repo), *args])


# -- read commands --------------------------------------------------------
def test_list_shows_the_book(repo: Path, capsys):
    assert run(repo, "list") == 0
    out = capsys.readouterr().out
    assert "sample" in out and "A Sample Book" in out and "drafting" in out


def test_list_json_is_machine_readable(repo: Path, capsys):
    assert run(repo, "list", "--json") == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload[0]["slug"] == "sample"
    assert payload[0]["word_count"] > 0
    assert len(payload[0]["chapters"]) == 2


def test_list_filters_by_status(repo: Path, capsys):
    assert run(repo, "list", "--status", "complete") == 0
    assert "No books found" in capsys.readouterr().out


def test_show_lists_chapters(repo: Path, capsys):
    assert run(repo, "show", "sample") == 0
    out = capsys.readouterr().out
    assert "Chapter 1" in out and "Chapter 2" in out


def test_show_unknown_slug_exits_two(repo: Path, capsys):
    assert run(repo, "show", "nope") == 2
    assert "unknown book" in capsys.readouterr().err


def test_stats_reports_totals(repo: Path, capsys):
    assert run(repo, "stats") == 0
    out = capsys.readouterr().out
    assert "chapters   2" in out
    assert "progress" in out


# -- validate -------------------------------------------------------------
def test_validate_passes_on_a_clean_library(repo: Path, capsys):
    assert run(repo, "validate") == 0
    assert "No problems found" in capsys.readouterr().out


def test_validate_exits_one_on_an_error(repo: Path, capsys):
    path = repo / "library" / "sample" / "chapters" / "ch02.md"
    path.write_text(path.read_text(encoding="utf-8").replace("empty chairs", "[Company Name]"), encoding="utf-8")
    assert run(repo, "validate") == 1
    assert "placeholder" in capsys.readouterr().out


def test_validate_strict_fails_on_warnings(repo: Path, capsys):
    path = repo / "library" / "sample" / "chapters" / "ch02.md"
    path.write_text(path.read_text(encoding="utf-8").replace("final time.", "final time (Ch. 8)."), encoding="utf-8")
    assert run(repo, "validate") == 0
    capsys.readouterr()
    assert run(repo, "validate", "--strict") == 1


# -- build ----------------------------------------------------------------
def test_manuscript_strips_scaffolding_and_orders_chapters(repo: Path):
    book = Library.load(repo).get("sample")
    text = manuscript(book)
    assert text.startswith("# A Sample Book")
    assert "Outline and Contextual Alignment" not in text
    assert "Links and References" not in text
    assert "## Act I" in text
    assert text.index("1. Chapter 1") < text.index("2. Chapter 2")


def test_build_writes_a_manuscript(repo: Path, capsys):
    assert run(repo, "build", "sample") == 0
    written = repo / "dist" / "sample" / "manuscript.md"
    assert written.exists()
    assert "empty chairs" in written.read_text(encoding="utf-8")
    assert "Wrote" in capsys.readouterr().out


def test_build_can_include_the_outline(repo: Path):
    run(repo, "build", "sample", "--include-outline")
    assert "An outline." in (repo / "dist" / "sample" / "manuscript.md").read_text(encoding="utf-8")


# -- dashboard ------------------------------------------------------------
def test_dashboard_is_self_contained(repo: Path):
    assert run(repo, "dashboard") == 0
    html = (repo / "dist" / "index.html").read_text(encoding="utf-8")
    assert "A Sample Book" in html
    assert "prefers-color-scheme: dark" in html
    assert 'data-theme="dark"' in html
    for external in ("http://", "https://", "<script"):
        assert external not in html, f"dashboard must not reference {external}"
    payload = json.loads((repo / "dist" / "library.json").read_text(encoding="utf-8"))
    assert payload["books"][0]["slug"] == "sample"


def test_dashboard_escapes_book_content(repo: Path):
    book_yml = repo / "library" / "sample" / "book.yml"
    book_yml.write_text(
        book_yml.read_text(encoding="utf-8").replace("title: A Sample Book", 'title: "Bad <b>markup</b>"'),
        encoding="utf-8",
    )
    run(repo, "dashboard")
    html = (repo / "dist" / "index.html").read_text(encoding="utf-8")
    assert "<b>markup</b>" not in html
    assert "&lt;b&gt;markup&lt;/b&gt;" in html


# -- scaffolding ----------------------------------------------------------
def test_new_book_then_add_chapter(repo: Path, capsys):
    assert run(repo, "new", "second-book", "--title", "Second Book", "--logline", "A pitch.") == 0
    capsys.readouterr()
    assert run(repo, "add-chapter", "second-book", "--title", "Opening") == 0

    book = Library.load(repo).get("second-book")
    assert book.title == "Second Book"
    assert book.status == "idea"
    assert book.logline == "A pitch."
    assert [c.title for c in book.chapters] == ["Opening"]
    assert (book.root / "chapters" / "ch01.md").exists()
    assert "Outline for second-book." in (book.root / "outline.md").read_text(encoding="utf-8")


def test_new_book_derives_a_slug_from_the_title(repo: Path):
    assert run(repo, "new", "--title", "The Long Way Home!") == 0
    assert Library.load(repo).get("the-long-way-home").title == "The Long Way Home!"


def test_added_chapters_take_the_next_free_number(repo: Path):
    run(repo, "add-chapter", "sample", "--title", "Third")
    book = Library.load(repo).get("sample")
    assert book.chapter(3) is not None
    assert (book.root / "chapters" / "ch03.md").exists()


def test_duplicate_book_is_rejected(repo: Path, capsys):
    assert run(repo, "new", "sample", "--title", "Clash") == 2
    assert "already exists" in capsys.readouterr().err


def test_bad_slug_is_rejected(repo: Path):
    with pytest.raises(ScaffoldError, match="not a valid slug"):
        new_book(repo / "library", "Not A Slug", "T", repo / "library" / "_template")


def test_a_broken_template_leaves_nothing_behind(repo: Path):
    """A failed scaffold must not leave a half-built book on the shelf."""
    template = repo / "library" / "_template"
    (template / "book.yml").unlink()
    with pytest.raises(ScaffoldError, match="not usable"):
        new_book(repo / "library", "doomed", "Doomed", template)
    assert not (repo / "library" / "doomed").exists()
    assert [book.slug for book in Library.load(repo).books] == ["sample"]


def test_template_is_not_listed_as_a_book(repo: Path):
    assert [book.slug for book in Library.load(repo).books] == ["sample"]


def test_missing_library_is_reported(tmp_path: Path, monkeypatch):
    empty = tmp_path / "empty"
    empty.mkdir()
    monkeypatch.chdir(empty)
    with pytest.raises(LibraryError, match="no library/ directory"):
        Library.load()


def test_root_is_found_from_inside_a_book(repo: Path, monkeypatch):
    monkeypatch.chdir(repo / "library" / "sample" / "chapters")
    assert find_root() == repo


def test_a_folder_spelled_like_the_library_is_not_one(tmp_path: Path, monkeypatch):
    # macOS has /Library and ~/Library on a case-insensitive filesystem, which
    # Path.is_dir() cannot tell from library/. Only the exact spelling counts.
    (tmp_path / "Library").mkdir()
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)
    with pytest.raises(LibraryError, match="no library/ directory"):
        find_root()


def test_slugify():
    assert slugify("The Impairment: A Novel") == "the-impairment-a-novel"
    assert slugify("  Spaces   and --- dashes ") == "spaces-and-dashes"
