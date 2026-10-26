"""Wagtail pages → a Jekyll site's Markdown files (PLAN §4, M7).

For each page under a site root, in tree order:

- **unchanged since import** (its `content_hash` still equals the import's)
  and without bylines or corrections from the newsroom: the stored source
  file, byte for byte;
- **changed, or created in Wagtail**: front matter + body rendered from the
  page. The front matter is the source's, in its original key order, with the
  typed fields written over it (title, description, seo_title, date — kept as
  the original string when the parsed date did not change —, author, tags,
  categories, book fields), and for an ABC book the `alphabet:` list rebuilt
  from its `letter` blocks, each merged into the original entry so a plate's
  `image`, `prompt` and `status` survive an edit to its word; a story's
  `authors` (its bylines) and `corrections` (its corrections and updates log:
  date, kind, text) come from the newsroom, for the site to render. The body
  is the blocks as Markdown (importers/markdown.py).

A page created in Wagtail gets a path from its type: an `ArticlePage` in
`_posts` becomes `<collections_dir>/_posts/YYYY-MM-DD-<slug>.md`, anything in
another collection `<collections_dir>/_<collection>/<slug>.md`, a page at the
site root `<slug>.md`. Only live pages are exported unless `include_drafts`;
an export writes into `out` and nothing else, and refuses a path that would
leave it.
"""

from dataclasses import dataclass, field
from pathlib import Path

from wagtail.models import Page

from cms.models import ArticlePage, BookPage, ChapterPage, CollectionPage, SiteRootPage
from importers import frontmatter
from importers.markdown import from_blocks
from importers.models import ImportedSource
from newsroom.services import front_matter_for as newsroom_front_matter
from newsroom.services import with_front_matter as with_newsroom_front_matter


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
            return f"{folder}/{page.date:%Y-%m-%d}-{page.slug}.md"
        if isinstance(page, BookPage):
            return f"{folder}/{page.slug}/index.md"
        return f"{folder}/{page.slug}.md"
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


def render(page) -> str:
    leading = "\n" if any(b.block_type != "letter" for b in page.body) else ""
    body = from_blocks(list(page.body.get_prep_value()), leading=leading or "\n")
    return frontmatter.join(front_matter_for(page), body)


def export_site(site_key: str, out, *, include_drafts=False) -> ExportReport:
    root = SiteRootPage.objects.get(site_key=site_key)
    out = Path(out).resolve()
    report = ExportReport(site_key=site_key)
    pages = Page.objects.descendant_of(root).specific().order_by("path")
    sources = {s.page_id: s for s in ImportedSource.objects.filter(site_key=site_key)}
    newsroom_pages = with_newsroom_front_matter()
    for page in pages:
        if isinstance(page, CollectionPage):
            continue
        if not page.live and not include_drafts:
            report.skipped.append(f"{page.url_path} (not live)")
            continue
        current = page.get_latest_revision_as_object() if include_drafts else page
        rel = path_for(current, root)
        target = (out / rel).resolve()
        if not str(target).startswith(str(out) + "/"):
            report.skipped.append(f"{rel} (outside the export directory)")
            continue
        source = sources.get(page.pk)
        target.parent.mkdir(parents=True, exist_ok=True)
        unchanged = source is not None and current.compute_content_hash() == source.import_hash
        if unchanged and page.pk not in newsroom_pages:
            target.write_text(source.source_text, encoding="utf-8")
            report.verbatim.append(rel)
        else:
            target.write_text(render(current), encoding="utf-8")
            report.rendered.append(rel)
    return report
