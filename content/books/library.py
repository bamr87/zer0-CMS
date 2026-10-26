"""The read model over a book's file set: chapters, prose, word counts, the
validator and the compiled manuscript — bookshelf's (packages/books/src) rules,
kept so its validation codes, its narrative-only word counts and its manuscript
layout stay what a writer already knows (docs/SCHEMA.md in that package).

It reads a `Tree` — a book's files as `{path inside the book: text}` — rather
than a directory, so the platform validates, measures and builds a book from
the same text `export_books` writes (books/files.py renders a book's tree from
the database). Paths in findings are relative to the library directory
(`impairment/chapters/ch07.md`), line numbers are the file's own.

What differs from bookshelf: front matter is parsed with the platform's loader,
which keeps dates as strings (nothing here reads a date); and a relative link
that leaves the book's directory is not checked, because the generated set is
the book's files and nothing else.
"""

from __future__ import annotations

import posixpath
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import yaml

from importers.frontmatter import _Loader

Tree = dict[str, str]

BOOK_STATUSES = ("idea", "outlining", "drafting", "revising", "complete", "archived")
CHAPTER_STATUSES = ("stub", "outline", "draft", "revised", "final")
CHAPTER_REQUIRED = ("title", "number")
CHAPTER_RECOMMENDED = ("subtitle", "act", "status", "pov", "characters", "setting", "era", "tone", "style")
BOOK_REQUIRED = ("title", "status")
KEY_ALIASES = {"character": "characters", "settings": "setting", "theme": "themes"}
SCAFFOLD_HEADINGS = (
    "outline and contextual alignment",
    "references & contextual alignment",
    "references and contextual alignment",
    "links and references",
    "suggested minor updates",
    "suggested updates",
)
PROSE_HEADINGS = ("chapter body", "body")
CONFIG, OUTLINE, CHAPTER_DIR = "book.yml", "outline.md", "chapters"
CHARACTERS, CONTINUITY, STYLE_GUIDE = "notes/characters.md", "notes/continuity.md", "notes/style-guide.md"
ERROR, WARNING = "error", "warning"

HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$", re.MULTILINE)
CHAPTER_FILE = re.compile(r"^ch(\d+)\.md$")
WORD = re.compile(r"[A-Za-z0-9'’-]+")
PLACEHOLDER = re.compile(r"\[(?:[A-Z][A-Za-z']*\s+){0,3}(?:Name|NAME|TBD|TODO|Placeholder)[^\]]*\]")
META_REF = re.compile(r"\((?:Ch\.?|Chapter)\s*\.?\s*\d+\)", re.IGNORECASE)
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
NEXT_LINK = re.compile(r"\[\s*next chapter[^\]]*\]\(([^)\s]+)\)", re.IGNORECASE)
PREV_LINK = re.compile(r"\[\s*previous chapter[^\]]*\]\(([^)\s]+)\)", re.IGNORECASE)


class FrontMatterError(ValueError):
    pass


def split(text: str) -> tuple[str | None, str]:
    """`(raw front matter, body)`; the first is None when the file has none."""
    if not text.startswith("---"):
        return None, text
    lines = text.splitlines(keepends=True)
    if lines[0].strip() != "---":
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise FrontMatterError("front matter opened with '---' but was never closed")


def loads(raw: str) -> dict:
    try:
        loaded = yaml.load(raw, Loader=_Loader)  # noqa: S506 — _Loader is a SafeLoader without timestamps
    except yaml.YAMLError as exc:
        raise FrontMatterError(str(exc)) from exc
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise FrontMatterError("front matter must be a mapping of keys to values")
    return loaded


def normalise_keys(meta: dict) -> dict:
    return {KEY_ALIASES.get(key, key): value for key, value in meta.items()}


def as_list(value: Any) -> list[str]:
    """A scalar-or-list value as a list of strings ("A, B" is two)."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()] if "," in text else [text]


def as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def count_words(text: str) -> int:
    return len(WORD.findall(text))


def prose_spans(body: str) -> list[tuple[int, int]]:
    """Character ranges of `body` that hold narrative prose: the "Chapter Body"
    section with everything nested under it, else everything not under a
    scaffold heading."""
    headings = list(HEADING.finditer(body))
    if not headings:
        return [(0, len(body))]
    levels = [len(match.group(1)) for match in headings]
    titles = [match.group(2).strip().lower() for match in headings]

    def subtree_end(index: int) -> int:
        for other in range(index + 1, len(headings)):
            if levels[other] <= levels[index]:
                return headings[other].start()
        return len(body)

    named = [i for i, title in enumerate(titles) if any(title.startswith(p) for p in PROSE_HEADINGS)]
    if named:
        return [(headings[i].end(), subtree_end(i)) for i in named]
    spans, index = [], 0
    while index < len(headings):
        if any(titles[index].startswith(p) for p in SCAFFOLD_HEADINGS):
            end = subtree_end(index)
            while index < len(headings) and headings[index].start() < end:
                index += 1
            continue
        following = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        spans.append((headings[index].end(), following))
        index += 1
    return spans


def prose_of(body: str) -> str:
    return "\n".join(body[start:end] for start, end in prose_spans(body))


@dataclass(frozen=True)
class Issue:
    level: str
    code: str
    message: str
    path: str
    line: int | None = None

    def format(self) -> str:
        where = f"{self.path}:{self.line}" if self.line else self.path
        return f"{self.level:>7}  {where}  [{self.code}] {self.message}"

    def as_dict(self) -> dict:
        return {"level": self.level, "code": self.code, "message": self.message, "path": self.path, "line": self.line}


@dataclass
class Chapter:
    path: str  # relative to the library directory
    meta: dict
    body: str
    body_offset: int = 0
    parse_error: str | None = None

    @classmethod
    def read(cls, path: str, text: str) -> Chapter:
        try:
            raw, body = split(text)
            meta = loads(raw) if raw is not None else {}
        except FrontMatterError as exc:
            return cls(path=path, meta={}, body=text, parse_error=str(exc))
        offset = 0 if raw is None else raw.count("\n") + 2
        return cls(path=path, meta=normalise_keys(meta), body=body, body_offset=offset)

    @property
    def filename(self) -> str:
        return posixpath.basename(self.path)

    @property
    def filename_number(self) -> int | None:
        match = CHAPTER_FILE.match(self.filename)
        return int(match.group(1)) if match else None

    @property
    def number(self) -> int | None:
        return as_int(self.meta.get("number", self.filename_number))

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or posixpath.splitext(self.filename)[0])

    @property
    def subtitle(self) -> str:
        return str(self.meta.get("subtitle") or "")

    @property
    def act(self) -> int | None:
        return as_int(self.meta.get("act"))

    @property
    def status(self) -> str:
        return str(self.meta.get("status") or "draft")

    @property
    def pov(self) -> str:
        return str(self.meta.get("pov") or "")

    @property
    def era(self) -> str:
        return str(self.meta.get("era") or "")

    @property
    def characters(self) -> list[str]:
        return as_list(self.meta.get("characters"))

    @property
    def prose(self) -> str:
        return prose_of(self.body)

    @property
    def word_count(self) -> int:
        return count_words(self.prose)

    def find(self, pattern: re.Pattern[str], prose_only: bool = True) -> list[tuple[int, str]]:
        """`(file line, matched text)` for each hit; with `prose_only`, outside the scaffolding only."""
        spans = prose_spans(self.body) if prose_only else [(0, len(self.body))]
        hits = []
        for match in pattern.finditer(self.body):
            if any(start <= match.start() < end for start, end in spans):
                hits.append((self.body.count("\n", 0, match.start()) + 1 + self.body_offset, match.group(0)))
        return hits


@dataclass
class Book:
    slug: str
    tree: Tree
    meta: dict = field(default_factory=dict)
    chapters: list[Chapter] = field(default_factory=list)
    load_error: str | None = None

    @classmethod
    def read(cls, slug: str, tree: Tree) -> Book:
        meta, error = {}, None
        if CONFIG in tree:
            try:
                meta = normalise_keys(loads(tree[CONFIG]))
            except FrontMatterError as exc:
                error = f"{CONFIG}: {exc}"
        else:
            error = f"missing {CONFIG}"
        chapters = [Chapter.read(f"{slug}/{path}", text) for path, text in sorted(tree.items()) if is_chapter(path)]
        chapters.sort(key=lambda c: (c.number is None, c.number or 0, c.filename))
        return cls(slug=slug, tree=tree, meta=meta, chapters=chapters, load_error=error)

    def text(self, path: str) -> str:
        return self.tree.get(path, "")

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.slug)

    @property
    def status(self) -> str:
        return str(self.meta.get("status") or "idea")

    @property
    def logline(self) -> str:
        return str(self.meta.get("logline") or "")

    @property
    def genre(self) -> str:
        return str(self.meta.get("genre") or "")

    @property
    def pov(self) -> str:
        return str(self.meta.get("pov") or "")

    @property
    def cast(self) -> list[str]:
        return as_list(self.meta.get("cast"))

    @property
    def acts(self) -> int:
        return as_int(self.meta.get("acts", 3), 3)

    @property
    def planned_chapters(self) -> int:
        return as_int(self.meta.get("planned_chapters", len(self.chapters)), len(self.chapters))

    @property
    def target_word_count(self) -> int:
        return as_int(self.meta.get("target_word_count", 0), 0)

    @property
    def word_count(self) -> int:
        return sum(chapter.word_count for chapter in self.chapters)

    @property
    def progress(self) -> float:
        """The share of the word target written; without one, of the planned chapters."""
        if self.target_word_count <= 0:
            return 0.0 if self.planned_chapters <= 0 else min(1.0, len(self.chapters) / self.planned_chapters)
        return min(1.0, self.word_count / self.target_word_count)

    def status_counts(self) -> dict[str, int]:
        return dict(Counter(chapter.status for chapter in self.chapters))

    def chapter(self, number: int | None) -> Chapter | None:
        return next((c for c in self.chapters if c.number == number), None) if number is not None else None

    def exists(self, path: str) -> bool:
        """A file or a directory of the book's set."""
        path = path.rstrip("/")
        return path in ("", ".") or path in self.tree or any(p.startswith(path + "/") for p in self.tree)


def is_chapter(path: str) -> bool:
    directory, name = posixpath.split(path)
    return directory == CHAPTER_DIR and bool(CHAPTER_FILE.match(name))


def chapter_filename(number: int) -> str:
    return f"ch{number:02d}.md"


# ── validation (the codes are bookshelf's, docs/SCHEMA.md) ──────────────────


def validate(book: Book) -> list[Issue]:
    config = f"{book.slug}/{CONFIG}"
    if book.load_error:
        return [Issue(ERROR, "book-config", book.load_error, config)]
    issues = _book_meta(book, config) + _outline(book) + _numbering(book)
    for chapter in book.chapters:
        issues += _chapter(book, chapter)
    return issues + _consistency(book)


def has_errors(issues: list[Issue]) -> bool:
    return any(issue.level == ERROR for issue in issues)


def _book_meta(book: Book, config: str) -> list[Issue]:
    issues = [
        Issue(ERROR, "book-missing-key", f"book.yml is missing required key {key!r}", config)
        for key in BOOK_REQUIRED
        if not book.meta.get(key)
    ]
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


def _outline(book: Book) -> list[Issue]:
    if OUTLINE in book.tree:
        return []
    level = WARNING if book.status == "idea" else ERROR
    return [Issue(level, "outline-missing", f"no {OUTLINE} for this book", f"{book.slug}/{OUTLINE}")]


def _numbering(book: Book) -> list[Issue]:
    issues, seen = [], {}
    for chapter in book.chapters:
        number = chapter.number
        if number is None:
            issues.append(Issue(ERROR, "chapter-number", "chapter has no usable number", chapter.path))
            continue
        expected = chapter_filename(number)
        if chapter.filename != expected:
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
                    f"chapter number {number} is also used by {posixpath.basename(seen[number])}",
                    chapter.path,
                )
            )
        seen[number] = chapter.path
    numbers = sorted(seen)
    missing = [n for n in range(1, numbers[-1] + 1) if n not in seen] if numbers else []
    if missing:
        issues.append(
            Issue(
                ERROR,
                "chapter-gap",
                f"chapter numbers are not contiguous; missing {', '.join(map(str, missing))}",
                f"{book.slug}/{CHAPTER_DIR}",
            )
        )
    return issues


def _chapter(book: Book, chapter: Chapter) -> list[Issue]:
    if chapter.parse_error:
        return [Issue(ERROR, "front-matter", chapter.parse_error, chapter.path, 1)]
    issues = [
        Issue(ERROR, "chapter-missing-key", f"front matter is missing required key {key!r}", chapter.path, 1)
        for key in CHAPTER_REQUIRED
        if key not in chapter.meta and not (key == "number" and chapter.filename_number is not None)
    ]
    issues += [
        Issue(WARNING, "chapter-missing-key", f"front matter has no {key!r}", chapter.path, 1)
        for key in CHAPTER_RECOMMENDED
        if not chapter.meta.get(key)
    ]
    if chapter.status not in CHAPTER_STATUSES:
        message = f"status {chapter.status!r} is not one of {', '.join(CHAPTER_STATUSES)}"
        issues.append(Issue(ERROR, "chapter-status", message, chapter.path, 1))
    if chapter.act is not None and not 1 <= chapter.act <= book.acts:
        message = f"act {chapter.act} is outside the book's {book.acts} acts"
        issues.append(Issue(ERROR, "chapter-act", message, chapter.path, 1))
    for line, text in chapter.find(PLACEHOLDER, prose_only=False):
        issues.append(
            Issue(ERROR, "placeholder", f"unresolved placeholder {text} left in the file", chapter.path, line)
        )
    for line, text in chapter.find(META_REF):
        message = f"outline bookkeeping {text} appears inside the narrative prose"
        issues.append(Issue(WARNING, "meta-reference", message, chapter.path, line))
    for name in chapter.characters:
        if book.cast and name not in book.cast:
            message = f"{name!r} is not in the book's cast; add it to book.yml or fix the spelling"
            issues.append(Issue(WARNING, "unknown-character", message, chapter.path, 1))
    return issues + _links(book, chapter)


def _links(book: Book, chapter: Chapter) -> list[Issue]:
    issues, number = [], chapter.number
    for pattern, delta, label in ((PREV_LINK, -1, "previous"), (NEXT_LINK, 1, "next")):
        match = pattern.search(chapter.body)
        neighbour = book.chapter(number + delta) if number is not None else None
        if not match:
            if neighbour is not None:
                issues.append(Issue(WARNING, "nav-missing", f"no link to the {label} chapter", chapter.path))
            continue
        if number is None:
            continue
        if neighbour is None:
            message = f"links to a {label} chapter that does not exist"
            issues.append(Issue(WARNING, "nav-dangling", message, chapter.path))
        elif match.group(1) != neighbour.filename:
            message = f"{label} link points at {match.group(1)} but chapter {number + delta} is {neighbour.filename}"
            issues.append(Issue(ERROR, "nav-wrong", message, chapter.path))
    here = posixpath.dirname(chapter.path.split("/", 1)[1])
    for match in LINK.finditer(chapter.body):
        target = match.group(1)
        if target.startswith(("http://", "https://", "mailto:", "#")):
            continue
        resolved = posixpath.normpath(posixpath.join(here, target.split("#", 1)[0]))
        if resolved == ".." or resolved.startswith("../"):
            continue  # outside the book: the book's file set cannot answer for it
        if not book.exists(resolved):
            line = chapter.body.count("\n", 0, match.start()) + 1 + chapter.body_offset
            message = f"relative link {target!r} does not resolve"
            issues.append(Issue(ERROR, "broken-link", message, chapter.path, line))
    return issues


def _consistency(book: Book) -> list[Issue]:
    """A point of view or an era that most chapters share and one does not."""
    issues = []
    for name in ("pov", "era"):
        present = [(c, str(c.meta.get(name) or "").strip()) for c in book.chapters]
        present = [(c, value) for c, value in present if value]
        if len(present) < 3:
            continue
        majority, count = Counter(value for _c, value in present).most_common(1)[0]
        if count <= len(present) / 2:
            continue
        for chapter, value in present:
            if value != majority:
                message = f"{name} is {value!r} but {count} of {len(present)} chapters use {majority!r}"
                issues.append(Issue(WARNING, f"{name}-drift", message, chapter.path, 1))
    return issues


# ── the manuscript and the library as data ──────────────────────────────────


def manuscript(book: Book, include_outline: bool = False) -> str:
    """The narrative in order behind a title page: no front matter, no
    scaffolding, act headings, and a placeholder for an unwritten chapter."""
    lines = [f"# {book.title}"]
    if book.meta.get("subtitle"):
        lines.append(f"\n*{book.meta['subtitle']}*")
    if book.meta.get("author"):
        lines.append(f"\nby {book.meta['author']}")
    if book.logline:
        lines.append(f"\n{book.logline}")
    lines.append("\n---")
    parts = ["\n".join(lines)]
    if include_outline and OUTLINE in book.tree:
        parts += ["## Outline\n", book.tree[OUTLINE].strip(), "\n---\n"]
    current_act = None
    for chapter in book.chapters:
        if chapter.act is not None and chapter.act != current_act:
            current_act = chapter.act
            parts.append(f"## Act {roman(current_act)}\n")
        parts.append((f"### {chapter.number}. {chapter.title}" if chapter.number else f"### {chapter.title}") + "\n")
        if chapter.subtitle:
            parts.append(f"*{chapter.subtitle}*\n")
        parts.append(chapter.prose.strip() or "_(not yet written)_")
        parts.append("\n---\n")
    return "\n".join(part.rstrip() + "\n" for part in parts)


def roman(number: int) -> str:
    out, remaining = "", number
    for symbol, value in (("X", 10), ("IX", 9), ("V", 5), ("IV", 4), ("I", 1)):
        while remaining >= value:
            out, remaining = out + symbol, remaining - value
    return out or str(number)


def book_to_dict(book: Book, prefix: str = "library") -> dict:
    """A book and its chapters as data: `library.json`'s shape, paths under `prefix`."""
    return {
        "slug": book.slug,
        "title": book.title,
        "subtitle": book.meta.get("subtitle") or "",
        "status": book.status,
        "genre": book.genre,
        "logline": book.logline,
        "pov": book.pov,
        "tags": as_list(book.meta.get("tags")),
        "themes": as_list(book.meta.get("themes")),
        "cast": book.cast,
        "acts": book.acts,
        "planned_chapters": book.planned_chapters,
        "target_word_count": book.target_word_count,
        "word_count": book.word_count,
        "progress": round(book.progress, 4),
        "path": f"{prefix}/{book.slug}",
        "chapters": [
            {
                "number": c.number,
                "title": c.title,
                "subtitle": c.subtitle,
                "act": c.act,
                "status": c.status,
                "pov": c.pov,
                "era": c.era,
                "characters": c.characters,
                "setting": as_list(c.meta.get("setting")),
                "tone": as_list(c.meta.get("tone")),
                "word_count": c.word_count,
                "path": f"{prefix}/{c.path}",
            }
            for c in book.chapters
        ],
    }
