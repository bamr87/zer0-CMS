"""Wagtail pages → a Jekyll site's Markdown files (PLAN §4, M7).

For each page under a site root, in tree order:

- **unchanged since import** (`ImportedSource.unchanged`: its `content_hash`
  still equals the import's, and a page whose file a person edits still has
  the file's path and front-matter key order) and without bylines or
  corrections from the newsroom: the stored source file, byte for byte;
- **changed since import**: the source file with only what changed rewritten
  — the front matter by line surgery (sites/frontmatter.py: a key whose value
  changed is rewritten in place, a new one goes in before the closing fence, a
  dropped one goes, and comments, quoting and every other line stay as they
  were), the body kept as it was while its blocks write the Markdown the
  body's own blocks write (so a page read before a block type existed keeps
  its body too);
- **created in Wagtail** (or a source the surgery cannot edit): front matter +
  body rendered from the page. Either way the front matter is the source's, in
  its original key order, with the typed fields written over it (title, description, seo_title, date — kept as
  the original string when the parsed date did not change —, author, tags,
  categories, book fields: the model's `front_matter_fields`; the SEO fields —
  `canonical_url`, `og_title`, `og_description`, `image`, `noindex` — only
  where a person set one to other than its file says, cms/seo.py); a page made in
  the platform, whose front matter holds only the raw keys a person gave it
  (cms/files.py), gets its typed keys first and its raw keys after them, as a
  file a person writes. For an ABC book the `alphabet:` list is rebuilt
  from its `letter` blocks, each merged into the original entry so a plate's
  `image`, `prompt` and `status` survive an edit to its tagline or alt, and a
  plate whose word or subject changed is planned again for it as the Rails
  generator planned it (books/abc.py: the image named for the word, the prompt
  composed for it, the status `planned`); a story's `authors` (its bylines)
  and `corrections` (its corrections and updates log: date, kind, text) come
  from the newsroom, for the site to render. The body is the blocks as
  Markdown (importers/markdown.py).

An ABC book read with its spec sidecar (`_data/abc_books/<slug>.json`, kept
on its `ImportedSource`) writes the sidecar with the page: as it was read while
the page is, else rewritten to agree with the page (books/abc.py), so drsai's
`tools/import_abc_book.py --check` holds after an edit.

A page is written at its file path (`legacy_path`: the file it was imported
from, or the one a person gave it). A page created in Wagtail without one gets
a path from its type: an `ArticlePage` in `_posts` becomes
`<collections_dir>/_posts/YYYY-MM-DD-<slug>.md`, anything in another collection
`<collections_dir>/_<collection>/<slug>.md`, a page at the site root
`<slug>.md` — the slug transliterated to `a-z0-9` and hyphens
(sites/writer.py). An imported page a person moved is rendered at its new path
and listed in `moved`; nothing deletes its old file.

**A page that is not live reaches its file as not built.** Never published,
unpublished or expired, its file carries Jekyll's own switch,
`published: false` (the file stays; Jekyll skips it), added by line surgery
before the closing fence — unless the file already keeps itself out of the
build in the site's own way (`sites.catalog.held_back`: `published: false`,
`draft: true`, `status: draft`, a draft in `_drafts/`, a future date), as the
reader reads it, so such a file exports byte for byte. When the page goes live
again only the marker the platform added comes off: the file gets back the
page's own `published` key, or none, and nothing else moves (`mark`).

Only live pages are exported unless `include_drafts`, which writes every page's
latest revision, marked when the page is not live. A write-back of the live
pages also takes down the file of each page that is not live but has one (an
`ImportedSource`): that file as the platform last read or wrote it, marked
(`File.take_down`), so unpublishing reaches the site on the next write-back
without writing a draft's content. `site_files` lists what an export writes;
`export_site` writes it into `out` and nothing else — a take-down is skipped
there, with no file to take down — refusing a path that would leave it and
never writing two pages to one path (the second is skipped), and a site's
write-back writes it into the site's checkout under the stale-write guard
(sites/services.py).
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.utils import timezone
from wagtail.models import Page

from books import abc
from cms import seo
from cms.files import SUFFIXES
from cms.models import ArticlePage, BookPage, ChapterPage, CollectionPage, SiteRootPage
from importers import frontmatter
from importers.markdown import from_blocks, to_blocks
from importers.models import ImportedSource
from newsroom.services import front_matter_for as newsroom_front_matter
from newsroom.services import with_front_matter as with_newsroom_front_matter
from sites import catalog
from sites import frontmatter as surgery
from sites.writer import slugify

_ABSENT = object()  # a front-matter key the file does not have


@dataclass
class ExportReport:
    site_key: str
    verbatim: list = field(default_factory=list)
    rendered: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    # (old, new): an imported page a person moved; its old file is not deleted.
    moved: list = field(default_factory=list)

    def summary(self) -> str:
        return (
            f"{self.site_key}: {len(self.verbatim)} verbatim, {len(self.rendered)} rendered, "
            f"{len(self.skipped)} skipped"
        )


def _collections_dir(root: SiteRootPage) -> str:
    return str((root.jekyll_config or {}).get("collections_dir") or "").strip("/")


def path_for(page, root: SiteRootPage) -> str:
    if page.legacy_path:
        return page.legacy_path
    base = _collections_dir(root)
    parent = page.get_parent().specific
    if isinstance(parent, CollectionPage):
        folder = "/".join(p for p in (base, f"_{parent.collection}") if p)
        if isinstance(page, ArticlePage) and parent.collection == "posts" and page.date:
            return f"{folder}/{page.date:%Y-%m-%d}-{_file_slug(page)}.md"
        if isinstance(page, BookPage):
            return f"{folder}/{_file_slug(page)}/index.md"
        return f"{folder}/{_file_slug(page)}.md"
    if isinstance(page, ChapterPage) and parent.legacy_path:
        return str(Path(parent.legacy_path).parent / f"{page.slug}.md")
    return f"{page.slug}.md"


def _alphabet(page, original, fm: dict, spec: dict) -> list | None:
    """The `alphabet:` list from the page's `letter` blocks. A plate whose word,
    or subject, is not the one its entry was composed for is planned again
    (books/abc.py `replan`) with the book's art style and palette and its
    sidecar's background and mood (`spec`); its subject is the block's, else
    the sidecar's (the page does not carry one)."""
    letters = [b for b in page.body if b.block_type == "letter"]
    if not letters:
        return original
    by_letter = {str(item.get("letter")): item for item in (original or []) if isinstance(item, dict)}
    composed = {str(e.get("letter")): e for e in spec.get("alphabet") or [] if isinstance(e, dict)}
    out = []
    for block in letters:
        value = block.value
        item = dict(by_letter.get(value["letter"], {}))
        if item:
            was = composed.get(value["letter"], {}).get("subject") or item.get("subject") or ""
            subject = value.get("subject") or was
            if value["word"] != item.get("word") or subject != was:
                item = abc.replan(
                    item,
                    word=value["word"],
                    subject=subject,
                    style=fm.get("art_style"),
                    palette=fm.get("palette"),
                    background=spec.get("background"),
                    mood=spec.get("mood"),
                )
        item["letter"] = value["letter"]
        for key in ("word", "tagline", "alt"):
            if value.get(key):
                item[key] = value[key]
        if value.get("subject") and "prompt" not in item:
            item["subject"] = value["subject"]
        item.setdefault("status", "planned")
        out.append(item)
    return out


def front_matter_for(page) -> dict:
    stored = dict(page.front_matter or {})
    # A file page made in the platform holds no typed key of its own: the typed keys lead.
    made_here = bool(page.file_editor_fields) and not stored.keys() & page.front_matter_fields.keys()
    fm = {} if made_here else stored

    def put(key, value):
        """Write a typed value over the source's; an empty one only clears a key
        the source had (it never adds an empty key)."""
        if value in (None, "", []):
            if fm.get(key) not in (None, "", []):
                fm[key] = "" if value is None else value
            return
        fm[key] = value

    fm["title"] = page.title
    put("description", page.search_description)
    put("seo_title", page.seo_title)
    for name, value in seo.changed(page).items():  # never a key a person did not change, in whatever form it has
        put(seo.FIELDS[name], value)
    if isinstance(page, ArticlePage):
        original = frontmatter.parse_date(fm.get("date"))
        if page.date and (original is None or original != page.date):
            fm["date"] = frontmatter.format_date(page.date)
        put("author", page.author)
        tags = sorted(t.name for t in page.tags.all())
        if tags != sorted(str(t) for t in _as_list(fm.get("tags"))):
            put("tags", tags)
        categories = sorted(c.name for c in page.categories.all())
        if categories != sorted(str(c) for c in _as_list(fm.get("categories"))):
            put("categories", categories)
    if isinstance(page, BookPage):
        for key in ("subtitle", "author", "series", "audience", "art_style"):
            put(key, getattr(page, key))
        if page.profile == "abc":
            fm.setdefault("layout", "book-abc")
            alphabet = _alphabet(page, fm.get("alphabet"), fm, _spec(page))
            if alphabet is not None:
                if alphabet != fm.get("alphabet") and fm.get("status") in abc.BOOK_STATUSES:
                    fm["status"] = abc.book_status(alphabet)
                fm["alphabet"] = alphabet
    if isinstance(page, ChapterPage) and page.number is not None:
        fm["chapter"] = page.number
    fm.update(newsroom_front_matter(page))
    if made_here:
        fm.update((key, value) for key, value in stored.items() if key not in fm)
    return fm


def _spec(page) -> dict:
    """The spec sidecar an ABC book was read with (`ImportedSource.sidecars`), or {}."""
    source = ImportedSource.objects.filter(page_id=page.pk).only("sidecars").first()
    return next((abc.load(text) for text in (source.sidecars if source else {}).values()), {})


def _as_list(value):
    if isinstance(value, str):
        return [v for v in value.replace(",", " ").split() if v]
    return list(value or [])


def _file_slug(page) -> str:
    return slugify(page.slug) or page.slug


def render(page, source_text: str | None = None) -> str:
    """The page as a Jekyll file: over `source_text` (the file it was read from)
    when there is one, else from scratch."""
    blocks = list(page.body.get_prep_value())
    fm = front_matter_for(page)
    leading = "\n" if any(b["type"] != "letter" for b in blocks) else ""
    if source_text is not None:
        try:
            return _render_over(source_text, fm, blocks, leading or "\n")
        except (surgery.EditError, yaml.YAMLError):
            pass  # a front matter the surgery cannot place: the whole file is rendered instead
    return frontmatter.join(fm, from_blocks(blocks, leading=leading or "\n"))


def _render_over(source_text: str, fm: dict, blocks: list, leading: str) -> str:
    original, _ = frontmatter.split(source_text)
    original = original or {}
    if [key for key in original if key in fm] != [key for key in fm if key in original]:
        # a person reordered the file's keys (cms/files.py): surgery keeps the file's order, so render it whole
        raise surgery.EditError("the front matter's keys were reordered")
    changes = {key: value for key, value in fm.items() if key not in original or original[key] != value}
    changes.update({key: None for key in original if key not in fm})
    text = surgery.update_keys(source_text, changes)
    _, body = frontmatter.split(text)
    if from_blocks(blocks, leading=leading) == from_blocks(to_blocks(body), leading=leading):
        return text  # the blocks write what the body's own blocks write (cut by any version of the importer)
    return text[: len(text) - len(body)] + from_blocks(blocks, leading=leading)


def mark(text: str, rel: str, page, *, live: bool, now) -> str:
    """`text`, the file of `page` at `rel`, with the platform's `published:
    false` where it belongs and nowhere else. A page that is not live gets it
    unless the file, with the page's own `published` key, already keeps itself
    out of the build (`catalog.held_back`, the reader's rules at `now`); a live
    page's file carries the page's own `published` key, or none, so a marker the
    platform added comes off. The page's front matter never holds the
    platform's marker (it is written here, never stored), which is how the two
    are told apart. Only that key's line moves (line surgery); a front matter
    the surgery cannot edit is rendered whole instead."""
    own = (page.front_matter or {}).get("published", _ABSENT)
    if live and own is _ABSENT and "published" not in text:
        return text  # nothing to take off, without parsing every live file
    data = surgery.parse(text).data
    want = own
    if not live:
        as_its_own = {key: value for key, value in data.items() if key != "published"}
        if own is not _ABSENT:
            as_its_own["published"] = own
        if catalog.held_back(rel, as_its_own, now) is None:
            want = False
    have = data.get("published", _ABSENT)
    if have is want or (_ABSENT not in (have, want) and surgery.same_value(have, want)):
        return text
    change = {"published": None if want is _ABSENT else want}
    try:
        return surgery.update_keys(text, change)
    except (surgery.EditError, yaml.YAMLError):
        fm = front_matter_for(page)
        if want is _ABSENT:
            fm.pop("published", None)
        else:
            fm["published"] = want
        return frontmatter.join(fm, from_blocks(list(page.body.get_prep_value()), leading="\n"))


@dataclass
class File:
    """One file an export writes: where, what, and which page it is. A
    `take_down` is the file of a page that is not live in a write-back of the
    live pages: the text the platform last read or wrote for it (`source`),
    marked not built — written only over that very file, never created."""

    rel: str
    text: str
    page: Page
    rendered: Page  # what was rendered: the live page, or its latest revision
    source: ImportedSource | None
    verbatim: bool
    take_down: bool = False
    sidecar: bool = False  # a file written with the page's, not the page's own: an ABC book's spec


def site_files(site_key: str, *, include_drafts=False, report: ExportReport | None = None) -> Iterator[File]:
    """Every file an export of the site writes, in tree order."""
    root = SiteRootPage.objects.get(site_key=site_key)
    pages = Page.objects.descendant_of(root).specific().order_by("path")
    sources = {s.page_id: s for s in ImportedSource.objects.filter(site_key=site_key)}
    newsroom_pages = with_newsroom_front_matter()
    now = timezone.now()
    for page in pages:
        if isinstance(page, CollectionPage):
            continue
        source = sources.get(page.pk)
        if not page.live and not include_drafts:
            if source is None:  # no file of its own yet: nothing to take down, and a draft is not written
                if report is not None:
                    report.skipped.append(f"{page.url_path} (not live)")
                continue
            rel = path_for(page, root)
            text = mark(source.source_text, rel, page, live=False, now=now)
            yield File(rel, text, page, page, source, verbatim=text == source.source_text, take_down=True)
            continue
        current = page.get_latest_revision_as_object() if include_drafts else page
        rel = path_for(current, root)
        unchanged = source is not None and source.unchanged(current)
        moved = source is not None and current.file_editor_fields and source.legacy_path != rel
        if moved and report is not None and source.legacy_path.endswith(SUFFIXES):  # a page's file it was read from
            report.moved.append((source.legacy_path, rel))
        verbatim = unchanged and page.pk not in newsroom_pages
        if verbatim:
            text = mark(source.source_text, rel, current, live=page.live, now=now)
            yield File(rel, text, page, current, source, verbatim=text == source.source_text)
        else:
            text = render(current, source.source_text if source is not None else None)
            text = mark(text, rel, current, live=page.live, now=now)
            yield File(rel, text, page, current, source, verbatim=False)
        if source is not None and source.sidecars:
            yield from _sidecar_files(page, current, source, verbatim)


def _sidecar_files(page, current, source: ImportedSource, verbatim: bool) -> Iterator[File]:
    """An ABC book's spec sidecar, written with its page: as it was read while
    the page is, else agreeing with the page's front matter (books/abc.py)."""
    abc_book = isinstance(current, BookPage) and current.profile == "abc"
    for rel, stored in source.sidecars.items():
        text = stored
        if abc_book and not verbatim:
            letters = (b.value for b in current.body if b.block_type == "letter")
            subjects = {v["letter"]: v["subject"] for v in letters if v.get("subject")}
            text = abc.sidecar_text(stored, front_matter_for(current), subjects)
        yield File(rel, text, page, current, source, verbatim=text == stored, sidecar=True)


def export_site(site_key: str, out, *, include_drafts=False) -> ExportReport:
    out = Path(out).resolve()
    report = ExportReport(site_key=site_key)
    written = set()
    for file in site_files(site_key, include_drafts=include_drafts, report=report):
        if file.take_down:
            report.skipped.append(f"{file.page.url_path} (not live)")
            continue
        target = (out / file.rel).resolve()
        if not str(target).startswith(str(out) + "/"):
            report.skipped.append(f"{file.rel} (outside the export directory)")
            continue
        if target in written:
            report.skipped.append(f"{file.rel} (another page was written there)")
            continue
        written.add(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.text, encoding="utf-8")
        (report.verbatim if file.verbatim else report.rendered).append(file.rel)
    return report
