"""Create new books and chapters from the templates in ``library/_template``.

Scaffolding is deliberately file-based rather than string-based: editing
``library/_template/`` changes what ``books new`` produces, with no code change.
"""

from __future__ import annotations

import re
import shutil
from datetime import date
from pathlib import Path

from . import frontmatter
from .models import Book, chapter_filename

SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class ScaffoldError(Exception):
    """Raised when a book or chapter cannot be created."""


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return re.sub(r"-{2,}", "-", slug)


def new_book(
    library_dir: Path,
    slug: str,
    title: str,
    template_dir: Path,
    logline: str = "",
    genre: str = "",
    today: date | None = None,
) -> Path:
    """Copy the template into ``library/<slug>`` and stamp its ``book.yml``."""
    if not SLUG.match(slug):
        raise ScaffoldError(f"{slug!r} is not a valid slug; use lowercase words joined by hyphens")
    target = library_dir / slug
    if target.exists():
        raise ScaffoldError(f"{target} already exists")
    if not template_dir.is_dir():
        raise ScaffoldError(f"template directory {template_dir} is missing")

    shutil.copytree(template_dir, target)
    try:
        _stamp(target, slug, title, logline, genre, today or date.today())
    except Exception:
        # Never leave a half-built book behind: the next `books new` would hit
        # "already exists", and `books validate` would report the wreckage.
        shutil.rmtree(target, ignore_errors=True)
        raise
    return target


def _stamp(target: Path, slug: str, title: str, logline: str, genre: str, today: date) -> None:
    config = target / Book.CONFIG
    try:
        meta = frontmatter.loads(config.read_text(encoding="utf-8"))
    except (OSError, frontmatter.FrontMatterError) as exc:
        raise ScaffoldError(f"template {config} is not usable: {exc}") from exc

    meta["slug"] = slug
    meta["title"] = title
    meta["status"] = "idea"
    meta["created"] = today.isoformat()
    if logline:
        meta["logline"] = logline
    if genre:
        meta["genre"] = genre
    config.write_text(frontmatter.dumps(meta), encoding="utf-8")

    outline = target / Book.OUTLINE
    if outline.exists():
        text = outline.read_text(encoding="utf-8")
        outline.write_text(text.replace("{{title}}", title).replace("{{slug}}", slug), encoding="utf-8")


def new_chapter(book: Book, title: str, number: int | None = None, act: int | None = None) -> Path:
    """Create the next chapter file for *book* from the chapter skeleton."""
    number = number or book.next_number()
    if book.chapter(number) is not None:
        raise ScaffoldError(f"chapter {number} already exists in {book.slug}")

    directory = book.root / Book.CHAPTER_DIR
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / chapter_filename(number)
    if path.exists():
        raise ScaffoldError(f"{path} already exists")

    meta = {
        "title": title,
        "subtitle": "",
        "number": number,
        "act": act if act is not None else _act_for(book, number),
        "status": "stub",
        "pov": book.pov or "Third person limited",
        "characters": [],
        "setting": [],
        "era": str(book.meta.get("era") or ""),
        "tone": [],
        "style": "",
    }
    path.write_text(frontmatter.render(meta, _CHAPTER_BODY.format(title=title)), encoding="utf-8")
    return path


def _act_for(book: Book, number: int) -> int:
    """Spread chapter numbers evenly across the book's acts."""
    planned = max(book.planned_chapters, number)
    acts = max(1, book.acts)
    return min(acts, (number - 1) * acts // planned + 1)


_CHAPTER_BODY = """
## Outline and Contextual Alignment

### Purpose of the Chapter

- What this chapter has to accomplish for the plot, the character and the themes.

### Setting

- Where it happens, and what the place is doing for the story.

### Main Characters

- Who is on the page, and what each of them wants here.

### Plot Progression

1. Beat one.
2. Beat two.
3. Beat three.

### Themes Introduced

- Which of the book's themes this chapter carries.

---

## Chapter Body

_{title} is not written yet._

---

## References & Contextual Alignment

- How this chapter lines up with the outline, the character arc and the themes.

---

## Links and References
"""
