"""Chapter and book read-model behaviour: prose extraction and measurement."""

from __future__ import annotations

from pathlib import Path

from bookshelf.models import Chapter, as_list, count_words, normalise_keys, prose_of

CHAPTER = """\
---
title: The Backup
number: 8
character: Kareem
---

## Outline and Contextual Alignment

Scaffolding words that should not be counted as prose.

## Chapter Body

The archive answered on the third try.

## References & Contextual Alignment

More scaffolding that should not be counted.

## Links and References

- [Next Chapter: Later](ch09.md)
"""


def test_prose_excludes_scaffolding():
    prose = prose_of(CHAPTER.split("---\n", 2)[2])
    assert "archive answered" in prose
    assert "Scaffolding words" not in prose
    assert "More scaffolding" not in prose


def test_prose_falls_back_when_there_is_no_chapter_body_heading():
    body = "\n## Notes\n\nSome narrative.\n\n## Links and References\n\n- a link\n"
    prose = prose_of(body)
    assert "Some narrative" in prose
    assert "a link" not in prose


def test_word_count_measures_prose_only(tmp_path: Path):
    path = tmp_path / "ch08.md"
    path.write_text(CHAPTER, encoding="utf-8")
    chapter = Chapter.load(path)
    assert chapter.word_count == count_words("The archive answered on the third try.")
    assert chapter.total_word_count > chapter.word_count


def test_singular_character_key_is_read_as_characters(tmp_path: Path):
    path = tmp_path / "ch08.md"
    path.write_text(CHAPTER, encoding="utf-8")
    assert Chapter.load(path).characters == ["Kareem"]


def test_number_falls_back_to_the_filename(tmp_path: Path):
    path = tmp_path / "ch04.md"
    path.write_text("---\ntitle: No number here\n---\n\nText.\n", encoding="utf-8")
    chapter = Chapter.load(path)
    assert chapter.number == 4
    assert chapter.filename_number == 4


def test_find_reports_absolute_file_line_numbers(tmp_path: Path):
    path = tmp_path / "ch01.md"
    path.write_text(CHAPTER, encoding="utf-8")
    chapter = Chapter.load(path)
    hits = chapter.find(__import__("re").compile(r"archive answered"))
    assert hits, "expected the prose match to be found"
    line = hits[0][0]
    assert CHAPTER.splitlines()[line - 1].startswith("The archive answered")


def test_meta_references_ignore_the_outline_section(tmp_path: Path):
    text = (
        "---\ntitle: t\nnumber: 1\n---\n\n"
        "## Outline and Contextual Alignment\n\nSet up in (Chapter 2) as planned.\n\n"
        "## Chapter Body\n\nHe remembered the deal (Chapter 2) and said nothing.\n"
    )
    path = tmp_path / "ch01.md"
    path.write_text(text, encoding="utf-8")
    hits = Chapter.load(path).meta_references
    assert len(hits) == 1
    line = hits[0][0]
    assert text.splitlines()[line - 1].startswith("He remembered")


def test_placeholders_are_detected(tmp_path: Path):
    path = tmp_path / "ch14.md"
    path.write_text(
        "---\ntitle: t\nnumber: 14\n---\n\n## Chapter Body\n\nEvidence against [Company Name] and [CFO's Name].\n",
        encoding="utf-8",
    )
    found = [text for _line, text in Chapter.load(path).placeholders]
    assert "[Company Name]" in found
    assert "[CFO's Name]" in found


def test_as_list_and_normalise_keys():
    assert as_list("One, Two") == ["One", "Two"]
    assert as_list(["A", " B "]) == ["A", "B"]
    assert as_list(None) == []
    assert normalise_keys({"character": "x", "title": "y"}) == {"characters": "x", "title": "y"}
