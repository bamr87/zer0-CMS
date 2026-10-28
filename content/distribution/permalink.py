"""The URL Jekyll 4.4 gives a page, post or collection document — the canonical
URL an article share links to and the ledger is keyed by.

Ported from the Ruby lane's `Distribution::Permalink` (itself transcribed from
Jekyll's `URL`, `Drops::UrlDrop`, `Document#url` and `Page#template`), and held
to what it computed on every site in this repository (`tests/distribution/
golden/ruby-lane.json`):

* a `permalink:` in the file's front matter wins, then one set by a matching
  `defaults:` scope, then the collection's `permalink`, then (posts only) the
  site's `permalink` style, then Jekyll's defaults;
* placeholders — `:collection :path :name :title :slug :categories :year :month
  :day :i_month :i_day :short_year :y_day :output_ext :basename` — are filled the
  way UrlDrop fills them, with Jekyll's slugify;
* the result is sanitized as `URL#sanitize_url` does it.

`:year`, `:month` and `:day` come from the calendar date as written
(`2026-07-08…` → 2026/07/08), never from a time converted to a zone. Both the
platform (`services.canonical_url`) and a site's own lane (`lane/`) call
`path_for`, so the two key a page the same way.
"""

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from posixpath import basename, dirname, splitext

STYLES = {
    "date": "/:categories/:year/:month/:day/:title:output_ext",
    "pretty": "/:categories/:year/:month/:day/:title/",
    "ordinal": "/:categories/:year/:y_day/:title:output_ext",
    "weekdate": "/:categories/:year/W:week/:short_day/:title:output_ext",
    "none": "/:categories/:title:output_ext",
}
COLLECTION_DEFAULT = "/:collection/:path:output_ext"
TOKEN = re.compile(
    r"/?:(output_ext|short_year|i_month|i_day|y_day|collection|categories|basename|path|name|title|slug|year|month|day)"
)
DATED = re.compile(r"\A\d{2,4}-\d{1,2}-\d{1,2}-")
PRETTY_KEEP = set("._~!$&'()+,;=@")
SAFE_PATH = re.compile(r"[^a-zA-Z0-9_.\-~!$&'()*+,;=:@/]")


@dataclass
class Entry:
    """What a URL is computed from: the file's path under the site's source, its kind
    (`post`, `document`, `page`), its collection, its front matter and its date."""

    source_relative: str
    kind: str
    collection: str = ""
    data: dict = field(default_factory=dict)
    date_raw: str = ""
    date: datetime | None = None

    @property
    def permalink(self) -> str:
        value = self.data.get("permalink")
        return value.strip() if isinstance(value, str) else ""


def path_for(site_config: dict, entry: Entry) -> str | None:
    """The site-relative URL path, or None for a draft (it has none)."""
    if entry.kind == "draft":
        return None
    template = entry.permalink or str(default_permalink(site_config, entry) or "")
    if not template:
        template = implicit_template(site_config, entry)
    return sanitize(fill(template, placeholders(entry)))


def implicit_template(site_config: dict, entry: Entry) -> str:
    if entry.kind == "post":
        return collection_permalink(site_config, "posts") or style(site_config.get("permalink"))
    if entry.kind == "document":
        return collection_permalink(site_config, entry.collection) or COLLECTION_DEFAULT
    return page_template(site_config, entry)


def collection_permalink(site_config: dict, label: str) -> str | None:
    collections = site_config.get("collections")
    if not isinstance(collections, dict) or not isinstance(collections.get(label), dict):
        return None
    value = str(collections[label].get("permalink") or "").strip()
    return style(value) if value else None


def style(value) -> str:
    text = str(value or "").strip() or "date"
    return STYLES.get(text, text)


def default_permalink(site_config: dict, entry: Entry):
    """Jekyll's front-matter defaults: every scope whose path prefixes the file and whose type matches it; the
    longest path wins, a later entry breaks a tie."""
    best = None
    for index, default in enumerate(site_config.get("defaults") or []):
        if not isinstance(default, dict) or not isinstance(default.get("values"), dict):
            continue
        if "permalink" not in default["values"]:
            continue
        scope = default.get("scope") if isinstance(default.get("scope"), dict) else {}
        scope_path = str(scope.get("path") or "").removeprefix("/").removesuffix("/")
        source = entry.source_relative
        if scope_path and source != scope_path and not source.startswith(scope_path + "/"):
            continue
        kind = str(scope.get("type") or "")
        if kind and kind != type_of(entry):
            continue
        rank = (len(scope_path), 1 if kind else 0, index)
        if best is None or rank >= best[0]:
            best = (rank, default["values"]["permalink"])
    return best[1] if best else None


def type_of(entry: Entry) -> str:
    return {"post": "posts", "document": entry.collection}.get(entry.kind, "pages")


def page_template(site_config: dict, entry: Entry) -> str:
    if splitext(basename(entry.source_relative))[0] == "index":
        return "/:path/"
    permalink = style(site_config.get("permalink"))
    pretty = str(site_config.get("permalink") or "").strip() == "pretty" or permalink.endswith("/")
    return "/:path/:basename" + ("/" if pretty else ":output_ext")


def placeholders(entry: Entry) -> dict:
    source = entry.source_relative
    base, ext = splitext(basename(source))
    slug_source = entry.data.get("slug") if isinstance(entry.data.get("slug"), str) else filename_slug(base, entry.kind)
    values = {
        "collection": None if entry.kind == "page" else ("posts" if entry.kind == "post" else entry.collection),
        "path": page_dir(source) if entry.kind == "page" else cleaned_relative_path(entry, source, ext),
        "basename": base,
        "name": slugify(base),
        "title": slugify(slug_source, mode="pretty", cased=True),
        "slug": slugify(slug_source),
        "categories": categories(entry),
        "output_ext": ".html",
    }
    year, month, day = calendar(entry)
    if year:
        stamp = datetime(year, month, day)
        values.update(
            year=f"{year:04d}",
            month=f"{month:02d}",
            day=f"{day:02d}",
            i_month=str(month),
            i_day=str(day),
            short_year=stamp.strftime("%y"),
            y_day=stamp.strftime("%j"),
        )
    return values


def calendar(entry: Entry):
    match = re.match(r"(\d{4})-(\d{1,2})-(\d{1,2})", entry.date_raw or "")
    if match:
        return int(match.group(1)), int(match.group(2)), int(match.group(3))
    if entry.date:
        return entry.date.year, entry.date.month, entry.date.day
    return None, None, None


def filename_slug(base: str, kind: str) -> str:
    return DATED.sub("", base, count=1) if kind == "post" else base


def cleaned_relative_path(entry: Entry, source: str, ext: str) -> str:
    """`Document#cleaned_relative_path`: the path under the collection's directory, without the extension."""
    marker = f"_{'posts' if entry.kind == 'post' else entry.collection}/"
    at = source.find(marker)
    tail = source[at + len(marker) :] if at >= 0 else basename(source)
    return "/" + re.sub(r"\.*\Z", "", tail.removesuffix(ext))


def page_dir(source: str) -> str:
    folder = dirname(source)
    return "" if folder in ("", ".") else folder


def categories(entry: Entry) -> str:
    value = entry.data.get("categories") or entry.data.get("category")
    items = _flatten(value if isinstance(value, list) else [] if value is None else [value])
    return "/".join(dict.fromkeys(str(c).lower() for c in items))


def _flatten(items):
    for item in items:
        if isinstance(item, list):
            yield from _flatten(item)
        else:
            yield item


def slugify(text, mode: str = "default", cased: bool = False) -> str | None:
    """Jekyll's slugify: runs of anything but marks, letters and decimal digits (and, `pretty`, `._~!$&'()+,;=@`)
    become one hyphen; a hyphen at either end is dropped."""
    if text is None:
        return None

    def kept(char):
        return (
            unicodedata.category(char)[0] in "ML"
            or unicodedata.category(char) == "Nd"
            or (mode == "pretty" and char in PRETTY_KEEP)
        )

    out, run = [], False
    for char in str(text):
        if kept(char):
            out.append(char)
            run = False
        elif not run:
            out.append("-")
            run = True
    slug = re.sub(r"^-|-$", "", "".join(out), flags=re.M)
    return slug if cased else slug.lower()


def fill(template: str, values: dict) -> str:
    def replace(match):
        key = match.group(1)
        lead = "/" if match.group(0).startswith("/") else ""
        if key not in values:
            return match.group(0)
        value = values[key]
        if value is None:
            return ""
        encoded = SAFE_PATH.sub(lambda c: "".join(f"%{b:02X}" for b in c.group(0).encode()), str(value))
        return lead + encoded

    return TOKEN.sub(replace, template)


def sanitize(path: str) -> str:
    return re.sub(r"/{2,}", "/", ("/" + path).replace("..", "/").replace("./", ""))
