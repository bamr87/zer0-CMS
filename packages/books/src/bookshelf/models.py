"""Domain objects for the bookshelf: issues, chapters and books.

The library is plain markdown on disk. These classes are a read model over
that -- they parse, normalise and measure, but the files stay the source of
truth so a book is still usable with nothing but a text editor.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import frontmatter

#: Lifecycle a book moves through, from a one-line notion to a finished draft.
BOOK_STATUSES = ("idea", "outlining", "drafting", "revising", "complete", "archived")

#: Lifecycle of a single chapter file.
CHAPTER_STATUSES = ("stub", "outline", "draft", "revised", "final")

#: Front matter keys a chapter must define.
CHAPTER_REQUIRED = ("title", "number")

#: Keys the validator nudges authors to fill in, but does not fail on.
CHAPTER_RECOMMENDED = ("subtitle", "act", "status", "pov", "characters", "setting", "era", "tone", "style")

#: Front matter keys a book.yml must define.
BOOK_REQUIRED = ("title", "status")

#: Older files wrote these singular keys; they are read as their plural form.
KEY_ALIASES = {"character": "characters", "settings": "setting", "theme": "themes"}

#: Headings that carry planning scaffolding rather than narrative prose.
SCAFFOLD_HEADINGS = (
    "outline and contextual alignment",
    "references & contextual alignment",
    "references and contextual alignment",
    "links and references",
    "suggested minor updates",
    "suggested updates",
)

#: Heading that opens the narrative itself.
PROSE_HEADINGS = ("chapter body", "body")

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$", re.MULTILINE)
_CHAPTER_FILE = re.compile(r"^ch(\d+)\.md$")
_WORD = re.compile(r"[A-Za-z0-9'’-]+")
_PLACEHOLDER = re.compile(r"\[(?:[A-Z][A-Za-z']*\s+){0,3}(?:Name|NAME|TBD|TODO|Placeholder)[^\]]*\]")
_META_REF = re.compile(r"\((?:Ch\.?|Chapter)\s*\.?\s*\d+\)", re.IGNORECASE)


@dataclass(frozen=True)
class Issue:
    """One validation finding, tied to a file and optionally a line."""

    level: str  # "error" or "warning"
    code: str
    message: str
    path: Path
    line: int | None = None

    def format(self, root: Path | None = None) -> str:
        location = self.path
        if root is not None:
            try:
                location = self.path.relative_to(root)
            except ValueError:
                pass
        where = f"{location}:{self.line}" if self.line else str(location)
        return f"{self.level:>7}  {where}  [{self.code}] {self.message}"


def normalise_keys(meta: dict[str, Any]) -> dict[str, Any]:
    """Fold deprecated singular keys onto their canonical plural names."""
    out: dict[str, Any] = {}
    for key, value in meta.items():
        out[KEY_ALIASES.get(key, key)] = value
    return out


def as_list(value: Any) -> list[str]:
    """Coerce a scalar-or-list front matter value into a list of strings."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    if not text:
        return []
    if "," in text:
        return [part.strip() for part in text.split(",") if part.strip()]
    return [text]


def count_words(text: str) -> int:
    return len(_WORD.findall(text))


def _is_scaffold(heading: str) -> bool:
    return any(heading.startswith(prefix) for prefix in SCAFFOLD_HEADINGS)


def prose_spans(body: str) -> list[tuple[int, int]]:
    """Character ranges of *body* that hold narrative prose.

    Prefers the explicit "Chapter Body" section, taken with everything nested
    under it -- a chapter that opens a ``### scene`` heading inside its body
    must not lose the scene. Falls back to everything that is not under a known
    scaffold heading, so a chapter that has not adopted the standard skeleton
    still reports a sensible word count. Spans rather than stitched text keep
    every offset resolvable back to a real line.
    """
    headings = list(_HEADING.finditer(body))
    if not headings:
        return [(0, len(body))]

    levels = [len(match.group(1)) for match in headings]
    titles = [match.group(2).strip().lower() for match in headings]

    def subtree_end(index: int) -> int:
        """Where a section ends: the next heading at the same or shallower level."""
        for other in range(index + 1, len(headings)):
            if levels[other] <= levels[index]:
                return headings[other].start()
        return len(body)

    named = [index for index, title in enumerate(titles) if any(title.startswith(p) for p in PROSE_HEADINGS)]
    if named:
        return [(headings[index].end(), subtree_end(index)) for index in named]

    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(headings):
        if _is_scaffold(titles[index]):
            end = subtree_end(index)
            while index < len(headings) and headings[index].start() < end:
                index += 1
            continue
        following = headings[index + 1].start() if index + 1 < len(headings) else len(body)
        spans.append((headings[index].end(), following))
        index += 1
    return spans


def prose_of(body: str) -> str:
    """Narrative prose only, with outline and reference scaffolding removed."""
    return "\n".join(body[start:end] for start, end in prose_spans(body))


@dataclass
class Chapter:
    """A single chapter file."""

    path: Path
    meta: dict[str, Any]
    body: str
    #: Lines consumed by the front matter, so body offsets map to file lines.
    body_offset: int = 0
    parse_error: str | None = None

    @classmethod
    def load(cls, path: Path) -> Chapter:
        text = path.read_text(encoding="utf-8")
        try:
            document = frontmatter.parse(text)
        except frontmatter.FrontMatterError as exc:
            return cls(path=path, meta={}, body=text, parse_error=str(exc))
        raw, _ = frontmatter.split(text)
        offset = 0 if raw is None else raw.count("\n") + 2
        return cls(path=path, meta=normalise_keys(document.meta), body=document.body, body_offset=offset)

    # -- identity ---------------------------------------------------------
    @property
    def filename_number(self) -> int | None:
        match = _CHAPTER_FILE.match(self.path.name)
        return int(match.group(1)) if match else None

    @property
    def number(self) -> int | None:
        value = self.meta.get("number", self.filename_number)
        try:
            return int(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    @property
    def title(self) -> str:
        return str(self.meta.get("title") or self.path.stem)

    @property
    def subtitle(self) -> str:
        return str(self.meta.get("subtitle") or "")

    @property
    def act(self) -> int | None:
        try:
            return int(self.meta["act"])
        except (KeyError, TypeError, ValueError):
            return None

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
    def setting(self) -> list[str]:
        return as_list(self.meta.get("setting"))

    @property
    def tone(self) -> list[str]:
        return as_list(self.meta.get("tone"))

    # -- measurement ------------------------------------------------------
    @property
    def prose(self) -> str:
        return prose_of(self.body)

    @property
    def word_count(self) -> int:
        return count_words(self.prose)

    @property
    def total_word_count(self) -> int:
        return count_words(self.body)

    def find(self, pattern: re.Pattern[str], prose_only: bool = True) -> list[tuple[int, str]]:
        """Return ``(file_line, matched_text)`` for *pattern* within the chapter.

        Matching always runs over the whole body so offsets stay exact; when
        *prose_only* is set, hits inside outline scaffolding are discarded.
        """
        spans = prose_spans(self.body) if prose_only else [(0, len(self.body))]
        hits: list[tuple[int, str]] = []
        for match in pattern.finditer(self.body):
            if not any(start <= match.start() < end for start, end in spans):
                continue
            line = self.body.count("\n", 0, match.start()) + 1 + self.body_offset
            hits.append((line, match.group(0)))
        return hits

    @property
    def placeholders(self) -> list[tuple[int, str]]:
        return self.find(_PLACEHOLDER, prose_only=False)

    @property
    def meta_references(self) -> list[tuple[int, str]]:
        """Outline bookkeeping such as "(Chapter 8)" leaking into the prose."""
        return self.find(_META_REF, prose_only=True)


@dataclass
class Book:
    """A book project: its ``book.yml``, outline and chapter files."""

    slug: str
    root: Path
    meta: dict[str, Any] = field(default_factory=dict)
    chapters: list[Chapter] = field(default_factory=list)
    load_error: str | None = None

    CONFIG = "book.yml"
    OUTLINE = "outline.md"
    CHAPTER_DIR = "chapters"

    @classmethod
    def load(cls, root: Path) -> Book:
        slug = root.name
        config = root / cls.CONFIG
        meta: dict[str, Any] = {}
        error: str | None = None
        if config.exists():
            try:
                meta = normalise_keys(frontmatter.loads(config.read_text(encoding="utf-8")))
            except frontmatter.FrontMatterError as exc:
                error = f"{cls.CONFIG}: {exc}"
        else:
            error = f"missing {cls.CONFIG}"
        chapters = [Chapter.load(path) for path in cls.chapter_paths(root)]
        chapters.sort(key=lambda chapter: (chapter.number is None, chapter.number or 0, chapter.path.name))
        return cls(slug=slug, root=root, meta=meta, chapters=chapters, load_error=error)

    @staticmethod
    def chapter_paths(root: Path) -> list[Path]:
        directory = root / Book.CHAPTER_DIR
        if not directory.is_dir():
            return []
        return sorted(path for path in directory.glob("ch*.md") if _CHAPTER_FILE.match(path.name))

    # -- metadata ---------------------------------------------------------
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
    def tags(self) -> list[str]:
        return as_list(self.meta.get("tags"))

    @property
    def themes(self) -> list[str]:
        return as_list(self.meta.get("themes"))

    @property
    def cast(self) -> list[str]:
        return as_list(self.meta.get("cast"))

    @property
    def acts(self) -> int:
        try:
            return int(self.meta.get("acts", 3))
        except (TypeError, ValueError):
            return 3

    @property
    def planned_chapters(self) -> int:
        try:
            return int(self.meta.get("planned_chapters", len(self.chapters)))
        except (TypeError, ValueError):
            return len(self.chapters)

    @property
    def target_word_count(self) -> int:
        try:
            return int(self.meta.get("target_word_count", 0))
        except (TypeError, ValueError):
            return 0

    @property
    def outline_path(self) -> Path:
        return self.root / self.OUTLINE

    # -- measurement ------------------------------------------------------
    @property
    def word_count(self) -> int:
        return sum(chapter.word_count for chapter in self.chapters)

    @property
    def progress(self) -> float:
        """Fraction of the target word count written, clamped to ``0..1``."""
        if self.target_word_count <= 0:
            if self.planned_chapters <= 0:
                return 0.0
            return min(1.0, len(self.chapters) / self.planned_chapters)
        return min(1.0, self.word_count / self.target_word_count)

    def status_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for chapter in self.chapters:
            counts[chapter.status] = counts.get(chapter.status, 0) + 1
        return counts

    def chapter(self, number: int) -> Chapter | None:
        return next((chapter for chapter in self.chapters if chapter.number == number), None)

    def next_number(self) -> int:
        numbers = [chapter.number for chapter in self.chapters if chapter.number]
        return max(numbers) + 1 if numbers else 1


def chapter_filename(number: int) -> str:
    """Zero-padded so lexical order matches reading order."""
    return f"ch{number:02d}.md"


def summarise(values: Iterable[str]) -> str:
    unique = sorted({value for value in values if value})
    return ", ".join(unique)
