"""Wagtail pages → a Jekyll site's Markdown files (PLAN §4, M7).

For each page under a site root, in tree order:

- **unchanged since import** (its `content_hash` still equals the import's)
  and without bylines or corrections from the newsroom: the stored source
  file, byte for byte;
- **changed since import**: the source file with only what changed rewritten
  — the front matter by line surgery (sites/frontmatter.py: a key whose value
  changed is rewritten in place, a new one goes in before the closing fence, a
  dropped one goes, and comments, quoting and every other line stay as they
  were), the body kept as it was while its blocks are the ones it was read as;
- **created in Wagtail** (or a source the surgery cannot edit): front matter +
  body rendered from the page. Either way the front matter is the source's, in
  its original key order, with the typed fields written over it (title, description, seo_title, date — kept as
  the original string when the parsed date did not change —, author, tags,
  categories, book fields), and for an ABC book the `alphabet:` list rebuilt
  from its `letter` blocks, each merged into the original entry so a plate's
  `image`, `prompt` and `status` survive an edit to its word; a story's
  `authors` (its bylines) and `corrections` (its corrections and updates log:
  date, kind, text) come from the newsroom, for the site to render. The body
  is the blocks as Markdown (importers/markdown.py).

A page keeps the file it was read from or last written to (its
`ImportedSource`). A page created in Wagtail gets a path from its type: an
`ArticlePage` in `_posts` becomes `<collections_dir>/_posts/YYYY-MM-DD-<slug>.md`,
anything in another collection `<collections_dir>/_<collection>/<slug>.md`, a
page at the site root `<slug>.md` — the slug transliterated to `a-z0-9` and
hyphens (sites/writer.py). Only live pages are exported unless
`include_drafts`. `site_files` lists what an export writes; `export_site`
writes it into `out` and nothing else, refusing a path that would leave it,
and a site's write-back writes it into the site's checkout under the
stale-write guard (sites/services.py).
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from wagtail.models import Page

from cms.models import ArticlePage, BookPage, ChapterPage, CollectionPage, SiteRootPage
from importers import frontmatter
from importers.markdown import from_blocks, to_blocks
from importers.models import ImportedSource
from newsroom.services import front_matter_for as newsroom_front_matter
from newsroom.services import with_front_matter as with_newsroom_front_matter
from sites import frontmatter as surgery
from sites.writer import slugify


@dataclass
class ExportReport:
    site_key: str
    verbatim: list = field(default_factory=list)
    rendered: list = field(default_factory=list)
    skipped: list = field(default_factory=list)

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


def _alphabet(page, original) -> list | None:
    letters = [b for b in page.body if b.block_type == "letter"]
    if not letters:
        return original
    by_letter = {str(item.get("letter")): item for item in (original or []) if isinstance(item, dict)}
    out = []
    for block in letters:
        value = block.value
        item = dict(by_letter.get(value["letter"], {}))
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
    fm = dict(page.front_matter or {})

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
            alphabet = _alphabet(page, fm.get("alphabet"))
            if alphabet is not None:
                fm["alphabet"] = alphabet
    if isinstance(page, ChapterPage) and page.number is not None:
        fm["chapter"] = page.number
    fm.update(newsroom_front_matter(page))
    return fm


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
    changes = {key: value for key, value in fm.items() if key not in original or original[key] != value}
    changes.update({key: None for key in original if key not in fm})
    text = surgery.update_keys(source_text, changes)
    _, body = frontmatter.split(text)
    mine = [(b["type"], b["value"]) for b in blocks if b["type"] != "letter"]
    if mine == [(b["type"], b["value"]) for b in to_blocks(body)]:
        return text
    return text[: len(text) - len(body)] + from_blocks(blocks, leading=leading)


@dataclass
class File:
    """One file an export writes: where, what, and which page it is."""

    rel: str
    text: str
    page: Page
    rendered: Page  # what was rendered: the live page, or its latest revision
    source: ImportedSource | None
    verbatim: bool


def site_files(site_key: str, *, include_drafts=False, report: ExportReport | None = None) -> Iterator[File]:
    """Every file an export of the site writes, in tree order."""
    root = SiteRootPage.objects.get(site_key=site_key)
    pages = Page.objects.descendant_of(root).specific().order_by("path")
    sources = {s.page_id: s for s in ImportedSource.objects.filter(site_key=site_key)}
    newsroom_pages = with_newsroom_front_matter()
    for page in pages:
        if isinstance(page, CollectionPage):
            continue
        if not page.live and not include_drafts:
            if report is not None:
                report.skipped.append(f"{page.url_path} (not live)")
            continue
        current = page.get_latest_revision_as_object() if include_drafts else page
        source = sources.get(page.pk)
        rel = source.legacy_path if source is not None else path_for(current, root)
        unchanged = source is not None and current.compute_content_hash() == source.import_hash
        if unchanged and page.pk not in newsroom_pages:
            yield File(rel, source.source_text, page, current, source, verbatim=True)
        else:
            text = render(current, source.source_text if source is not None else None)
            yield File(rel, text, page, current, source, verbatim=False)


def export_site(site_key: str, out, *, include_drafts=False) -> ExportReport:
    out = Path(out).resolve()
    report = ExportReport(site_key=site_key)
    for file in site_files(site_key, include_drafts=include_drafts, report=report):
        target = (out / file.rel).resolve()
        if not str(target).startswith(str(out) + "/"):
            report.skipped.append(f"{file.rel} (outside the export directory)")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(file.text, encoding="utf-8")
        (report.verbatim if file.verbatim else report.rendered).append(file.rel)
    return report
