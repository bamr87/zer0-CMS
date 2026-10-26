"""A book's `library/<slug>/` as a generated file set: rendered from the
database, written by `export_books`, read back by `import_books` (ADR 0006
decision 13).

| In `library/<slug>/`                | In the platform                                   |
|-------------------------------------|---------------------------------------------------|
| `book.yml`                          | the `BookPage`: its title, subtitle, author and manuscript fields; every key in `front_matter` |
| `outline.md`, `notes/characters.md`, `notes/continuity.md`, `notes/style-guide.md` | `outline`, `character_notes`, `continuity_notes`, `style_guide` |
| `chapters/chNN.md`                  | a `ChapterPage` under the book: its front matter as fields (`front_matter` keeps every key), its body as blocks |
| anything else (`README.md`, `guides/…`, `chapters/.gitkeep`, an empty notes file) | the book's `documents`, verbatim |

**Byte-stable.** The file a page came from is kept beside it
(`importers.ImportedSource`: `book.yml` for a book, the chapter file for a
chapter) and a page renders over it: a YAML key is rewritten only when its
value changed (line surgery — comments, quoting and every other line stay as
they were), and a chapter body that still has the blocks it was read as is its
original text. An unchanged book therefore exports exactly the files it was
imported from; a book made here renders a plain manifest. A directory whose
name starts with `_` (`_template`) is a template: it round-trips like a book
and never appears on the shelf. Two chapters never share a file: a chapter
keeps its own file while its name carries its number, else takes `chNN.md`,
and when two want one name the later keeps its own file or a longer name for
its number (`ch002.md`), so validation reports the duplicate and neither is lost.

**Nothing is lost, in either direction.** Every file the platform reads from
or writes to a library directory is recorded (`books.LibraryFile`: its digest,
the page it belongs to, and that page's content hash then), so each command
can tell what the other side changed since:

- `export_books` writes what is live (`--include-drafts`: the latest
  revisions). It writes a file only when it is missing or still what the
  platform last read or wrote there; a file changed by hand since is a reported
  conflict and stays as it is (`--force` overwrites it). A file the platform no
  longer has there — a renumbered chapter's old name, a deleted or unpublished
  chapter's file, a removed document, a deleted book's directory — is removed
  while it is unchanged since, and kept (a conflict) otherwise.
- `import_books` matches a file to the page last read from or written to it
  (a renumbered chapter keeps its old file until an export moves it), and never
  brings back a page deleted here. A file unchanged since is left alone, and the
  platform's newer content stays; a changed one updates its page only while
  that page has not changed here since — else it is a reported conflict
  (`--force` takes the file). An update is published over a live page with no
  draft, as `legacy:import`, the way the other importers publish; over a draft,
  or a page with a person's unpublished draft, it is a new draft revision. A new
  book is published; a new chapter only under a live book. A chapter whose file
  is gone is reported, never deleted.

A directory the platform never read or wrote falls back to the file each page
was read from (its `ImportedSource`).
"""

from __future__ import annotations

import hashlib
import posixpath
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from django.db import transaction

from agents.principals import ensure_legacy_import_user
from cms.models import BOOK_STATUSES, CHAPTER_STATUSES, BookPage, ChapterPage, SiteRootPage
from cms.services import publish, save_draft
from importers.jekyll import _unique_slug, ensure_site_root
from importers.markdown import from_blocks, to_blocks
from importers.models import ImportedSource

from .library import (
    CHAPTER_DIR,
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
from .models import LibraryFile

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
    """One digest for a set of files (`ImportedSource.source_digest`)."""
    return hashlib.sha256(repr(sorted(files.items())).encode()).hexdigest()


def sha(data: str | bytes) -> str:
    """One file's digest (`LibraryFile.digest`)."""
    return hashlib.sha256(data.encode("utf-8") if isinstance(data, str) else data).hexdigest()


def directory_key(root) -> str:
    """How a library directory is recorded: relative to the repository when it is inside it."""
    from django.conf import settings

    root = Path(root).resolve()
    try:
        return root.relative_to(Path(settings.REPO_ROOT).resolve()).as_posix()
    except ValueError:
        return root.as_posix()


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


def own_path(chapter: ChapterPage) -> str | None:
    """The chapter file it was read from, inside its book, if it was read from one."""
    return chapter.legacy_path.split("/", 1)[1] if chapter.legacy_path and "/" in chapter.legacy_path else None


def chapter_path(chapter: ChapterPage) -> str:
    """The file it wants: the one it came from while that file's name still
    carries its number, else `chapters/chNN.md`."""
    path = own_path(chapter)
    if path and (chapter.number is None or number_in(path) in (chapter.number, None)):
        return path
    return f"{CHAPTER_DIR}/{chapter_filename(chapter.number or 0)}"


def chapter_files(chapters) -> dict[str, ChapterPage]:
    """Each chapter's file in its book (`chapters` in reading order). A
    chapter whose own file still carries its number keeps it; the rest take the
    name their number wants. When one name is wanted twice, the later chapter
    keeps its own file, else takes a longer name for its number (`ch002.md`):
    two chapters never share a file, so neither is lost and validation reports
    the duplicate."""
    placed, rest = {}, []
    for chapter in chapters:
        path = chapter_path(chapter)
        if path == own_path(chapter) and path not in placed:
            placed[path] = chapter
        else:
            rest.append(chapter)
    for chapter in rest:
        path = next((p for p in (chapter_path(chapter), own_path(chapter)) if p and p not in placed), None)
        if path is None:
            path = chapter_path(chapter)
            while path in placed:
                path = f"{CHAPTER_DIR}/ch0{posixpath.basename(path)[2:]}"
        placed[path] = chapter
    return placed


def _content(blocks) -> list:
    return [(b["type"], b["value"]) for b in blocks]


def chapter_text(chapter: ChapterPage, path: str | None = None) -> str:
    """The chapter's file (at `path`, else the one it wants): its front matter
    rewritten where a field changed, its body kept as written while it still
    has the blocks it was read as."""
    blocks = list(chapter.body.get_prep_value())
    stem = posixpath.splitext(posixpath.basename(path or chapter_path(chapter)))[0]
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


def reading_order(chapters) -> list[ChapterPage]:
    return sorted(chapters, key=lambda c: (c.number is None, c.number or 0, c.path))


def book_chapters(book, *, live=False) -> list[ChapterPage]:
    """The book's chapters in reading order: their latest revisions, or
    (`live`) the live chapters as published."""
    pages = ChapterPage.objects.child_of(book).order_by("path")
    return reading_order([p for p in pages if p.live] if live else [p.get_latest_revision_as_object() for p in pages])


def own_files(book: BookPage) -> dict[str, str]:
    """The book's own files: its manifest, its other documents, its outline and notes."""
    tree = {CONFIG: manifest_text(book)}
    for document in book.documents or []:
        tree[document["path"]] = document["text"]
    for path, attr in TEXTS.items():
        if getattr(book, attr):
            tree[path] = getattr(book, attr)
    return tree


def render_book(book: BookPage, chapters) -> tuple[dict[str, str], dict[str, ChapterPage]]:
    """The files of `book` (a revision, or the live page) with `chapters`, and which chapter each chapter file is."""
    placed = chapter_files(chapters)
    tree = own_files(book)
    tree.update((path, chapter_text(chapter, path)) for path, chapter in placed.items())
    return tree, placed


def book_tree(book: BookPage) -> dict[str, str]:
    """Every file of the book's directory as the platform would write it now, from the latest revisions."""
    return render_book(book.get_latest_revision_as_object(), book_chapters(book))[0]


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
    # An empty outline or notes file is kept as a document, so it is written back.
    own = (p for p in sorted(files) if p != CONFIG and not is_chapter(p) and (p not in TEXTS or not files[p]))
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
    report, key = Report(site_key=site_key), directory_key(root)
    with transaction.atomic():
        library = ensure_library(site_key, root)
        for directory in library_dirs(root):
            if slugs and directory.name not in slugs:
                continue
            folder = Folder(site_key, key, directory.name, force, report)
            try:
                with transaction.atomic():
                    import_book(library, directory, folder)
            except Exception as e:  # noqa: BLE001 — one bad book is reported; the rest of the library imports
                report.errors.append(f"{directory.name}: {type(e).__name__}: {e}")
    return report


@dataclass
class Folder:
    """One book's directory as an import reads it, and what the platform last
    read from or wrote to each of its files (`rows`, by path inside the book)."""

    site_key: str
    directory: str
    name: str
    force: bool
    report: Report
    rows: dict = field(default_factory=dict)

    def __post_init__(self):
        found = LibraryFile.objects.filter(
            site_key=self.site_key, directory=self.directory, path__startswith=f"{self.name}/"
        )
        self.rows = {row.path.split("/", 1)[1]: row for row in found}

    def label(self, rel: str) -> str:
        return f"{self.name}/{rel}"

    def record(self, page, files: dict[str, str], page_hash: str, drop=()):
        """The files as the platform has just read them (or found them already in sync)."""
        for rel, text in files.items():
            self.rows[rel], _ = LibraryFile.objects.update_or_create(
                site_key=self.site_key,
                directory=self.directory,
                path=self.label(rel),
                defaults={"page": page, "digest": sha(text), "page_hash": page_hash},
            )
        for rel in drop:
            LibraryFile.objects.filter(pk=self.rows.pop(rel).pk).delete()

    def deleted_here(self, files: dict[str, str], label: str) -> bool:
        """Files whose page was deleted in the platform: unchanged since, they
        are left for export_books to remove (True); changed by hand since, a
        conflict (True) — unless `--force`, which reads them in again (False)."""
        if all(rel in self.rows and sha(text) == self.rows[rel].digest for rel, text in files.items()):
            self.report.unchanged.append(label)
            return True
        if self.force:
            return False
        self.report.conflicts.append(
            f"{label}: deleted in the platform, and changed on disk since (--force reads it in)"
        )
        return True


def import_book(library: SiteRootPage, directory: Path, folder: Folder):
    name, rows = folder.name, folder.rows
    files, unreadable = read_dir(directory)
    folder.report.errors += [f"{name}/{rel}: not UTF-8 text, left out" for rel in unreadable]
    own = {p: t for p, t in files.items() if not is_chapter(p)}
    manifest = rows.get(CONFIG)
    if manifest is not None and manifest.page_id is None and folder.deleted_here(own, folder.label(CONFIG)):
        return
    if manifest is not None and manifest.page_id is not None:
        book = BookPage.objects.get(pk=manifest.page_id)
    elif manifest is None:
        book = next((b for b in BookPage.objects.child_of(library).specific() if book_dir(b) == name), None)
    else:
        book = None  # deleted here, and read in again (--force)
    known = {rel: row for rel, row in rows.items() if not is_chapter(rel) and book and row.page_id == book.pk}
    book = _sync(
        folder,
        book,
        own,
        known,
        render=own_files,
        fill=lambda page: apply_manifest(page, own, name),
        new=lambda: BookPage(slug=name),
        parent=library,
        rel=CONFIG,
        text=own.get(CONFIG, ""),
    )
    import_chapters(book, {p: t for p, t in files.items() if is_chapter(p)}, folder)


def import_chapters(book: BookPage, files: dict[str, str], folder: Folder):
    """Each chapter file → the page last read from or written to it: by this
    directory's records, else the file its page was read from or the name it
    wants now; a file no page claims is a new chapter."""
    rows = {rel: row for rel, row in folder.rows.items() if is_chapter(rel)}
    pages = {p.pk: p for p in ChapterPage.objects.child_of(book).specific()}
    latest = {pk: page.get_latest_revision_as_object() for pk, page in pages.items()}
    wants = {chapter.pk: rel for rel, chapter in chapter_files(reading_order(latest.values())).items()}
    sources = {s.page_id: s for s in ImportedSource.objects.filter(page_id__in=pages)}
    synced = {row.page_id for row in rows.values()}
    claims = {wants[pk]: pk for pk in pages if pk not in synced}
    claims |= {s.legacy_path.split("/", 1)[-1]: pk for pk, s in sources.items() if pk not in synced}
    claims |= {rel: row.page_id for rel, row in rows.items()}

    def sync(page, rel, known):
        stem = posixpath.splitext(posixpath.basename(rel))[0]
        _sync(
            folder,
            page,
            {rel: files[rel]},
            known,
            render=lambda current: {wants.get(current.pk, rel): chapter_text(current, wants.get(current.pk, rel))},
            fill=lambda chapter: apply_chapter(chapter, files[rel], stem),
            new=lambda: ChapterPage(slug=stem),
            parent=book,
            rel=rel,
            text=files[rel],
        )

    found = defaultdict(list)
    for rel in sorted(files, key=lambda p: (number_in(p) or 0, p)):
        if rel not in claims:
            sync(None, rel, {})  # a new chapter
        elif claims[rel] is None:  # its chapter was deleted here
            if not folder.deleted_here({rel: files[rel]}, folder.label(rel)):
                sync(None, rel, {})
        else:
            found[claims[rel]].append(rel)
    for pk, rels in found.items():
        main = wants[pk] if wants[pk] in rels else rels[0]
        sync(pages[pk], main, {main: rows[main]} if main in rows else {})
        for rel in rels:
            if rel != main:  # the chapter's old file, which an export moves
                source = sources.get(pk)
                was = rows[rel].digest if rel in rows else sha(source.source_text) if source else ""
                if sha(files[rel]) == was:
                    folder.report.unchanged.append(folder.label(rel))
                else:
                    folder.report.conflicts.append(
                        f"{folder.label(rel)}: its chapter is {wants[pk]} now, and this old file was changed on disk "
                        "since — merge it by hand"
                    )
    for pk in pages.keys() - found.keys():
        expected = next((rel for rel, row in rows.items() if row.page_id == pk), None)
        if expected is None and pk in sources:
            expected = sources[pk].legacy_path.split("/", 1)[-1]
        if expected is not None:
            folder.report.errors.append(f"{folder.label(expected)}: its file is gone; the chapter is kept")


def _sync(folder: Folder, page, files, known, *, render, fill, new, parent, rel, text):
    """One page and the file(s) it renders in this directory (`known`: what
    the platform last read or wrote there): create it, take the files into it,
    leave it alone, or report a conflict."""
    importer = ensure_legacy_import_user()
    label = folder.label(rel)
    if page is None:
        page = new()
        fill(page)
        page.slug = _unique_slug(parent, page.slug)
        page.legacy_path, page.live = label, False
        parent.add_child(instance=page)
        (publish if parent.live else save_draft)(page, importer)
        folder.report.created.append(label)
    else:
        source = source_of(page)
        current = page.get_latest_revision_as_object()
        now = current.compute_content_hash()
        if render(current) == files:  # what the platform would write now: in sync
            folder.report.unchanged.append(label)
            folder.record(page, files, now, drop=known.keys() - files.keys())
            return page
        if known:
            unchanged = files.keys() == known.keys() and all(sha(t) == known[r].digest for r, t in files.items())
            since = {row.page_hash for row in known.values()}
        else:  # never read or written in this directory: the file the page was read from stands in
            unchanged = source is not None and source.source_digest == digest(files)
            since = {source.import_hash} if source is not None else set()
        if unchanged:  # as the platform last read or wrote it: the platform's newer content stays
            folder.report.unchanged.append(label)
            if not known:
                folder.record(page, files, source.import_hash)
            return page
        if since != {now} and not folder.force:
            folder.report.conflicts.append(f"{label}: changed in the platform since it was last read or written here")
            return page
        fill(current)
        current.legacy_path = current.legacy_path or label
        unpublished = not page.live or page.live_revision_id != page.latest_revision_id
        (save_draft if unpublished else publish)(current, importer)
        folder.report.updated.append(label)
    page = type(page).objects.get(pk=page.pk)
    page_hash = page.get_latest_revision_as_object().compute_content_hash()
    ImportedSource.objects.filter(site_key=folder.site_key, legacy_path=label).exclude(page=page).delete()
    ImportedSource.objects.update_or_create(
        page=page,
        defaults={
            "site_key": folder.site_key,
            "legacy_path": label,
            "source_text": text,
            "source_digest": digest(files),
            "import_hash": page_hash,
        },
    )
    folder.record(page, files, page_hash, drop=known.keys() - files.keys())
    return page


# ── export ─────────────────────────────────────────────────────────────────


@dataclass
class ExportReport:
    site_key: str
    written: list = field(default_factory=list)
    unchanged: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    conflicts: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.site_key}: {len(self.written)} written, {len(self.unchanged)} unchanged, "
            f"{len(self.removed)} removed, {len(self.conflicts)} conflict(s), "
            f"{len(self.extra)} file(s) in the books' directories that the platform does not hold"
        )


def library_books(site_key: str, slugs=None) -> list[BookPage]:
    """The books (and templates) of a library, in tree order."""
    library = SiteRootPage.objects.filter(site_key=site_key).first()
    if library is None:
        return []
    books = BookPage.objects.child_of(library).order_by("path")
    return [b for b in books if not slugs or book_dir(b) in slugs]


def export_library(out, *, site_key: str, slugs=None, prune=False, include_drafts=False, force=False) -> ExportReport:
    """Write each book's files under `out/<slug>/` — what is live, or with
    `include_drafts` the latest revisions — leaving a file alone that is
    already identical, or that was changed by hand since the platform last read
    or wrote it (a conflict, unless `force`). With `prune`, delete the files in
    a book's directory that the platform does not hold."""
    out = Path(out).resolve()
    directory = directory_key(out)
    report = ExportReport(site_key=site_key)
    rows = defaultdict(dict)
    for row in LibraryFile.objects.filter(site_key=site_key, directory=directory):
        name, rel = row.path.split("/", 1)
        rows[name][rel] = row
    exported = set()
    for book in library_books(site_key):
        name = book_dir(book)
        exported.add(name)
        if slugs and name not in slugs:
            continue
        if not (book.live or include_drafts):
            report.skipped.append(f"{name} (not live; --include-drafts writes it)")
            continue
        _export_book(book, out, name, rows[name], directory, include_drafts, force, prune, report)
    for name in sorted(rows.keys() - exported):  # a book deleted here: its files go while unchanged
        if not slugs or name in slugs:
            root = _inside(out, name)
            for rel, row in sorted(rows[name].items()):
                _retire(root, name, rel, row.digest, row, force, report)
    return report


def _inside(out: Path, rel: str) -> Path:
    target = (out / rel).resolve()
    if not target.is_relative_to(out):
        raise ValueError(f"{rel} leaves the export directory")
    return target


def _export_book(book, out, name, rows, directory, include_drafts, force, prune, report):
    root = _inside(out, name)
    rendered = book.get_latest_revision_as_object() if include_drafts else book
    tree, placed = render_book(rendered, book_chapters(book, live=not include_drafts))
    known = {}  # what the platform last read or wrote here: rel → digest (a page's source file stands in)
    pages = [book.pk, *ChapterPage.objects.child_of(book).values_list("pk", flat=True)]
    synced = {row.page_id for row in rows.values()}
    for source in ImportedSource.objects.filter(page_id__in=pages).exclude(page_id__in=synced):
        known[source.legacy_path.split("/", 1)[-1]] = sha(source.source_text)
        if source.page_id == book.pk:  # the book's own files, all as it read them?
            own = {rel: text for rel, text in read_dir(root)[0].items() if not is_chapter(rel)} if root.is_dir() else {}
            if digest(own) == source.source_digest:
                known |= {rel: sha(text) for rel, text in own.items()}
    known |= {rel: row.digest for rel, row in rows.items()}
    hashes = {}
    for rel, text in sorted(tree.items()):
        target = _inside(root, rel)
        on_disk = target.read_bytes() if target.is_file() else None
        if on_disk is not None and on_disk != text.encode("utf-8") and not force and sha(on_disk) != known.get(rel):
            report.conflicts.append(f"{name}/{rel}: changed on disk since the platform last read or wrote it — kept")
            continue
        if on_disk == text.encode("utf-8"):
            report.unchanged.append(f"{name}/{rel}")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
            report.written.append(f"{name}/{rel}")
        owner = placed.get(rel, rendered)
        if id(owner) not in hashes:
            hashes[id(owner)] = owner.compute_content_hash()
        LibraryFile.objects.update_or_create(
            site_key=report.site_key,
            directory=directory,
            path=f"{name}/{rel}",
            defaults={"page_id": owner.pk, "digest": sha(text), "page_hash": hashes[id(owner)]},
        )
        if rel in placed:
            _rekey(placed[rel], f"{name}/{rel}")
    for rel in sorted(known.keys() - tree.keys()):  # moved, removed, deleted or unpublished here
        _retire(root, name, rel, known[rel], rows.get(rel), force, report)
    if root.is_dir():
        for rel in sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()):
            if rel not in tree and rel not in known:
                report.extra.append(f"{name}/{rel}")
                if prune:
                    (root / rel).unlink()


def _retire(root: Path, name: str, rel: str, was: str, row, force: bool, report: ExportReport):
    """A file the platform no longer has here: removed while it is what the
    platform last read or wrote (or `force`), kept as a conflict otherwise."""
    target = _inside(root, rel)
    if target.is_file():
        if not force and sha(target.read_bytes()) != was:
            report.conflicts.append(
                f"{name}/{rel}: no longer the platform's here (moved, removed, deleted or unpublished), "
                "and changed on disk since — kept"
            )
            return
        target.unlink()
        report.removed.append(f"{name}/{rel}")
    if row is not None:
        row.delete()


def _rekey(chapter: ChapterPage, path: str):
    """A chapter whose file moved: its source is now known by the new name, so
    a later page read from the old name cannot take it over."""
    source = source_of(chapter)
    if source is not None and source.legacy_path != path:
        if not ImportedSource.objects.filter(site_key=source.site_key, legacy_path=path).exists():
            ImportedSource.objects.filter(pk=source.pk).update(legacy_path=path)
