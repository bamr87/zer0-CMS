"""Resolve an Obsidian vault's syntax in a Jekyll source tree, before a plugin-less Jekyll builds it.

zer0-pages's plugins did this inside the build, from what Jekyll had read: each
document's URL and data (`item.url`, `item.data`) fed the wikilink index and the
Dataview pool. Without plugins nothing runs inside the build, so this module
reads the tree the way Jekyll 4.4 does for the part the bridge used — every
collection document and Markdown page with the URL and data Jekyll gives it,
and every static file — then rewrites each page's Markdown (`bridge.transform`)
and writes the graph index as a page of its own, and after the build puts the
base URL on the built pages' root-relative links (`bridge.postprocess_html`).

What it reproduces of Jekyll, from Jekyll 4.4.1's own reader: the entry filter
(no `.`/`_`/`#`/`~` entries, `exclude:` with Jekyll 4's default excludes, which
`include:` overrides), posts from `_posts` (dated file names only, not
unpublished, not in the future), the other collections from `collections_dir`,
front matter defaults, a document's title, slug, date, categories and tags as
Jekyll fills them in, URLs from `permalink:` front matter, the collection's
template or the page template (pretty or not), and a collection's documents in
Jekyll's order (date, then path). Theme files are not read: the theme arrives
with the build, and nothing in the vault links to one of its files.
"""

from __future__ import annotations

import datetime as dt
import fnmatch
import os
import posixpath
import re
import unicodedata
from dataclasses import dataclass, field
from functools import cmp_to_key
from pathlib import Path
from typing import Optional
from urllib.parse import quote, unquote

import yaml

from . import bridge, graph_index
from .dataview import to_s

FRONT_MATTER = re.compile(r"\A(---\s*\n.*?\n?)^((---|\.\.\.)\s*$\n?)", re.DOTALL | re.MULTILINE)
HAS_FRONT_MATTER = re.compile(rb"\A---\s*\r?\n")
DATED = re.compile(r"(\d{2,4}-\d{1,2}-\d{1,2})-([^/]*)(\.[^.]+)\Z")
DATELESS = re.compile(r"(.*)(\.[^.]+)\Z")
SPECIAL = (".", "_", "#", "~")
DEFAULT_EXCLUDES = [".sass-cache", ".jekyll-cache", "gemfiles", "Gemfile", "Gemfile.lock", "node_modules",
                    "vendor/bundle/", "vendor/cache/", "vendor/gems/", "vendor/ruby/"]  # fmt: skip
STYLES = {"pretty": "/:categories/:year/:month/:day/:title/", "date": "/:categories/:year/:month/:day/:title:output_ext",
          "none": "/:categories/:title:output_ext", "ordinal": "/:categories/:year/:y_day/:title:output_ext"}  # fmt: skip
INDEX_PAGE = "assets/data/wiki-index.json"


@dataclass
class Item:
    """A document or page as the bridge saw it: its path under the source, URL, data and Markdown body."""

    path: str
    url: str
    data: dict
    content: str = ""
    collection: Optional[str] = None
    file: Optional[Path] = None
    head: str = ""  # the front matter block, kept byte for byte

    @property
    def markdown(self) -> bool:
        return posixpath.splitext(self.path)[1].lower() in bridge.MD_EXTS


@dataclass
class Site:
    documents: list = field(default_factory=list)  # every collection's, in Jekyll's order
    pages: list = field(default_factory=list)
    static_files: list = field(default_factory=list)  # [(path, url)]

    @property
    def items(self) -> list:
        """What the bridge works on: every document, then every Markdown page."""
        return self.documents + [p for p in self.pages if p.markdown]


# ── reading the tree ────────────────────────────────────────────────────────


def ruby_split(text: str, separator: str) -> list:
    parts = text.split(separator)
    while parts and not parts[-1]:
        parts.pop()
    return parts


def utc(value) -> Optional[dt.datetime]:
    """A front matter date as the UTC time Jekyll reads it as (every build runs in UTC)."""
    if isinstance(value, dt.datetime):
        return value.astimezone(dt.timezone.utc) if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    if isinstance(value, str):
        try:
            return utc(dt.datetime.fromisoformat(value.strip().replace("Z", "+00:00")))
        except ValueError:
            return None
    return None


def split_front_matter(text: str) -> tuple[str, dict, str]:
    """(the front matter block, its data, the body) — the body is what a plugin saw as `content`."""
    m = FRONT_MATTER.match(text)
    if not m:
        return "", {}, text
    try:
        data = yaml.safe_load(m[1]) or {}
    except yaml.YAMLError:  # Jekyll logs a bad front matter block and reads the page with no data
        data = {}
    return m[0], data if isinstance(data, dict) else {}, text[m.end() :]


class Reader:
    def __init__(self, source: Path, config: dict, now: dt.datetime) -> None:
        self.source, self.config, self.now = source, config, now
        include = list(config.get("include") or [".htaccess"])
        self.include = include
        self.exclude = [e for e in list(config.get("exclude") or []) + DEFAULT_EXCLUDES if e not in include]
        collections = config.get("collections") or {}
        if isinstance(collections, list):
            collections = {name: {} for name in collections}
        self.collections = {"posts": {}, **collections}
        style = str(config.get("permalink") or "date")
        self.permalink_style = style
        if "permalink" not in self.collections["posts"] or not self.collections["posts"].get("permalink"):
            self.collections["posts"] = {**self.collections["posts"], "permalink": STYLES.get(style, style)}
        self.collections_dir = str(config.get("collections_dir") or "").strip("/")
        self.defaults = config.get("defaults") or []

    # Jekyll's EntryFilter, with paths relative to the source.
    def _matches(self, patterns: list, rel: str) -> bool:
        full = posixpath.join("/src", rel)
        is_dir = (self.source / rel).is_dir()
        for pattern in patterns:
            target = posixpath.join("/src", str(pattern))
            if fnmatch.fnmatchcase(full, target) or full.startswith(target) or (is_dir and target == full + "/"):
                return True
        return False

    def keep(self, entry: str, base: str = "") -> bool:
        if entry.endswith("."):
            return False
        rel = posixpath.join(base, entry) if base else entry
        included = self._matches(self.include, entry) or self._matches(self.include, posixpath.basename(entry))
        if self._matches(self.exclude, rel) and not included:
            return False
        if included:
            return True
        name = posixpath.basename(entry)
        return not (entry.startswith(SPECIAL) or name.startswith(SPECIAL) or entry.endswith("~"))

    def front_matter_defaults(self, rel: str, kind: str) -> dict:
        merged: dict = {}
        for rule in self.defaults:
            scope = rule.get("scope") or {}
            path = str(scope.get("path") or "").strip("/")
            if path and not (fnmatch.fnmatchcase(rel, path) if "*" in path else rel.startswith(path)):
                continue
            if scope.get("type") and str(scope["type"]) != kind:
                continue
            merged = deep_merge(merged, rule.get("values") or {})
        return merged

    def read(self) -> Site:
        site = Site()
        self._walk("", site)
        for label in self.collections:
            if label != "posts":
                site.documents += self._sorted(self._collection(label, site))
        posts = [d for d in site.documents if d.collection == "posts"]
        site.documents = self._sorted(posts) + [d for d in site.documents if d.collection != "posts"]
        site.pages.sort(key=lambda p: (posixpath.basename(p.path), p.path))
        site.static_files.sort()
        return site

    def _walk(self, rel_dir: str, site: Site) -> None:
        directory = self.source / rel_dir
        if (directory / "_posts").is_dir():
            site.documents += self._posts(posixpath.join(rel_dir, "_posts") if rel_dir else "_posts")
        for entry in sorted(os.listdir(directory)):
            rel = posixpath.join(rel_dir, entry) if rel_dir else entry
            if not self.keep(rel):
                continue
            path = self.source / rel
            if path.is_dir():
                self._walk(rel, site)
            elif HAS_FRONT_MATTER.match(path.read_bytes()[:16]):
                page = self._page(rel)
                if page.data.get("published", True) is not False:
                    site.pages.append(page)
            else:
                site.static_files.append((rel, "/" + escape_path(rel)))

    def _posts(self, posts_dir: str) -> list:
        found = []
        base = self.source / posts_dir
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            entry = path.relative_to(base).as_posix()
            if not self.keep(entry, posts_dir) or not DATED.search(entry.rsplit("/", 1)[-1]):
                continue
            doc = self._document(posixpath.join(posts_dir, entry), "posts", posts_dir)
            published = doc.data.get("published", True) is not False
            if published and (self.config.get("future") or doc.data["date"] <= self.now):
                found.append(doc)
        return found

    def _collection(self, label: str, site: Site) -> list:
        relative_dir = posixpath.join(self.collections_dir, "_" + label) if self.collections_dir else "_" + label
        base = self.source / relative_dir
        if not base.is_dir():
            return []
        docs = []
        for path in sorted(p for p in base.rglob("*") if p.is_file()):
            entry = path.relative_to(base).as_posix()
            if not self.keep(entry, relative_dir):
                continue
            rel = posixpath.join(relative_dir, entry)
            if HAS_FRONT_MATTER.match(path.read_bytes()[:16]):
                doc = self._document(rel, label, relative_dir)
                if doc.data.get("published", True) is not False:
                    docs.append(doc)
            elif (self.collections[label] or {}).get("output"):
                site.static_files.append((rel, "/" + escape_path(rel)))
        return docs

    def _sorted(self, docs: list) -> list:
        def order(a: Item, b: Item) -> int:
            da, db = a.data.get("date"), b.data.get("date")
            if da is not None and db is not None and da != db:
                return -1 if da < db else 1
            return (a.path > b.path) - (a.path < b.path)

        return sorted(docs, key=cmp_to_key(order))

    def _read(self, rel: str) -> tuple[str, dict, str]:
        text = (self.source / rel).read_text(encoding="utf-8-sig")
        return split_front_matter(text)

    def _document(self, rel: str, label: str, relative_dir: str) -> Item:
        head, front, body = self._read(rel)
        data: dict = {"draft": False, "categories": []}
        special = "_posts" if label == "posts" else relative_dir
        if not rel.startswith(special):  # a post under blog/_posts/ is in the category "blog"
            name = rel.rsplit("/", 1)[-1]
            data["categories"] = [c for c in re.sub(re.escape(special) + ".*", "", rel).split("/") if c and c != name]
        data = deep_merge(data, self.front_matter_defaults(rel, label))
        data = merge_front_matter(data, front)
        name = rel.rsplit("/", 1)[-1]
        if m := DATED.search(name):
            date, slug, ext = m.groups()
            if data.get("date") is None:
                data["date"] = utc(dt.date.fromisoformat("-".join(part.zfill(2) for part in date.split("-"))))
        else:
            m = DATELESS.search(name)
            slug, ext = m.groups() if m else (name, None)
        slug = re.sub(r"\.*\Z", "", slug)
        data.setdefault("title", None)
        if data["title"] is None:
            data["title"] = " ".join(part.capitalize() for part in ruby_split(slug, "-"))
        if data.get("slug") is None:
            data["slug"] = slug
        if data.get("ext") is None:
            data["ext"] = ext
        categories = _flatten([data.get("categories"), _plural(data, "category", "categories")])
        data["categories"] = list(dict.fromkeys(to_s(c) for c in categories))
        data["tags"] = _flatten([_plural(data, "tag", "tags")])
        doc = Item(rel, "", data, body, label, self.source / rel, head)
        cleaned = re.sub(r"\.*\Z", "", rel[: -len(posixpath.splitext(rel)[1])] if posixpath.splitext(rel)[1] else rel)
        cleaned = cleaned.replace(relative_dir, "", 1)
        template = (self.collections[label] or {}).get("permalink") or add_suffix("/:collection/:path", self.permalink_style)
        placeholders = {
            "collection": label,
            "path": cleaned,
            "name": slugify(posixpath.splitext(name)[0]),
            "title": slugify(str(data["slug"]), mode="pretty", cased=True),
            "slug": slugify(str(data["slug"])),
            "categories": "/".join(dict.fromkeys(str(c).lower() for c in data["categories"])),
            "output_ext": ".html" if doc.markdown else posixpath.splitext(rel)[1],
        }
        when = data.get("date") or self.now
        placeholders.update(
            year=when.strftime("%Y"), month=when.strftime("%m"), day=when.strftime("%d"),
            hour=when.strftime("%H"), minute=when.strftime("%M"), second=when.strftime("%S"),
            i_day=str(when.day), i_month=str(when.month), short_year=when.strftime("%y"), y_day=when.strftime("%j"),
        )  # fmt: skip
        doc.url = url_for(data.get("permalink") or template, placeholders, drop=True)
        return doc

    def _page(self, rel: str) -> Item:
        head, front, body = self._read(rel)
        data = merge_front_matter(self.front_matter_defaults(rel, "pages"), front)
        directory, name = posixpath.split(rel)
        stem, ext = posixpath.splitext(name)
        basename = re.sub(r"\.*\Z", "", stem)
        markdown = ext.lower() in (".md", ".markdown", ".mkdown", ".mkdn", ".mkd")
        output_ext = ".html" if markdown or ext.lower() in (".html", ".xhtml", ".htm") else ext
        if output_ext not in (".html", ".xhtml", ".htm"):
            template = "/:path/:basename:output_ext"
        elif basename == "index":
            template = "/:path/"
        else:
            template = add_suffix("/:path/:basename", self.permalink_style)
        placeholders = {"path": directory, "basename": basename, "output_ext": output_ext}
        url = url_for(data.get("permalink") or template, placeholders, drop=False)
        return Item(rel, url, data, body, None, self.source / rel, head)


def _plural(data: dict, singular: str, plural: str) -> list:
    """Jekyll's `pluralized_array_from_hash`: the singular key's value, else the plural's (a string split on spaces)."""
    if data.get(singular) is not None:
        return _flatten([data[singular]])
    value = data.get(plural)
    if isinstance(value, str):
        return value.split()
    return [v for v in value if v is not None] if isinstance(value, list) else []


def _flatten(values: list) -> list:
    out = []
    for value in values:
        if isinstance(value, list):
            out += _flatten(value)
        elif value is not None:
            out.append(value)
    return out


def deep_merge(base: dict, other: dict) -> dict:
    merged = dict(base)
    for key, value in other.items():
        merged[key] = deep_merge(merged[key], value) if isinstance(value, dict) and isinstance(merged.get(key), dict) else value
    return merged


def merge_front_matter(data: dict, front: dict) -> dict:
    front = dict(front)
    if isinstance(front.get("categories"), str):
        front["categories"] = front["categories"].split()
    if isinstance(front.get("categories"), list) and isinstance(data.get("categories"), list):
        front["categories"] = list(dict.fromkeys([*data["categories"], *front["categories"]]))
    merged = deep_merge(data, front)
    if "date" in front and merged.get("date") is not None:
        merged["date"] = utc(merged["date"])
    return merged


def add_suffix(template: str, style: str) -> str:
    if style == "pretty" or style.endswith("/"):
        return template + "/"
    if style in ("date", "ordinal", "none") or style.endswith(":output_ext"):
        return template + ":output_ext"
    return template


def slugify(text: str, mode: str = "default", cased: bool = False) -> str:
    """Jekyll's `Utils.slugify` in its default and pretty modes: every run of characters that are not
    letters, marks or decimal digits (nor, when pretty, `._~!$&'()+,;=@`) becomes one hyphen."""
    extra = "._~!$&'()+,;=@" if mode == "pretty" else ""

    def kept(char: str) -> bool:
        kind = unicodedata.category(char)
        return kind[0] in "LM" or kind == "Nd" or char in extra

    slug, run = [], False
    for char in text:
        if kept(char):
            slug.append(char)
            run = False
        elif not run:
            slug.append("-")
            run = True
    slug = re.sub(r"^-|-$", "", "".join(slug), flags=re.MULTILINE)
    return slug if cased else slug.lower()


def escape_path(path: str) -> str:
    """Jekyll's `URL.escape_path`: unchanged when plain, else percent-encoded as a URI path."""
    if not path or re.fullmatch(r"[a-zA-Z0-9./-]+", path):
        return path
    return quote(path, safe="/!$&'()*+,;=:@~").replace("#", "%23")


def _from_drop(match: re.Match, placeholders: dict) -> str:
    """One `:name` of a document's template; `:month_` is `:month` followed by an underscore."""
    name = match[1]
    winner = name if name in placeholders else name[:-1] if name.endswith("_") and name[:-1] in placeholders else None
    if winner is None:
        raise KeyError(f"the URL template has no :{name} placeholder")
    value = placeholders[winner]
    return match[0].replace(f":{winner}", escape_path("" if value is None else str(value)), 1)


def url_for(template: str, placeholders: dict, drop: bool) -> str:
    """Jekyll's `URL#to_s` over a template or a front matter permalink."""
    if drop:
        url = re.sub(r":([a-z_]+)", lambda m: _from_drop(m, placeholders), template)
    else:
        url = template
        for key, value in placeholders.items():
            if ":" not in url:
                break
            url = url.replace(f"/:{key}", "") if value is None else url.replace(f":{key}", escape_path(str(value)))
    url = ("/" + url).replace("..", "/").replace("./", "")
    return re.sub(r"/+", "/", url)


# ── the bridge over a tree ──────────────────────────────────────────────────


def resolve(source: Path, config: dict, now: Optional[dt.datetime] = None) -> list:
    """Rewrite every document's and Markdown page's Markdown under `source` as the bridge did, and write the
    graph index page; returns the rewritten items, whose built pages `postprocess` finishes."""
    now = now or dt.datetime.now(dt.timezone.utc)
    site = Reader(source, config, now).read()
    items = site.items
    entries = [{"path": i.path, "url": i.url, "aliases": i.data.get("aliases")} for i in items]
    entries += [{"path": path, "url": url, "aliases": []} for path, url in site.static_files]
    resolver = bridge.resolver_for(bridge.build_index(entries))
    pool = [
        {"title": Path(i.path).stem if i.data.get("title") is None else i.data["title"], "url": i.url, "path": i.path, "fm": i.data}
        for i in items
    ]
    baseurl = str(config.get("baseurl") or "")
    graph = [
        {
            "title": i.data.get("title"),
            "path": i.path,
            "url": baseurl + i.url,
            "collection": i.collection,
            "tags": i.data.get("tags"),
            "categories": i.data.get("categories"),
            "aliases": i.data.get("aliases"),
            "content": i.content,
        }
        for i in items
    ]
    for item in items:
        if item.markdown and item.content:
            item.file.write_text(item.head + bridge.transform(item.content, resolver, pool), encoding="utf-8")
    index = source / INDEX_PAGE
    index.parent.mkdir(parents=True, exist_ok=True)
    front = "---\nlayout: null\nsitemap: false\nrender_with_liquid: false\npermalink: /assets/data/wiki-index.json\n---\n"
    index.write_text(front + graph_index.to_json(graph, now), encoding="utf-8")
    return [item for item in items if item.markdown]


def postprocess(destination: Path, items: list, config: dict) -> None:
    """The built pages of the rewritten items, with the base URL on their root-relative links."""
    baseurl, site_url = str(config.get("baseurl") or ""), str(config.get("url") or "")
    if not baseurl:
        return
    for item in items:
        rel = unquote(item.url).lstrip("/")
        if item.url.endswith("/"):
            rel += "index.html"
        elif not rel.endswith(".html"):
            rel += ".html"
        built = destination / rel
        if built.is_file():
            built.write_text(bridge.postprocess_html(built.read_text(encoding="utf-8"), baseurl, site_url), encoding="utf-8")
