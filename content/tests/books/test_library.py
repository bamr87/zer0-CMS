"""The read model, the validator, statistics and the manuscript (books/library.py,
books/context.py) hold to bookshelf's behaviour:

- every validation code on the fixtures its own suite used (packages/books/
  tests/test_validate.py and test_models.py), run on a book's file set;
- on the real library, through the platform (import, then everything computed
  from the rendered files), exactly what bookshelf said: `golden/bookshelf.json`
  was recorded from packages/books/src on 2026-10-22 (validate, book_to_dict,
  build with and without the outline, and the assistant's context for the book
  and for each chapter), before the package is retired (PLAN G11).
"""

import hashlib
import json
from pathlib import Path

import pytest

from books import context, library, services
from books.library import Book, Chapter, has_errors, validate

from .conftest import BOOK_YML, chapter_text

GOLDEN = json.loads((Path(__file__).parent / "golden" / "bookshelf.json").read_text(encoding="utf-8"))
NAV = {1: "- [Next Chapter: Later](ch02.md)\n", 2: "- [Previous Chapter: Earlier](ch01.md)\n"}


def sample_tree(**changes) -> dict[str, str]:
    tree = {
        "book.yml": BOOK_YML,
        "outline.md": "# A Sample Book\n\nAn outline.\n",
        "chapters/ch01.md": chapter_text(1) + NAV[1],
        "chapters/ch02.md": chapter_text(2) + NAV[2],
    }
    for path, text in changes.items():
        if text is None:
            tree.pop(path)
        else:
            tree[path] = text
    return tree


def codes(tree, level=None, slug="sample") -> set[str]:
    return {i.code for i in validate(Book.read(slug, tree)) if level is None or i.level == level}


# ── each check, on a fixture ───────────────────────────────────────────────


def test_a_clean_book_has_no_errors():
    issues = validate(Book.read("sample", sample_tree()))
    assert not has_errors(issues), [i.format() for i in issues]


def test_numbering_checks():
    assert "chapter-filename" in codes(sample_tree(**{"chapters/ch02.md": None, "chapters/ch2.md": chapter_text(2)}))
    assert "chapter-gap" in codes(sample_tree(**{"chapters/ch05.md": chapter_text(5)}), "error")
    assert "chapter-duplicate" in codes(sample_tree(**{"chapters/ch03.md": chapter_text(3, number=2)}), "error")
    assert "chapter-number-mismatch" in codes(sample_tree(**{"chapters/ch03.md": chapter_text(3, number=9)}))
    assert "chapter-number" in codes(sample_tree(**{"chapters/ch03.md": chapter_text(3, number="x")}), "error")


def test_prose_checks():
    placeholder = chapter_text(2, prose="Ana counted the [Company Name] chairs.") + NAV[2]
    assert "placeholder" in codes(sample_tree(**{"chapters/ch02.md": placeholder}), "error")
    meta = chapter_text(2, prose="Ana counted the chairs one final time (Chapter 8).") + NAV[2]
    issues = validate(Book.read("sample", sample_tree(**{"chapters/ch02.md": meta})))
    assert "meta-reference" in {i.code for i in issues if i.level == "warning"} and not has_errors(issues)


def test_link_checks():
    wrong = (chapter_text(1) + NAV[1]).replace("(ch02.md)", "(ch03.md)")
    assert "nav-wrong" in codes(sample_tree(**{"chapters/ch01.md": wrong, "chapters/ch03.md": chapter_text(3)}))
    broken = chapter_text(1) + NAV[1] + "- [Outline](../nope.md)\n"
    assert "broken-link" in codes(sample_tree(**{"chapters/ch01.md": broken}), "error")
    fine = chapter_text(1) + NAV[1] + "- [Outline](../outline.md)\n- [Away](../../docs/x.md)\n"
    assert "broken-link" not in codes(sample_tree(**{"chapters/ch01.md": fine}))
    assert "nav-missing" in codes(sample_tree(**{"chapters/ch01.md": chapter_text(1)}), "warning")
    dangling = chapter_text(2) + NAV[2] + "- [Next Chapter: None](ch03.md)\n"
    assert "nav-dangling" in codes(sample_tree(**{"chapters/ch02.md": dangling}), "warning")


def test_drift_and_cast_checks():
    drift = sample_tree(
        **{"chapters/ch03.md": chapter_text(3), "chapters/ch04.md": chapter_text(4, pov="First person")}
    )
    issues = [i for i in validate(Book.read("sample", drift)) if i.code == "pov-drift"]
    assert len(issues) == 1 and "Third person limited" in issues[0].message
    assert issues[0].path == "sample/chapters/ch04.md"
    era = sample_tree(**{"chapters/ch03.md": chapter_text(3), "chapters/ch04.md": chapter_text(4, era="1999")})
    assert "era-drift" in codes(era, "warning")
    unknown = sample_tree(**{"chapters/ch03.md": chapter_text(3, characters=["Ana", "Someone Unlisted"])})
    found = [i for i in validate(Book.read("sample", unknown)) if i.code == "unknown-character"]
    assert len(found) == 1 and "Someone Unlisted" in found[0].message


def test_manifest_and_front_matter_checks():
    assert "book-status" in codes(sample_tree(**{"book.yml": BOOK_YML.replace("drafting", "wip")}), "error")
    assert "book-slug" in codes(sample_tree(**{"book.yml": BOOK_YML.replace("slug: sample", "slug: other")}))
    assert "book-missing-key" in codes(sample_tree(**{"book.yml": "status: drafting\n"}), "error")
    assert "book-logline" in codes(sample_tree(**{"book.yml": BOOK_YML.replace("logline:", "x:")}), "warning")
    assert codes(sample_tree(**{"book.yml": None})) == {"book-config"}
    assert "outline-missing" in codes(sample_tree(**{"outline.md": None}), "error")
    idea = sample_tree(**{"book.yml": BOOK_YML.replace("drafting", "idea"), "outline.md": None})
    assert "outline-missing" in codes(idea, "warning") and not has_errors(validate(Book.read("sample", idea)))
    empty = {"book.yml": BOOK_YML, "outline.md": "x\n"}
    assert "book-no-chapters" in codes(empty, "warning")
    broken = "---\ntitle: x\n\nnever closed\n"
    assert "front-matter" in codes(sample_tree(**{"chapters/ch02.md": broken}), "error")
    assert "chapter-status" in codes(sample_tree(**{"chapters/ch02.md": chapter_text(2, status="wip")}), "error")
    assert "chapter-act" in codes(sample_tree(**{"chapters/ch02.md": chapter_text(2, act=7)}), "error")
    no_title = "---\nnumber: 2\n---\n\n## Chapter Body\n\nText.\n"
    assert "chapter-missing-key" in codes(sample_tree(**{"chapters/ch02.md": no_title}), "error")


def test_prose_is_what_the_chapter_body_holds():
    text = chapter_text(8, prose="The archive answered on the third try.")
    chapter = Chapter.read("b/chapters/ch08.md", text)
    assert chapter.prose.strip().startswith("The archive answered") and "Scaffolding" not in chapter.prose
    assert chapter.word_count == library.count_words("The archive answered on the third try.\n\n---")
    fallback = library.prose_of("\n## Notes\n\nSome narrative.\n\n## Links and References\n\n- a link\n")
    assert "Some narrative" in fallback and "a link" not in fallback
    single = Chapter.read("b/chapters/ch04.md", "---\ntitle: t\ncharacter: Kareem\n---\n\nText.\n")
    assert (single.number, single.characters) == (4, ["Kareem"])  # the filename's number, the singular key read


# ── the real library, through the platform, against bookshelf ──────────────


@pytest.mark.django_db
def test_the_platform_says_what_bookshelf_said_about_the_real_library(impairment):
    golden = GOLDEN["impairment"]
    rm = services.read(impairment)
    assert [i.as_dict() for i in validate(rm)] == golden["issues"]
    data = library.book_to_dict(rm)
    data.pop("path")
    for chapter in data["chapters"]:
        chapter.pop("path")
    assert data == golden["book"]
    for include, key in ((False, "manuscript"), (True, "manuscript_with_outline")):
        text = library.manuscript(rm, include_outline=include)
        assert hashlib.sha256(text.encode()).hexdigest() == golden[key]["sha256"]
        assert len(text.encode()) == golden[key]["bytes"]
    assert library.manuscript(rm).splitlines()[:12] == golden["manuscript"]["head"]
    for chapter in [None, *rm.chapters]:
        expected = golden["context"]["book" if chapter is None else f"ch{chapter.number:02d}"]
        assert hashlib.sha256(context.brief(rm).encode()).hexdigest() == expected["brief_sha256"]
        assert hashlib.sha256(context.local(rm, chapter).encode()).hexdigest() == expected["local_sha256"]


@pytest.mark.django_db
def test_stats_are_narrative_only_and_progress_is_against_the_target(impairment):
    stats = services.stats(services.read(impairment))
    assert stats["chapters"] == 14 and stats["status_counts"] == {"draft": 14}
    assert (stats["word_count"], stats["target_word_count"], stats["average"]) == (10096, 90000, 721)
    assert stats["longest"] == {"number": 1, "title": "The Last Day in the Plant", "word_count": 1225}
    assert stats["shortest"] == {"number": 13, "title": "Impairment", "word_count": 520}
    assert stats["progress"] == 0.1122


def test_the_context_carries_the_books_own_material():
    tree = sample_tree(
        **{
            "chapters/ch03.md": chapter_text(3),
            "guides/act-1-chapters-01-02.md": "# Act I guide\n\nOpen cold.\n",
            "guides/act-2-chapters-03-04.md": "# Act II guide\n\nRaise the stakes.\n",
            "notes/characters.md": "# Cast\n\nAna is the protagonist.\n",
            "notes/continuity.md": "# Ledger\n\nThe door is always green.\n",
            "notes/style-guide.md": "Short sentences.\n",
        }
    )
    book = Book.read("sample", tree)
    brief = context.brief(book)
    for text in ("A Sample Book", "Ana is the protagonist.", "The door is always green.", "An outline.", "Short "):
        assert text in brief
    assert "Cast (the only names you may use): Ana, Boris" in brief
    assert "Act II guide" in context.local(book, book.chapter(3)) and "Act I guide" not in context.local(
        book, book.chapter(3)
    )
    assert "Act I guide" in context.local(book, book.chapter(1))  # act-2-chapters-03-04 covers 3–4, not 2
    near = context.local(book, book.chapter(2))
    assert "Previous chapter: Chapter 1" in near and "Next chapter: Chapter 3" in near
    request = context.request(book, book.chapter(2), context.TASKS["revise"], instruction="Tighter.", selection="Ana")
    assert request.index("# Book brief") < request.index("# Nearby material") < request.index("# The chapter")
    assert request.endswith("# Additional instruction\n\nSELECTION:\n\nAna\n\nTighter.")
    assert context.local(book, None) == ""
