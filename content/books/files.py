"""A book's `library/<slug>/` as a generated file set: rendered from the
database, written by `export_books`, read back by `import_books` (ADR 0006
decision 13).

| In `library/<slug>/`                | In the platform                                   |
|-------------------------------------|---------------------------------------------------|
| `book.yml`                          | the `BookPage`: its title, subtitle, author and manuscript fields; every key in `front_matter` |
| `outline.md`, `notes/characters.md`, `notes/continuity.md`, `notes/style-guide.md` | `outline`, `character_notes`, `continuity_notes`, `style_guide` |
| `chapters/chNN.md`                  | a `ChapterPage` under the book: its front matter as fields (`front_matter` keeps every key), its body as blocks |
| anything else (`README.md`, `guides/…`, `chapters/.gitkeep`) | the book's `documents`, verbatim         |

**Byte-stable.** The file a page came from is kept beside it
(`importers.ImportedSource`: `book.yml` for a book, the chapter file for a
chapter) and a page renders over it: a YAML key is rewritten only when its
value changed (line surgery — comments, quoting and every other line stay as
they were), and a chapter body that still has the blocks it was read as is its
original text. An unchanged book therefore exports exactly the files it was
imported from; a book made here renders a plain manifest. A directory whose
name starts with `_` (`_template`) is a template: it round-trips like a book
and never appears on the shelf.

**Never overwrites the platform.** Importing a book again, file by page: a
file that is what the platform would write now is in sync; a file unchanged
since the last import leaves the platform's newer content alone; a changed file
updates its page — unless the page was changed here since (or was made here and
never imported), which is a reported conflict (`--force` takes the file).
Imported pages are published by `legacy:import`, as the other importers do; a
chapter whose file is gone is reported, never deleted.
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from django.db import transaction

from agents.principals import ensure_legacy_import_user
from cms.models import BOOK_STATUSES, CHAPTER_STATUSES, BookPage, ChapterPage, SiteRootPage
from cms.services import publish
from importers.jekyll import _unique_slug, ensure_site_root
from importers.markdown import from_blocks, to_blocks
from importers.models import ImportedSource

from .library import (
    CHAPTER_FILE,
    CHARACTERS,
    CONFIG,
    CONTINUITY,
    OUTLINE,
    STYLE_GUIDE,
    FrontMatterError,
    as_int,
    as_list,
    chapter_filename,
    is_chapter,
    loads,
)

TEXTS = {OUTLINE: "outline", CHARACTERS: "character_notes", CONTINUITY: "continuity_notes", STYLE_GUIDE: "style_guide"}
KEY = re.compile(r"^([A-Za-z_][\w-]*)[ \t]*:(?=\s|$)")
FENCED = re.compile(r"(---[ \t]*\r?\n)(.*?)(^---[ \t]*(?:\r?\n|\Z))", re.S | re.M)
WIDE = 10**9


def _text(value) -> str:
    return "" if value is None else str(value)


def _status(choices, default):
    return lambda raw: str(raw) if str(raw or "") in choices else default


# A key of the file → (the page's attribute, how the file's value reads as it).
# Title and a chapter's number fall back to the directory or the file name.
BOOK_KEYS = {
    "title": ("title", None),
    "subtitle": ("subtitle", _text),
    "author": ("author", _text),
    "status": ("book_status", _status(BOOK_STATUSES, "idea")),
    "logline": ("logline", _text),
    "genre": ("genre", _text),
    "pov": ("pov", _text),
    "tense": ("tense", _text),
    "era": ("era", _text),
    "protagonist": ("protagonist", _text),
    "acts": ("acts", lambda raw: as_int(raw, 3)),
    "planned_chapters": ("planned_chapters", as_int),
    "target_word_count": ("target_word_count", as_int),
    "themes": ("themes", as_list),
    "cast": ("cast", as_list),
}
CHAPTER_KEYS = {
    "title": ("title", None),
    "subtitle": ("subtitle", _text),
    "number": ("number", None),
    "act": ("act", as_int),
    "status": ("chapter_status", _status(CHAPTER_STATUSES, "draft")),
    "pov": ("pov", _text),
    "era": ("era", _text),
    "characters": ("characters", as_list),
    "setting": ("setting", as_list),
    "tone": ("tone", as_list),
    "style": ("style", _text),
}
ALIASES = {"themes": "theme", "characters": "character", "setting": "settings"}  # older files' singular keys


def digest(files: dict[str, str]) -> str:
    return hashlib.sha256(repr(sorted(files.items())).encode()).hexdigest()


def number_in(path: str) -> int | None:
    """The chapter number a file name carries (`ch07.md` → 7)."""
    match = CHAPTER_FILE.match(posixpath.basename(path))
    return int(match.group(1)) if match else None


def _key(raw: dict, key: str) -> str:
    """The name `raw` uses for `key`: an older singular alias when only that is there."""
    alias = ALIASES.get(key)
    return alias if alias and key not in raw and alias in raw else key


# ── YAML by line surgery ────────────────────────────────────────────────────


def parse(text: str) -> dict:
    """A flat YAML mapping (a manifest, a front matter), or {} when it does not parse."""
    try:
        return loads(text)
    except FrontMatterError:
        return {}


def scalar(value) -> str:
    out = yaml.safe_dump(value, allow_unicode=True, width=WIDE).removesuffix("\n...\n").removesuffix("\n")
    if "\n" in out:
        out = yaml.safe_dump(value, allow_unicode=True, width=WIDE, default_style='"').rstrip("\n")
    return out


def _span(lines: list[str], start: int) -> int:
    """Where the value of the key on line `start` ends: its indented and `- ` lines."""
    end = start + 1
    while end < len(lines) and lines[end].strip() and (lines[end][0] in " \t" or lines[end].lstrip().startswith("-")):
        end += 1
    return end


def _render(key: str, value, old: list[str]) -> list[str]:
    if isinstance(value, (list, dict)):
        items = [line for line in old[1:] if line.lstrip().startswith("- ")]
        if items and value and isinstance(value, list):  # a block list stays one, its items indented as before
            prefix = items[0][: len(items[0]) - len(items[0].lstrip())] + "- "
            return [f"{key}:\n"] + [f"{prefix}{scalar(item)}\n" for item in value]
        flow = yaml.safe_dump(value, default_flow_style=True, allow_unicode=True, width=WIDE).strip()
        return [f"{key}: {flow}\n"]
    return [f"{key}: {scalar(value)}\n"]


def set_keys(text: str, changes: dict[str, Any]) -> str:
    """`text` with each key of `changes` set — rewritten where it is, appended
    where it is not; every other line is left exactly as it was."""
    if not changes:
        return text
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    for key, value in changes.items():
        at = next((i for i, line in enumerate(lines) if (m := KEY.match(line)) and m.group(1) == key), None)
        if at is None:
            lines += _render(key, value, [])
        else:
            end = _span(lines, at)
            lines[at:end] = _render(key, value, lines[at:end])
    return "".join(lines)


def changed_keys(page, raw: dict, keys: dict, name: str) -> dict:
    """The keys whose value on `page` is not what the file (`raw`) says; `name`
    is the directory or the file's stem, which a missing title (or number) falls back to."""
    changes = {}
    for key, (attr, read) in keys.items():
        written = _key(raw, key)
        if key == "title":
            known = str(raw.get("title") or name)
        elif key == "number":
            known = as_int(raw.get("number", number_in(f"{name}.md")))
        else:
            known = read(raw.get(written))
        value = getattr(page, attr)
        if value != known and not (value in (None, "", []) and written not in raw):
            changes[written] = value
    return changes


def canonical(page, keys: dict) -> str:
    """A manifest or a front matter for a page with no file yet: its
    `front_matter` in order with the fields written over it, then each field
    with a value that it lacks."""
    data = dict(page.front_matter or {})
    for key, (attr, _read) in keys.items():
        name, value = _key(data, key), getattr(page, attr)
        if value not in (None, "", []) or name in data or key in ("title", "status"):
            data[name] = value
    return "".join(line for key, value in data.items() for line in _render(key, value, []))


# ── rendering a book's files from the database ──────────────────────────────


def source_of(page) -> ImportedSource | None:
    return ImportedSource.objects.filter(page_id=page.pk).first() if page.pk else None


def book_dir(book) -> str:
    """The book's directory in the library: the one it came from, else its slug."""
    return book.legacy_path.split("/", 1)[0] if book.legacy_path else book.slug


def manifest_text(book: BookPage) -> str:
    source = source_of(book)
    if source is None:
        return canonical(book, BOOK_KEYS)
    return set_keys(source.source_text, changed_keys(book, parse(source.source_text), BOOK_KEYS, book_dir(book)))


def chapter_path(chapter: ChapterPage) -> str:
    """Its path inside the book: the file it came from while that file's name
    still carries its number, else `chapters/chNN.md`."""
    if chapter.legacy_path and "/" in chapter.legacy_path:
        path = chapter.legacy_path.split("/", 1)[1]
        if chapter.number is None or number_in(path) in (chapter.number, None):
            return path
    return f"chapters/{chapter_filename(chapter.number or 0)}"


def _content(blocks) -> list:
    return [(b["type"], b["value"]) for b in blocks]


def chapter_text(chapter: ChapterPage) -> str:
    """The chapter's file: its front matter rewritten where a field changed,
    its body kept as written while it still has the blocks it was read as."""
    blocks = list(chapter.body.get_prep_value())
    stem = posixpath.splitext(posixpath.basename(chapter_path(chapter)))[0]
    source = source_of(chapter)
    if source is None:
        return f"---\n{canonical(chapter, CHAPTER_KEYS)}---\n{from_blocks(blocks)}"
    text = source.source_text
    match = FENCED.match(text)
    body = text[match.end() :] if match else text
    if _content(to_blocks(body)) != _content(blocks):
        body = from_blocks(blocks)
    if match is None:
        changes = changed_keys(chapter, {}, CHAPTER_KEYS, stem)
        return f"---\n{set_keys('', changes)}---\n{body}" if changes else body
    head, front, close = match.groups()
    return f"{head}{set_keys(front, changed_keys(chapter, parse(front), CHAPTER_KEYS, stem))}{close}{body}"


def book_chapters(book) -> list[ChapterPage]:
    """The latest revisions of the book's chapters, in reading order."""
    latest = [page.get_latest_revision_as_object() for page in ChapterPage.objects.child_of(book).order_by("path")]
    return sorted(latest, key=lambda c: (c.number is None, c.number or 0, c.path))


def book_tree(book: BookPage, *, chapters=None) -> dict[str, str]:
    """Every file of the book's directory as the platform would write it now,
    from the latest revisions (`chapters`: these instead of the book's)."""
    if book.pk:
        book = book.get_latest_revision_as_object()
    tree = {CONFIG: manifest_text(book)}
    for path, attr in TEXTS.items():
        if getattr(book, attr):
            tree[path] = getattr(book, attr)
    for document in book.documents or []:
        tree[document["path"]] = document["text"]
    for chapter in book_chapters(book) if chapters is None else chapters:
        tree[chapter_path(chapter)] = chapter_text(chapter)
    return tree


# ── reading a book's directory into its pages ───────────────────────────────


def read_dir(root: Path) -> tuple[dict[str, str], list[str]]:
    """Every file under `root` as text, and the ones that are not UTF-8 text."""
    files, unreadable = {}, []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            files[rel] = path.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            unreadable.append(rel)
    return files, unreadable


def library_dirs(root: Path) -> list[Path]:
    """The books (and templates) of a library: its directories holding a `book.yml`."""
    return [p for p in sorted(root.iterdir()) if p.is_dir() and not p.name.startswith(".") and (p / CONFIG).is_file()]


def apply_manifest(book: BookPage, files: dict[str, str], name: str):
    raw = parse(files.get(CONFIG, ""))
    book.front_matter = raw
    book.title = str(raw.get("title") or name)[:255]
    for key, (attr, read) in BOOK_KEYS.items():
        if read is not None:
            setattr(book, attr, read(raw.get(_key(raw, key))))
    for path, attr in TEXTS.items():
        setattr(book, attr, files.get(path, ""))
    own = (p for p in sorted(files) if p != CONFIG and p not in TEXTS and not is_chapter(p))
    book.documents = [{"path": p, "text": files[p]} for p in own]


def apply_chapter(chapter: ChapterPage, text: str, stem: str):
    match = FENCED.match(text)
    raw = parse(match.group(2)) if match else {}
    chapter.front_matter = raw
    chapter.title = str(raw.get("title") or stem)[:255]
    chapter.number = as_int(raw.get("number", number_in(f"{stem}.md")))
    for key, (attr, read) in CHAPTER_KEYS.items():
        if read is not None:
            setattr(chapter, attr, read(raw.get(_key(raw, key))))
    chapter.body = to_blocks(text[match.end() :] if match else text)


@dataclass
class Report:
    site_key: str
    created: list = field(default_factory=list)
    updated: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.site_key}: {len(self.created)} created, {len(self.updated)} updated, "
            f"{len(self.unchanged)} unchanged, {len(self.conflicts)} conflict(s), {len(self.errors)} error(s)"
        )


def ensure_library(site_key: str, root=None) -> SiteRootPage:
    """The site root the books of a library live under (and its Wagtail site)."""
    from django.conf import settings

    title = site_key.replace("-", " ").title()
    return ensure_site_root(site_key, Path(root or settings.BOOKS_LIBRARY_DIR), {"title": title}, settings.REPO_ROOT)


def import_library(root, *, site_key: str, slugs=None, force=False) -> Report:
    root = Path(root)
    if not root.is_dir():
        raise FileNotFoundError(f"{root} is not a library directory")
    report = Report(site_key=site_key)
    with transaction.atomic():
        library = ensure_library(site_key, root)
        for directory in library_dirs(root):
            if slugs and directory.name not in slugs:
                continue
            try:
                with transaction.atomic():
                    import_book(library, directory, site_key=site_key, force=force, report=report)
            except Exception as e:  # noqa: BLE001 — one bad book is reported; the rest of the library imports
                report.errors.append(f"{directory.name}: {type(e).__name__}: {e}")
    return report


def import_book(library: SiteRootPage, directory: Path, *, site_key: str, force: bool, report: Report):
    name = directory.name
    files, unreadable = read_dir(directory)
    report.errors += [f"{name}/{rel}: not UTF-8 text, left out" for rel in unreadable]
    own = {p: t for p, t in files.items() if not is_chapter(p)}
    found = next((b for b in BookPage.objects.child_of(library).specific() if book_dir(b) == name), None)
    book = _sync(
        found,
        own,
        render=lambda current: book_tree(current, chapters=[]),
        fill=lambda page: apply_manifest(page, own, name),
        new=lambda: BookPage(slug=name),
        parent=library,
        legacy=f"{name}/{CONFIG}",
        text=own.get(CONFIG, ""),
        site_key=site_key,
        force=force,
        report=report,
    )
    pages = {chapter_path(c.get_latest_revision_as_object()): c for c in ChapterPage.objects.child_of(book).specific()}
    for path in sorted((p for p in files if is_chapter(p)), key=lambda p: (number_in(p) or 0, p)):
        stem, text = posixpath.splitext(posixpath.basename(path))[0], files[path]
        _sync(
            pages.pop(path, None),
            {path: text},
            render=lambda current, path=path: {path: chapter_text(current)},
            fill=lambda page, text=text, stem=stem: apply_chapter(page, text, stem),
            new=lambda stem=stem: ChapterPage(slug=stem),
            parent=book,
            legacy=f"{name}/{path}",
            text=text,
            site_key=site_key,
            force=force,
            report=report,
        )
    report.errors += [f"{name}/{path}: its file is gone; the chapter is kept" for path in sorted(pages)]


def _sync(page, files, *, render, fill, new, parent, legacy, text, site_key, force, report):
    """One page and the file(s) it renders: create it, update it, leave it alone, or report a conflict."""
    importer = ensure_legacy_import_user()
    file_digest = digest(files)
    source = source_of(page) if page is not None else None
    if page is None:
        page = new()
        fill(page)
        page.slug = _unique_slug(parent, page.slug)
        page.legacy_path, page.live = legacy, False
        parent.add_child(instance=page)
        publish(page, user=importer)
        report.created.append(legacy)
    else:
        current = page.get_latest_revision_as_object()
        if render(current) == files:
            report.unchanged.append(legacy)  # what the platform would write now: in sync
        elif source is not None and source.source_digest == file_digest:
            report.unchanged.append(legacy)  # the file has not moved; the platform's newer content stays
            return page
        elif (source is None or current.compute_content_hash() != source.import_hash) and not force:
            report.conflicts.append(f"{legacy}: changed in the platform since the last import (--force takes the file)")
            return page
        else:
            fill(current)
            current.legacy_path = current.legacy_path or legacy
            publish(current, user=importer)
            report.updated.append(legacy)
    page = type(page).objects.get(pk=page.pk)
    ImportedSource.objects.filter(site_key=site_key, legacy_path=legacy).exclude(page=page).delete()
    ImportedSource.objects.update_or_create(
        page=page,
        defaults={
            "site_key": site_key,
            "legacy_path": legacy,
            "source_text": text,
            "source_digest": file_digest,
            "import_hash": page.get_latest_revision_as_object().compute_content_hash(),
        },
    )
    return page


# ── export ─────────────────────────────────────────────────────────────────


@dataclass
class ExportReport:
    site_key: str
    written: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    extra: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.site_key}: {len(self.written)} written, {len(self.unchanged)} unchanged, "
            f"{len(self.extra)} file(s) in the books' directories that the platform does not hold"
        )


def library_books(site_key: str, slugs=None) -> list[BookPage]:
    """The books (and templates) of a library, in tree order."""
    library = SiteRootPage.objects.filter(site_key=site_key).first()
    if library is None:
        return []
    books = BookPage.objects.child_of(library).order_by("path")
    return [b for b in books if not slugs or book_dir(b) in slugs]


def export_library(out, *, site_key: str, slugs=None, prune=False) -> ExportReport:
    """Write each book's files under `out/<slug>/` (a file already identical is
    left untouched); with `prune`, delete the files there that are not its own."""
    out = Path(out).resolve()
    report = ExportReport(site_key=site_key)
    for book in library_books(site_key, slugs):
        name = book_dir(book)
        root = (out / name).resolve()
        tree = book_tree(book)
        for rel, text in sorted(tree.items()):
            target = (root / rel).resolve()
            if not target.is_relative_to(root):
                raise ValueError(f"{name}/{rel} leaves the book's directory")
            data = text.encode("utf-8")
            if target.is_file() and target.read_bytes() == data:
                report.unchanged.append(f"{name}/{rel}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            report.written.append(f"{name}/{rel}")
        _moved(book, root, name, tree, report)
        if root.is_dir():
            on_disk = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
            for rel in sorted(set(on_disk) - set(tree)):
                report.extra.append(f"{name}/{rel}")
                if prune:
                    on_disk[rel].unlink()
    return report


def _moved(book, root: Path, name: str, tree: dict[str, str], report: ExportReport):
    """A renumbered chapter's old file, still exactly as the platform last read or
    wrote it, has moved to its new name: remove it (a file someone changed stays)."""
    for source in ImportedSource.objects.filter(page__in=ChapterPage.objects.child_of(book)):
        rel = source.legacy_path.split("/", 1)[1]
        old = root / rel
        if rel not in tree and old.is_file() and old.read_bytes() == source.source_text.encode("utf-8"):
            old.unlink()
            report.written.append(f"{name}/{rel} (moved)")
