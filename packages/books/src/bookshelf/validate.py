"""Checks that keep a book internally consistent as it grows.

Every check exists because the ``impairment`` draft tripped over it: unnamed
placeholders left in finished prose, outline bookkeeping leaking into a
character's dialogue, a point of view that silently flipped between chapters,
prev/next links pointing at the wrong file. See ``docs/reviews/`` for the audit
that produced this list.

Errors fail ``books validate``; warnings are reported and do not.
"""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

from .models import (
    BOOK_REQUIRED,
    BOOK_STATUSES,
    CHAPTER_RECOMMENDED,
    CHAPTER_REQUIRED,
    CHAPTER_STATUSES,
    Book,
    Chapter,
    Issue,
    chapter_filename,
)

ERROR = "error"
WARNING = "warning"

_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_NEXT_LINK = re.compile(r"\[\s*next chapter[^\]]*\]\(([^)\s]+)\)", re.IGNORECASE)
_PREV_LINK = re.compile(r"\[\s*previous chapter[^\]]*\]\(([^)\s]+)\)", re.IGNORECASE)


def validate_book(book: Book) -> list[Issue]:
    """Run every check against *book* and return the findings."""
    issues: list[Issue] = []
    config = book.root / Book.CONFIG

    if book.load_error:
        issues.append(Issue(ERROR, "book-config", book.load_error, config))
        return issues

    issues += _check_book_meta(book, config)
    issues += _check_outline(book)
    issues += _check_numbering(book)
    for chapter in book.chapters:
        issues += _check_chapter(book, chapter)
    issues += _check_consistency(book)
    return issues


def validate_all(books: list[Book]) -> list[Issue]:
    issues: list[Issue] = []
    for book in books:
        issues += validate_book(book)
    return issues


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == ERROR for issue in issues)


# -- book level -----------------------------------------------------------
def _check_book_meta(book: Book, config: Path) -> list[Issue]:
    issues: list[Issue] = []
    for key in BOOK_REQUIRED:
        if not book.meta.get(key):
            issues.append(Issue(ERROR, "book-missing-key", f"book.yml is missing required key {key!r}", config))
    if book.status not in BOOK_STATUSES:
        issues.append(
            Issue(ERROR, "book-status", f"status {book.status!r} is not one of {', '.join(BOOK_STATUSES)}", config)
        )
    declared = book.meta.get("slug")
    if declared and str(declared) != book.slug:
        issues.append(
            Issue(ERROR, "book-slug", f"slug {declared!r} does not match directory name {book.slug!r}", config)
        )
    if not book.logline:
        issues.append(Issue(WARNING, "book-logline", "no logline; `books list` has nothing to show", config))
    if book.status != "idea" and not book.chapters:
        issues.append(
            Issue(WARNING, "book-no-chapters", f"status is {book.status!r} but no chapters exist yet", config)
        )
    return issues


def _check_outline(book: Book) -> list[Issue]:
    if book.outline_path.exists():
        return []
    level = WARNING if book.status == "idea" else ERROR
    return [Issue(level, "outline-missing", f"no {Book.OUTLINE} for this book", book.outline_path)]


def _check_numbering(book: Book) -> list[Issue]:
    issues: list[Issue] = []
    seen: dict[int, Path] = {}
    for chapter in book.chapters:
        number = chapter.number
        if number is None:
            issues.append(Issue(ERROR, "chapter-number", "chapter has no usable number", chapter.path))
            continue
        expected = chapter_filename(number)
        if chapter.path.name != expected:
            issues.append(
                Issue(
                    ERROR,
                    "chapter-filename",
                    f"chapter {number} should be named {expected} so files sort in reading order",
                    chapter.path,
                )
            )
        if chapter.filename_number is not None and chapter.filename_number != number:
            issues.append(
                Issue(
                    ERROR,
                    "chapter-number-mismatch",
                    f"front matter says number {number} but the filename says {chapter.filename_number}",
                    chapter.path,
                )
            )
        if number in seen:
            issues.append(
                Issue(
                    ERROR,
                    "chapter-duplicate",
                    f"chapter number {number} is also used by {seen[number].name}",
                    chapter.path,
                )
            )
        seen[number] = chapter.path

    numbers = sorted(seen)
    if numbers:
        missing = [n for n in range(1, numbers[-1] + 1) if n not in seen]
        if missing:
            gaps = ", ".join(str(n) for n in missing)
            issues.append(
                Issue(
                    ERROR,
                    "chapter-gap",
                    f"chapter numbers are not contiguous; missing {gaps}",
                    book.root / Book.CHAPTER_DIR,
                )
            )
    return issues


# -- chapter level --------------------------------------------------------
def _check_chapter(book: Book, chapter: Chapter) -> list[Issue]:
    issues: list[Issue] = []
    if chapter.parse_error:
        return [Issue(ERROR, "front-matter", chapter.parse_error, chapter.path, line=1)]

    for key in CHAPTER_REQUIRED:
        if key not in chapter.meta and not (key == "number" and chapter.filename_number is not None):
            issues.append(
                Issue(ERROR, "chapter-missing-key", f"front matter is missing required key {key!r}", chapter.path, 1)
            )
    for key in CHAPTER_RECOMMENDED:
        if not chapter.meta.get(key):
            issues.append(Issue(WARNING, "chapter-missing-key", f"front matter has no {key!r}", chapter.path, 1))

    if chapter.status not in CHAPTER_STATUSES:
        issues.append(
            Issue(
                ERROR,
                "chapter-status",
                f"status {chapter.status!r} is not one of {', '.join(CHAPTER_STATUSES)}",
                chapter.path,
                1,
            )
        )
    act = chapter.act
    if act is not None and not 1 <= act <= book.acts:
        issues.append(Issue(ERROR, "chapter-act", f"act {act} is outside the book's {book.acts} acts", chapter.path, 1))

    for line, text in chapter.placeholders:
        issues.append(
            Issue(ERROR, "placeholder", f"unresolved placeholder {text} left in the file", chapter.path, line)
        )
    for line, text in chapter.meta_references:
        issues.append(
            Issue(
                WARNING,
                "meta-reference",
                f"outline bookkeeping {text} appears inside the narrative prose",
                chapter.path,
                line,
            )
        )

    unknown = [name for name in chapter.characters if book.cast and name not in book.cast]
    for name in unknown:
        issues.append(
            Issue(
                WARNING,
                "unknown-character",
                f"{name!r} is not in the book's cast; add it to book.yml or fix the spelling",
                chapter.path,
                1,
            )
        )

    issues += _check_links(book, chapter)
    return issues


def _check_links(book: Book, chapter: Chapter) -> list[Issue]:
    issues: list[Issue] = []
    number = chapter.number
    for pattern, delta, label in ((_PREV_LINK, -1, "previous"), (_NEXT_LINK, 1, "next")):
        match = pattern.search(chapter.body)
        if not match:
            if number is not None and book.chapter(number + delta) is not None:
                issues.append(Issue(WARNING, "nav-missing", f"no link to the {label} chapter", chapter.path))
            continue
        target = match.group(1)
        if number is None:
            continue
        neighbour = book.chapter(number + delta)
        if neighbour is None:
            issues.append(
                Issue(WARNING, "nav-dangling", f"links to a {label} chapter that does not exist", chapter.path)
            )
            continue
        if target != neighbour.path.name:
            issues.append(
                Issue(
                    ERROR,
                    "nav-wrong",
                    f"{label} link points at {target} but chapter {number + delta} is {neighbour.path.name}",
                    chapter.path,
                )
            )

    for match in _LINK.finditer(chapter.body):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = (chapter.path.parent / target.split("#", 1)[0]).resolve()
        if not resolved.exists():
            line = chapter.body.count("\n", 0, match.start()) + 1 + chapter.body_offset
            issues.append(Issue(ERROR, "broken-link", f"relative link {target!r} does not resolve", chapter.path, line))
    return issues


# -- cross-chapter consistency -------------------------------------------
def _check_consistency(book: Book) -> list[Issue]:
    """Flag a field that is near-uniform across chapters but not quite.

    A single odd point of view or era is far more often a mistake than a
    deliberate choice, so the minority value gets a warning naming the majority.
    """
    issues: list[Issue] = []
    for field in ("pov", "era"):
        values = [(chapter, str(chapter.meta.get(field) or "").strip()) for chapter in book.chapters]
        present = [(chapter, value) for chapter, value in values if value]
        if len(present) < 3:
            continue
        counts = Counter(value for _chapter, value in present)
        majority, majority_count = counts.most_common(1)[0]
        if majority_count <= len(present) / 2:
            continue
        for chapter, value in present:
            if value != majority:
                issues.append(
                    Issue(
                        WARNING,
                        f"{field}-drift",
                        f"{field} is {value!r} but {majority_count} of {len(present)} chapters use {majority!r}",
                        chapter.path,
                        1,
                    )
                )
    return issues
