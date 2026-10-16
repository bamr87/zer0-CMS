"""Validator behaviour, one test per check that the impairment audit produced."""

from __future__ import annotations

from pathlib import Path

from bookshelf.library import Library
from bookshelf.models import Book
from bookshelf.validate import has_errors, validate_book
from conftest import write_chapter


def codes(issues, level=None):
    return {issue.code for issue in issues if level is None or issue.level == level}


def load(repo: Path) -> Book:
    return Library.load(repo).get("sample")


def test_clean_book_has_no_errors(repo: Path):
    issues = validate_book(load(repo))
    assert not has_errors(issues), [i.format(repo) for i in issues]


def test_unpadded_filename_is_an_error(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    (chapters / "ch02.md").rename(chapters / "ch2.md")
    assert "chapter-filename" in codes(validate_book(load(repo)), "error")


def test_gap_in_numbering_is_an_error(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 5)
    assert "chapter-gap" in codes(validate_book(load(repo)), "error")


def test_duplicate_number_is_an_error(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 3, number=2)
    assert "chapter-duplicate" in codes(validate_book(load(repo)), "error")


def test_number_disagreeing_with_filename_is_an_error(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 3, number=9)
    issues = validate_book(load(repo))
    assert "chapter-number-mismatch" in codes(issues, "error")


def test_placeholder_in_prose_is_an_error(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    path = chapters / "ch02.md"
    path.write_text(path.read_text(encoding="utf-8").replace("empty chairs", "[Company Name] chairs"), encoding="utf-8")
    assert "placeholder" in codes(validate_book(load(repo)), "error")


def test_meta_reference_in_prose_is_a_warning(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    path = chapters / "ch02.md"
    text = path.read_text(encoding="utf-8").replace("final time.", "final time (Chapter 8).")
    path.write_text(text, encoding="utf-8")
    issues = validate_book(load(repo))
    assert "meta-reference" in codes(issues, "warning")
    assert not has_errors(issues)


def test_wrong_next_link_is_an_error(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 3)
    path = chapters / "ch01.md"
    path.write_text(path.read_text(encoding="utf-8").replace("(ch02.md)", "(ch03.md)"), encoding="utf-8")
    assert "nav-wrong" in codes(validate_book(load(repo)), "error")


def test_broken_relative_link_is_an_error(repo: Path):
    path = repo / "library" / "sample" / "chapters" / "ch01.md"
    path.write_text(path.read_text(encoding="utf-8") + "\n- [Outline](../nope.md)\n", encoding="utf-8")
    assert "broken-link" in codes(validate_book(load(repo)), "error")


def test_pov_drift_warns_and_names_the_majority(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 3)
    write_chapter(chapters, 4, pov="First person")
    issues = [i for i in validate_book(load(repo)) if i.code == "pov-drift"]
    assert len(issues) == 1
    assert "Third person limited" in issues[0].message
    assert issues[0].path.name == "ch04.md"


def test_era_drift_warns(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 3)
    write_chapter(chapters, 4, era="Early 2000s")
    assert "era-drift" in codes(validate_book(load(repo)), "warning")


def test_unknown_character_warns_against_the_cast(repo: Path):
    chapters = repo / "library" / "sample" / "chapters"
    write_chapter(chapters, 3, characters=["Ana", "Someone Unlisted"])
    issues = [i for i in validate_book(load(repo)) if i.code == "unknown-character"]
    assert len(issues) == 1
    assert "Someone Unlisted" in issues[0].message


def test_bad_status_values_are_errors(repo: Path):
    book_yml = repo / "library" / "sample" / "book.yml"
    text = book_yml.read_text(encoding="utf-8").replace("status: drafting", "status: wip")
    book_yml.write_text(text, encoding="utf-8")
    assert "book-status" in codes(validate_book(load(repo)), "error")


def test_missing_outline_is_an_error_once_drafting(repo: Path):
    (repo / "library" / "sample" / "outline.md").unlink()
    assert "outline-missing" in codes(validate_book(load(repo)), "error")


def test_missing_outline_is_only_a_warning_for_an_idea(repo: Path):
    book_yml = repo / "library" / "sample" / "book.yml"
    text = book_yml.read_text(encoding="utf-8").replace("status: drafting", "status: idea")
    book_yml.write_text(text, encoding="utf-8")
    (repo / "library" / "sample" / "outline.md").unlink()
    issues = validate_book(load(repo))
    assert "outline-missing" in codes(issues, "warning")
    assert not has_errors(issues)


def test_slug_mismatch_is_an_error(repo: Path):
    book_yml = repo / "library" / "sample" / "book.yml"
    book_yml.write_text(book_yml.read_text(encoding="utf-8").replace("slug: sample", "slug: other"), encoding="utf-8")
    assert "book-slug" in codes(validate_book(load(repo)), "error")


def test_unparseable_front_matter_is_reported_not_raised(repo: Path):
    path = repo / "library" / "sample" / "chapters" / "ch02.md"
    path.write_text("---\ntitle: x\n\nnever closed\n", encoding="utf-8")
    assert "front-matter" in codes(validate_book(load(repo)), "error")
