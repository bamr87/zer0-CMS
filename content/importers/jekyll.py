"""Jekyll (and Obsidian-vault Jekyll) sites → Wagtail pages (PLAN §4.2, M6).

One Jekyll site becomes one `SiteRootPage` (and one Wagtail `Site`) with a
`CollectionPage` per collection. What becomes what:

| In the site                                 | In Wagtail                                   |
|---------------------------------------------|----------------------------------------------|
| `_posts/*`                                  | `ArticlePage` (date, author, tags, categories) |
| a collection document with a `date`         | `ArticlePage`                                |
| `_books/<book>/index.md`                    | `BookPage` (`book-abc` layout → profile abc, its `alphabet:` → `letter` blocks) |
| `_books/<book>/<chapter>.md`                | `ChapterPage` under its book                 |
| any other document or page with front matter | `StandardPage`                              |
| `title`, `description`, `seo_title`        | `title`, `search_description`, `seo_title`   |
| `preview` / `image`                         | a Wagtail image (SVG too) in the site's collection, the file found where Jekyll serves it (`preview_file`) |
| every other front-matter key                | `front_matter`, in source order              |
| the body                                    | StreamField blocks (importers/markdown.py)   |

An ABC book's spec sidecar (`_data/abc_books/<book>.json`, books/abc.py) is
read with its page and kept on its `ImportedSource`, for the exporter to write
the two together; a sync refreshes it while the page has not changed here.

Which files are content is the platform's one Jekyll reader's answer
(sites/catalog.py, Jekyll 4.4's reader rules, held to Jekyll's own lists by
tests/sites/test_catalog.py): pages with front matter (Markdown and HTML),
posts and drafts, the documents of each declared collection, and `include:`d
files. A draft (`_drafts/`) is imported as a draft. A file the reader marks as
unreadable (not UTF-8, front matter that does not parse) is reported as an
error and the rest of the site still imports.

**Idempotent.** A file whose digest has not changed is skipped. A changed file
updates its page — unless an editor changed that page in Wagtail since the
last import (`ImportedSource.unchanged`: its content, or the path and
front-matter order of a page whose file a person edits), in which case it is
reported as a conflict and left alone (`--force` overrides). A new file at a
path a page made or moved in the platform already has (cms/files.py) is that
page's export, not a new page: it is skipped. Pages are published, as
`legacy:import`, unless the front matter says `published: false` or
`draft: true`. Links are indexed in a second pass, once every page of the site
exists.
"""

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from django.core.files.images import ImageFile
from django.db import transaction
from django.utils.text import slugify
from wagtail.images import get_image_model
from wagtail.models import Collection, Page, Site

from agents.principals import ensure_legacy_import_user
from books import abc
from cms.files import holder_of
from cms.models import ArticlePage, BookPage, Category, ChapterPage, CollectionPage, SiteRootPage, StandardPage
from cms.services import publish, save_draft
from sites import catalog, writer

from . import frontmatter
from .markdown import to_blocks
from .models import ImportedSource

DATED_POST = re.compile(r"^(\d{4}-\d{2}-\d{2})-(.+)$")
LETTER_KEYS = ("letter", "word", "tagline", "alt", "subject")


@dataclass
class Document:
    path: Path  # absolute
    rel: str  # relative to the site root (the directory holding _config.yml)
    collection: str | None  # "posts", "books", … or None for a page
    front_matter: dict
    body: str
    text: str
    kind: str = "page"  # the catalog's: page | post | draft | document


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


# ── reading the site ───────────────────────────────────────────────────────


def read_config(root: Path) -> dict:
    path = root / "_config.yml"
    if not path.is_file():
        raise FileNotFoundError(f"{root} has no _config.yml — not a Jekyll site")
    try:
        data, _ = frontmatter.split("---\n" + path.read_text(encoding="utf-8") + "\n---\n")
    except yaml.YAMLError as e:
        raise ValueError(f"{path} is not YAML Jekyll can read: {e}".replace("\n", " ")) from e
    return data or {}


def documents(root: Path, config: dict | None = None, errors: list | None = None) -> list[Document]:
    """The site's content files, as the catalog reads them. A file it cannot
    read as front matter and Markdown is appended to `errors` (when given)."""
    found: list[Document] = []
    for entry in catalog.scan(root).entries:
        try:
            if entry.error:
                raise ValueError(entry.error)
            text = Path(entry.path).read_bytes().decode("utf-8")  # bytes, so CRLF stays CRLF
            data, body = frontmatter.split(text)
        except (ValueError, yaml.YAMLError) as e:
            if errors is not None:
                errors.append(f"{entry.relative}: {e}".replace("\n", " "))
            continue
        found.append(
            Document(
                path=Path(entry.path),
                rel=entry.relative,
                collection=None if entry.kind == "page" else entry.collection,
                front_matter=data or {},
                body=body,
                text=text,
                kind=entry.kind,
            )
        )
    return found


# ── mapping one document ───────────────────────────────────────────────────


def page_class(doc: Document):
    fm = doc.front_matter
    if doc.collection == "books" or fm.get("layout") in ("book", "book-abc"):
        return BookPage if Path(doc.rel).name == "index.md" else ChapterPage
    if doc.collection == "posts" or fm.get("date"):
        return ArticlePage
    return StandardPage


def slug_for(doc: Document) -> str:
    stem = Path(doc.rel).stem
    if stem == "index":
        stem = Path(doc.rel).parent.name or "index"
    match = DATED_POST.match(stem)
    if match:
        stem = match.group(2)
    return slugify(str(doc.front_matter.get("slug") or stem))[:255] or "page"


def _tags(value) -> list[str]:
    if isinstance(value, str):
        return [t for t in re.split(r"[,\s]+", value) if t]
    return [str(t) for t in value or [] if str(t).strip()]


def letter_blocks(alphabet) -> list[dict]:
    blocks = []
    for item in alphabet or []:
        if not isinstance(item, dict) or not re.fullmatch(r"[A-Z]", str(item.get("letter", ""))):
            continue
        blocks.append(
            {
                "type": "letter",
                "value": {
                    "letter": item["letter"],
                    "word": str(item.get("word", ""))[:80],
                    "tagline": str(item.get("tagline", ""))[:250],
                    "subject": str(item.get("subject", ""))[:400],
                    "alt": str(item.get("alt", ""))[:250],
                    "image": None,
                },
            }
        )
    return blocks


def apply_document(page, doc: Document, images: dict):
    fm = doc.front_matter
    page.title = str(fm.get("title") or slug_for(doc).replace("-", " ").title())[:255]
    page.slug = page.slug or slug_for(doc)
    page.seo_title = str(fm.get("seo_title", "") or "")[:255]
    page.search_description = str(fm.get("description", "") or "")
    page.legacy_path = doc.rel
    page.front_matter = fm
    blocks = to_blocks(doc.body)
    if isinstance(page, BookPage):
        layout = fm.get("layout")
        page.profile = (
            "abc" if layout == "book-abc" or fm.get("alphabet") else ("story" if fm.get("illustrations") else "book")
        )
        page.subtitle = str(fm.get("subtitle", "") or "")[:250]
        page.author = str(fm.get("author", "") or "")[:200]
        page.series = str(fm.get("series", "") or "")[:200]
        page.audience = str(fm.get("audience", "") or "")[:80]
        page.art_style = str(fm.get("art_style", "") or "")[:80]
        blocks = blocks + letter_blocks(fm.get("alphabet"))
    if isinstance(page, ChapterPage):
        chapter = fm.get("chapter")
        page.number = int(chapter) if str(chapter).isdigit() else None
    if isinstance(page, ArticlePage):
        page.date = frontmatter.parse_date(fm.get("date")) or _filename_date(doc)
        page.author = str(fm.get("author", "") or "")[:200]
        page.tags.set(_tags(fm.get("tags")))
        page.categories.set(
            [
                Category.objects.get_or_create(slug=slugify(c)[:120] or "uncategorised", defaults={"name": c})[0]
                for c in _tags(fm.get("categories"))
            ]
        )
    page.body = blocks
    preview = fm.get("preview") or fm.get("image")
    if isinstance(preview, str) and preview in images:
        page.preview_image = images[preview]


def _filename_date(doc: Document):
    match = DATED_POST.match(Path(doc.rel).stem)
    return frontmatter.parse_date(match.group(1)) if match else None


def _is_draft(doc: Document) -> bool:
    fm = doc.front_matter
    published = fm.get("published") is False or str(fm.get("published")).lower() == "false"
    return doc.kind == "draft" or published or fm.get("draft") is True


# ── images ─────────────────────────────────────────────────────────────────


def preview_file(root: Path, source: str, value: str) -> Path | None:
    """The file a front-matter `preview`/`image` value names, looked up where
    the site serves it from (rails.assets-terms): `<source>/<value>`, then
    `<source>/assets/<value>` — the image engine writes `/images/previews/x.png`
    for a file in `assets/images/previews/`, and the theme adds the prefix —
    then `<root>/<value>`, without the value's query or fragment. `source` is
    the source directory relative to the root ("" when it is the root). Every
    candidate is confined like any other disk path (sites/writer.py): a plain
    path, no symlink at any component, its realpath inside the root. None for
    an external URL or a file that is not in the site."""
    if "://" in value:
        return None
    path = value.split("#", 1)[0].split("?", 1)[0].lstrip("/")
    prefix = f"{source}/" if source else ""
    for candidate in dict.fromkeys((f"{prefix}{path}", f"{prefix}assets/{path}", path)):
        try:
            return writer.confined_file(root, candidate)
        except writer.Refused:  # NotFound included: try the next place the site serves it from
            continue
    return None


def import_images(root: Path, config: dict, docs: list[Document], collection: Collection) -> dict:
    """Front-matter preview images that exist in the site → Wagtail images, one
    per distinct file, in the site's collection; an SVG is one too (Willow reads
    it with defusedxml). Returns {front-matter value: image}."""
    real_root = writer.root_of(root)
    source = catalog.confine(real_root, real_root, config.get("source"), "source")
    source = "" if source == real_root else source.relative_to(real_root).as_posix()
    Image = get_image_model()
    out = {}
    for doc in docs:
        value = doc.front_matter.get("preview") or doc.front_matter.get("image")
        if not isinstance(value, str) or value in out:
            continue
        path = preview_file(real_root, source, value)
        if path is None:
            continue
        data = path.read_bytes()
        digest = hashlib.sha256(data).hexdigest()
        image = Image.objects.filter(content_hash=digest).first()
        if image is None:
            with path.open("rb") as fh:
                image = Image(title=path.stem, collection=collection, content_hash=digest)
                try:
                    image.file = ImageFile(fh, name=path.name)  # reads the dimensions: a broken file raises here
                    image.save()
                except Exception:  # noqa: BLE001 — an unreadable image is skipped, the page still imports
                    continue
        out[value] = image
    return out


# ── the import ─────────────────────────────────────────────────────────────


def _container(site_root: SiteRootPage, doc: Document, collections: dict, books: dict):
    if page_class(doc) is ChapterPage:
        book_dir = Path(doc.rel).parent.as_posix()
        if book_dir in books:
            return books[book_dir]
    if doc.collection is None:
        return site_root
    if doc.collection not in collections:
        existing = CollectionPage.objects.child_of(site_root).filter(collection=doc.collection).first()
        if existing is None:
            page = CollectionPage(
                title=doc.collection.replace("_", " ").title(),
                slug=_unique_slug(site_root, slugify(doc.collection) or "collection"),
                collection=doc.collection,
                output_dir="/".join(
                    p
                    for p in (
                        str((site_root.jekyll_config or {}).get("collections_dir") or "").strip("/"),
                        f"_{doc.collection}",
                    )
                    if p
                ),
            )
            site_root.add_child(instance=page)
            publish(page, user=ensure_legacy_import_user())
            existing = page
        collections[doc.collection] = existing
    return collections[doc.collection]


def _unique_slug(parent, slug: str, exclude_pk=None) -> str:
    siblings = set(parent.get_children().exclude(pk=exclude_pk).values_list("slug", flat=True))
    candidate, n = slug, 2
    while candidate in siblings:
        candidate = f"{slug}-{n}"[:255]
        n += 1
    return candidate


def ensure_site_root(site_key: str, root: Path, config: dict, repo_root: Path) -> SiteRootPage:
    existing = SiteRootPage.objects.filter(site_key=site_key).first()
    if existing is not None:
        return existing
    top = Page.get_first_root_node()
    title = str(config.get("title") or site_key)
    try:
        source_root = root.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        source_root = str(root)
    page = SiteRootPage(
        title=title[:255],
        slug=_unique_slug(top, slugify(site_key)),
        site_key=site_key,
        source_root=source_root,
        jekyll_config={
            k: config.get(k)
            for k in ("title", "url", "baseurl", "collections_dir", "source")
            if config.get(k) is not None
        },
    )
    top.add_child(instance=page)
    publish(page, user=ensure_legacy_import_user())
    Site.objects.get_or_create(
        hostname=f"{site_key}.localhost",
        port=80,
        defaults={
            "root_page": page,
            "site_name": title[:255],
            "is_default_site": not Site.objects.filter(is_default_site=True).exists(),
        },
    )
    return page


def import_site(root, site_key: str, *, force=False, repo_root=None) -> Report:
    from django.conf import settings

    root = Path(root)
    repo_root = Path(repo_root or settings.REPO_ROOT)
    config = read_config(root)
    report = Report(site_key=site_key)
    docs = documents(root, config, report.errors)
    importer = ensure_legacy_import_user()
    with transaction.atomic():
        site_root = ensure_site_root(site_key, root, config, repo_root)
        collection = Collection.objects.filter(name=f"site: {site_key}").first()
        if collection is None:
            collection = Collection.get_first_root_node().add_child(name=f"site: {site_key}")
        images = import_images(root, config, docs, collection)
        collections, books = {}, {}
        # Books before chapters, so a chapter finds its book.
        ordered = sorted(docs, key=lambda d: (page_class(d) is ChapterPage, d.rel))
        for doc in ordered:
            try:
                with transaction.atomic():
                    _import_document(doc, site_key, site_root, collections, books, images, importer, force, report)
            except Exception as e:  # noqa: BLE001 — one bad file is reported; the rest of the site still imports
                report.errors.append(f"{doc.rel}: {type(e).__name__}: {e}")
        from graph.services import index_page

        for source in ImportedSource.objects.filter(site_key=site_key).select_related("page"):
            page = source.page.specific
            if page.live:
                index_page(page)
    return report


def _import_document(doc, site_key, site_root, collections, books, images, importer, force, report):
    digest = hashlib.sha256(doc.text.encode()).hexdigest()
    source = ImportedSource.objects.filter(site_key=site_key, legacy_path=doc.rel).select_related("page").first()
    cls = page_class(doc)
    if source is not None:
        page = source.page.specific
        if isinstance(page, BookPage):
            books[Path(doc.rel).parent.as_posix()] = page
        if source.source_digest == digest:
            sidecars = _sidecars(doc, page)
            if sidecars != source.sidecars and (
                not source.sidecars or source.unchanged(page.get_latest_revision_as_object())
            ):
                source.sidecars = sidecars
                source.save(update_fields=["sidecars"])
            report.unchanged.append(doc.rel)
            return
        current = page.get_latest_revision_as_object()
        if not source.unchanged(current) and not force:
            report.conflicts.append(f"{doc.rel}: changed in Wagtail since the last import (pass --force to overwrite)")
            return
        apply_document(current, doc, images)
        _save(current, doc, importer)
        source.source_text, source.source_digest = doc.text, digest
        source.import_hash = current.compute_content_hash()
        source.sidecars = _sidecars(doc, current)
        source.save()
        report.updated.append(doc.rel)
        return
    if holder_of(doc.rel, site_root):  # a page made or moved here writes this file: the platform's, not a new page
        report.unchanged.append(doc.rel)
        return
    parent = _container(site_root, doc, collections, books)
    page = cls(slug="")
    apply_document(page, doc, images)
    page.slug = _unique_slug(parent, page.slug)
    page.live = False
    parent.add_child(instance=page)
    _save(page, doc, importer)
    page.refresh_from_db()
    page = page.specific
    if isinstance(page, BookPage):
        books[Path(doc.rel).parent.as_posix()] = page
    ImportedSource.objects.create(
        page=page,
        site_key=site_key,
        legacy_path=doc.rel,
        source_text=doc.text,
        source_digest=digest,
        import_hash=page.get_latest_revision_as_object().compute_content_hash(),
        sidecars=_sidecars(doc, page),
    )
    report.created.append(doc.rel)


def _sidecars(doc: Document, page) -> dict:
    """The files read with the document's: an ABC book's spec sidecar, at
    `_data/abc_books/<book>.json` under the site root, when it has one —
    {path: text}. Read through the confined reader, so a symlink or a path
    that leaves the site is never followed."""
    if not (isinstance(page, BookPage) and page.profile == "abc"):
        return {}
    rel = abc.sidecar_path(doc.front_matter.get("book"))
    if rel is None:
        return {}
    root = doc.path.parents[len(Path(doc.rel).parts) - 1]
    try:
        data = writer.read_bytes(root, rel)
        return {} if data is None else {rel: data.decode("utf-8")}
    except (writer.Refused, UnicodeDecodeError):
        return {}  # not a file the platform reads: the book exports without it, as before


def _save(page, doc, importer):
    if _is_draft(doc):
        save_draft(page, user=importer)
    else:
        publish(page, user=importer)
