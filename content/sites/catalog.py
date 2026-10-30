"""Walk a Jekyll site and list what Jekyll itself would read as content — the
same files, under the same rules (PLAN G4).

The Python port of the Rails catalog (`Zer0Cms::Cms::Catalog`), whose rules are
transcribed from Jekyll 4.4's reader, not approximated:

* `source:` moves the whole tree; every path below is relative to it.
* A directory entry is skipped when it is excluded (`exclude:` plus Jekyll's
  defaults — matched by fnmatch, by *prefix*, or as a directory) and not
  `include:`d, or when it starts with `.`, `_`, `#` or `~` or ends with `~` (and
  is not `include:`d). That one rule is why `_data`, `_includes`, `_layouts`,
  `_site` and a `_templates` folder inside a collection are never content.
* A file outside a collection is a *page* when its first line is `---`; an
  `include:`d file the walk never reached is read as one too.
* `_posts` is read only inside `collections_dir` (or anywhere, when none is
  set); a post needs a `YYYY-MM-DD-slug.ext` name and no front matter. `_drafts`
  needs only an extension. A post or draft that is not valid UTF-8 is skipped.
* A declared collection (a map, or the legacy list form) lives at
  `<collections_dir>/_<name>`; `posts` and `data` are never read this way. A
  file in it is a *document* only with front matter.
* `published: false` and a future date are recorded, not hidden — the platform
  shows what the build would skip; it does not pretend it is gone.

Where it differs from Jekyll it is stricter, never looser: only content
extensions (Markdown and HTML) become entries — the rest are counted in
`skipped` — every symlink is skipped, and a `source:` or `collections_dir:`
that resolves outside the site root raises `UnsafePath`.

`tests/fixtures/jekyll-site*.expected.json` hold the lists Jekyll 4.4.1's own
reader produced for the two fixture sites (`rails/bin/jekyll-parity --json`),
and tests/sites/test_catalog.py holds this walk to them byte for byte. The
importer (importers/jekyll.py) reads a site through this module, so the
platform has one Jekyll reader. It needs PyYAML and nothing from Django, so the
doctor can run it outside the platform.
"""

from __future__ import annotations

import fnmatch
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from . import frontmatter

DEFAULT_EXCLUDES = [
    ".sass-cache",
    ".jekyll-cache",
    "gemfiles",
    "Gemfile",
    "Gemfile.lock",
    "node_modules",
    "vendor/bundle/",
    "vendor/cache/",
    "vendor/gems/",
    "vendor/ruby/",
]
DEFAULT_INCLUDES = [".htaccess"]
SPECIAL_LEADING = re.compile(r"\A[._#~]")
SPECIAL_COLLECTIONS = ("posts", "data")
DATE_FILENAME = re.compile(r"^(?>.+/)*?(\d{2,4}-\d{1,2}-\d{1,2})-([^/]*)(\.[^.]+)$")
# Jekyll's DATELESS_FILENAME_MATCHER only asks "does the path end in a dot and at
# least one non-dot?"; its nested quantifiers backtrack on a crafted name, so the
# same question is asked without them.
DATELESS_FILENAME = re.compile(r"\.[^.\n]+\Z")
CONTENT_EXTENSIONS = (".md", ".markdown", ".mkd", ".mkdn", ".mdown", ".html", ".htm")
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif")
YAML_HEADER = re.compile(rb"\A---\s*\r?\n")


class UnsafePath(Exception):
    """A path from a site's configuration or a request that resolves outside the site root."""


@dataclass
class Entry:
    path: str  # absolute
    relative: str  # to the site root (the directory holding _config.yml)
    source_relative: str  # to the source
    kind: str  # page | post | draft | document
    collection: str  # "pages" for a page, "posts" for a post or draft, else the collection
    title: str = ""
    date: datetime | None = None
    date_raw: str = ""
    lastmod: datetime | None = None
    status: str = ""
    draft: bool = False
    published: bool = True
    future: bool = False
    layout: str = ""
    permalink: str = ""
    preview: str = ""
    description: str = ""
    author: str = ""
    tags: list = field(default_factory=list)
    categories: list = field(default_factory=list)
    data: dict = field(default_factory=dict)
    front_matter: bool = False
    error: str | None = None
    error_line: int | None = None

    @property
    def live(self) -> bool:
        """Whether the build publishes it — `held_back`'s rules, read at the scan's time."""
        return not self.draft and self.published and not self.future and self.status != "draft"


@dataclass
class Result:
    config: dict
    root: Path
    source: Path
    collections_dir: str
    collections: list
    entries: list
    errors: list
    skipped: Counter

    @property
    def by_collection(self) -> dict:
        return dict(Counter(e.collection for e in self.entries))


@dataclass
class Site:
    """Everything the walk needs to know about a site, resolved once.
    `collections_dir_raw` is the configured string, kept for Jekyll's plain-prefix
    posts test; `collections_dir` is the cleaned relative path."""

    root: Path
    source: Path
    config: dict
    collections_dir: str
    collections_dir_raw: str
    excludes: list
    includes: list
    destination: Path
    collection_names: list

    def in_source(self, *parts) -> Path:
        parts = [str(p).lstrip("/") for p in parts]
        parts = [p for p in parts if p]
        return self.source.joinpath(*parts) if parts else self.source


def scan(root, now: datetime | None = None) -> Result:
    site = site_for(root)
    entries: list[Entry] = []
    errors: list[dict] = []
    skipped: Counter = Counter()
    _read_directories(site, "", entries, errors, skipped)
    _read_included_files(site, entries, errors, skipped)
    _read_collections(site, entries, errors, skipped)
    now = now or datetime.now().astimezone()
    for entry in entries:
        entry.future = bool(entry.date and entry.date > now)
    return Result(
        config=site.config,
        root=site.root,
        source=site.source,
        collections_dir=site.collections_dir,
        collections=site.collection_names,
        entries=_sort(entries),
        errors=errors,
        skipped=skipped,
    )


def site_for(root) -> Site:
    """Raises UnsafePath when `source:` or `collections_dir:` resolves outside
    the root (lexically, or through a symlink)."""
    root = Path(os.path.realpath(os.path.expanduser(str(root))))
    config = read_config(root)
    source = confine(root, root, config.get("source"), "source")
    raw_collections_dir = _text(config.get("collections_dir"))
    collections_dir = confine(root, source, raw_collections_dir, "collections_dir")
    excludes = _as_list(config.get("exclude")) + DEFAULT_EXCLUDES
    includes = list(DEFAULT_INCLUDES) if config.get("include") is None else _as_list(config.get("include"))
    destination = _text(config.get("destination")).strip() or "_site"
    return Site(
        root=root,
        source=source,
        config=config,
        collections_dir="" if collections_dir == source else collections_dir.relative_to(source).as_posix(),
        collections_dir_raw=raw_collections_dir,
        excludes=_uniq(excludes),
        includes=includes,
        destination=Path(os.path.normpath(root / destination)),
        collection_names=list(dict.fromkeys(["posts", *declared_collections(config)])),
    )


def confine(root: Path, base: Path, value, key: str) -> Path:
    text = _text(value).strip()
    if not text or text == ".":
        return base
    target = Path(os.path.normpath(base / os.path.expanduser(text)))
    resolved = _resolve(target)
    if _inside(root, target) and _inside(root, resolved):
        return resolved
    raise UnsafePath(f"{key}: {text!r} resolves outside the site root")


def _resolve(path: Path) -> Path:
    """realpath of the deepest existing ancestor, plus the rest."""
    if path.exists():
        return Path(os.path.realpath(path))
    if path.parent == path:
        return path
    return _resolve(path.parent) / path.name


def _inside(root: Path, path: Path) -> bool:
    return str(path) == str(root) or str(path).startswith(str(root).rstrip("/") + "/")


def read_config(root: Path) -> dict:
    """`_config.yml`, or {} when it is missing or does not read as a mapping."""
    path = Path(root) / "_config.yml"
    if not path.is_file():
        return {}
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=frontmatter.Loader)  # noqa: S506 — a SafeLoader
    except (yaml.YAMLError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def declared_collections(config: dict) -> list[str]:
    """Declared collections in either form — a map, or the legacy plain list —
    with Jekyll's label sanitising."""
    raw = config.get("collections")
    names = list(raw.keys()) if isinstance(raw, dict) else list(raw) if isinstance(raw, list) else []
    labels = [re.sub(r"[^a-z0-9_\-.]", "", _text(n), flags=re.I) for n in names]
    return [label for label in labels if label and label != "posts"]


# ── pages, posts and drafts (Jekyll::Reader#read_directories) ───────────────


def _read_directories(site, directory, out, errors, skipped):
    base = site.in_source(directory)
    if not base.is_dir():
        return
    names = _filter_entries(site, sorted(os.listdir(base)), directory)
    dirs, pages = [], []
    for name in names:
        path = base / name
        if path.is_symlink():
            skipped["symlinks"] += 1
        elif path.is_dir():
            dirs.append(name)
        elif _yaml_header(path):
            pages.append(name)
    if not _outside_collections_dir(site, directory):
        _read_posts(site, directory, out, errors, skipped)
    for name in dirs:
        if str(site.destination) == str(base / name):
            continue
        _read_directories(site, f"{directory}/{name}", out, errors, skipped)
    for name in pages:
        _add_page(site, f"{directory}/{name}".lstrip("/"), out, errors, skipped)


def _add_page(site, rel, out, errors, skipped):
    if not content_extension(rel):
        skipped["non_content_pages"] += 1
        return
    out.append(_build_entry(site, site.in_source(rel), rel, "page", "pages", errors))


def _read_included_files(site, out, errors, skipped):
    """Jekyll::Reader#read_included_excludes: an `include:` entry naming a file
    with front matter that the walk did not reach is still a page."""
    for entry in site.includes:
        if not isinstance(entry, str):
            continue
        path = Path(_sanitized_path(str(site.source), entry))
        if path.is_dir() or not path.is_file():
            continue
        if path.is_symlink():
            skipped["symlinks"] += 1
            continue
        if not _yaml_header(path):
            continue
        rel = os.path.relpath(path, site.source)
        if any(e.kind == "page" and e.source_relative == rel for e in out):
            continue
        _add_page(site, rel, out, errors, skipped)


def _sanitized_path(base: str, questionable: str) -> str:
    """Jekyll.sanitized_path: the questionable path is forced under base."""
    clean = "/" + questionable if questionable.startswith("~") else questionable
    clean = os.path.normpath(os.path.join("/", clean))
    if clean == base:
        return clean
    clean = re.sub(r"/+", "/", clean)
    if clean.startswith(base + "/"):
        return clean
    return _join(base, re.sub(r"\A\w:/", "/", clean))


def _outside_collections_dir(site, directory) -> bool:
    """Jekyll reads `_posts`/`_drafts` from every directory when there is no
    collections_dir, and only within it when there is one — a plain prefix test
    on a `/`-led path with the value as configured, exactly as Jekyll does it
    (so `/pagesx` counts as inside `pages`, a quirk kept so the two agree)."""
    if not site.collections_dir_raw:
        return False
    return not directory.startswith(f"/{site.collections_dir_raw}")


def _read_posts(site, directory, out, errors, skipped):
    for rel in _publishable_entries(site, directory, "_posts", skipped):
        if not DATE_FILENAME.match(rel):
            skipped["undated_posts"] += 1
            continue
        _add_post(site, f"{directory}/_posts/{rel}", "post", out, errors, skipped)
    for rel in _publishable_entries(site, directory, "_drafts", skipped):
        if not DATELESS_FILENAME.search(rel):
            skipped["extensionless_drafts"] += 1
            continue
        _add_post(site, f"{directory}/_drafts/{rel}", "draft", out, errors, skipped)


def _add_post(site, rel, kind, out, errors, skipped):
    rel = rel.lstrip("/")
    full = site.in_source(rel)
    if not content_extension(rel):
        skipped["non_content_posts"] += 1
        return
    try:
        full.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        skipped["invalid_utf8_posts"] += 1
        return
    out.append(_build_entry(site, full, rel, kind, "posts", errors))


def _publishable_entries(site, directory, magic_dir, skipped) -> list[str]:
    """Jekyll::Reader#get_entries — every file under <dir>/<magic_dir> (a glob
    without dot-matching), filtered with the magic dir as the base."""
    base = site.in_source(directory, magic_dir)
    if not base.exists():
        return []
    if base.is_symlink():
        skipped["symlinks"] += 1
        return []
    kept = []
    for rel in sorted(_filter_entries(site, _glob(base, dotmatch=False), f"{directory}/{magic_dir}")):
        path = base / rel
        if path.is_symlink():
            skipped["symlinks"] += 1
        elif not path.is_dir():
            kept.append(rel)
    return kept


# ── declared collections (Jekyll::Collection#read) ──────────────────────────


def _read_collections(site, out, errors, skipped):
    for label in site.collection_names:
        if label in SPECIAL_COLLECTIONS:
            continue
        directory = collection_directory(site, label)
        if not directory.is_dir():
            continue
        if directory.is_symlink():
            skipped["symlinks"] += 1
            continue
        # Jekyll filters these with base "_<label>" — relative to the source,
        # NOT to collections_dir. Mirrored, quirk included.
        for rel in sorted(_filter_entries(site, _glob(directory, dotmatch=True), f"_{label}")):
            full = directory / rel
            if full.is_symlink():
                skipped["symlinks"] += 1
                continue
            if full.is_dir() or not _yaml_header(full):
                continue
            if not content_extension(rel):
                skipped["non_content_documents"] += 1
                continue
            out.append(_build_entry(site, full, full.relative_to(site.source).as_posix(), "document", label, errors))


def collection_directory(site: Site, label: str) -> Path:
    return site.in_source(site.collections_dir, f"_{label}")


def content_extension(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in CONTENT_EXTENSIONS


def _glob(base: Path, *, dotmatch: bool) -> list[str]:
    """Ruby's `Dir.glob("**/*", base:)`: every file and directory below `base`,
    relative to it, without descending into a symlinked directory; without
    `dotmatch`, nothing whose name starts with a dot, at any depth."""
    found = []
    for current, dirs, files in os.walk(base):
        prefix = os.path.relpath(current, base)
        if not dotmatch:
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files = [f for f in files if not f.startswith(".")]
        for name in dirs + files:
            found.append(name if prefix == "." else f"{prefix}/{name}")
    return found


# ── the entry filter (Jekyll::EntryFilter) ──────────────────────────────────


def _filter_entries(site, entries, base_dir) -> list[str]:
    """`entries` are paths relative to `base_dir` (itself relative to the source,
    `/`-led or empty). Returns the ones Jekyll keeps."""
    kept = []
    for entry in entries:
        if entry.endswith("."):
            continue
        included = _included(site, entry)
        if _excluded(site, entry, base_dir) and not included:
            continue
        if included or not (_special(entry) or entry.endswith("~")):
            kept.append(entry)
    return kept


def _included(site, entry) -> bool:
    return _glob_include(site, site.includes, entry) or _glob_include(site, site.includes, os.path.basename(entry))


def _excluded(site, entry, base_dir) -> bool:
    relative = _join(base_dir.lstrip("/"), entry) if base_dir else entry
    return _glob_include(site, [p for p in site.excludes if p not in site.includes], relative)


def _special(entry) -> bool:
    return bool(SPECIAL_LEADING.match(entry) or SPECIAL_LEADING.match(os.path.basename(entry)))


def _glob_include(site, patterns, entry) -> bool:
    """Jekyll::EntryFilter#glob_include?: fnmatch (no flags, so `*` crosses `/`),
    or a bare prefix match, or directory equality with a trailing slash. All
    three are Jekyll's; the prefix one is the surprising one."""
    with_source = _join(str(site.source), str(entry))
    is_dir = os.path.isdir(with_source)
    for pattern in patterns:
        if not isinstance(pattern, str):
            continue
        pattern_with_source = _join(str(site.source), pattern)
        if (
            fnmatch.fnmatchcase(with_source, pattern_with_source)
            or with_source.startswith(pattern_with_source)
            or (is_dir and pattern_with_source == with_source + "/")
        ):
            return True
    return False


def _join(left: str, right: str) -> str:
    """Ruby's File.join: one `/` between the parts, whatever each brings."""
    if not left:
        return right
    return left.rstrip("/") + "/" + right.lstrip("/")


def _yaml_header(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return bool(YAML_HEADER.match(handle.readline()))
    except OSError:
        return False


# ── one entry ───────────────────────────────────────────────────────────────


def _build_entry(site, full: Path, source_relative: str, kind: str, collection: str, errors: list) -> Entry:
    raw_bytes = full.read_bytes()
    error = line = None
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        raw = raw_bytes.decode("utf-8", errors="replace")
        error = "not valid UTF-8"
    data: dict = {}
    try:
        data = frontmatter.parse(raw, strict=True).data
    except yaml.YAMLError as e:
        error, line = f"front matter: {_problem(e)}", frontmatter.error_line(e)
    if error:
        errors.append({"path": str(full), "message": error})
    stem = os.path.splitext(os.path.basename(source_relative))[0]
    filename_date, slug = None, stem
    if kind == "post" and (match := DATE_FILENAME.match(source_relative)):
        filename_date, slug = match.group(1), match.group(2)
    when, date_raw = _resolve_date(data.get("date"), filename_date)
    lastmod, _ = _resolve_date(data.get("lastmod"), None)
    author = data.get("author")
    categories = data.get("categories")
    if categories is None or categories is False:  # Ruby's `||`: an empty list still wins
        categories = data.get("category")
    preview = _text(data.get("preview")) or _text(data.get("image"))
    return Entry(
        path=str(full),
        relative=full.relative_to(site.root).as_posix(),
        source_relative=source_relative,
        kind=kind,
        collection=collection,
        title=_title(data.get("title"), slug, kind),
        date=when,
        date_raw=date_raw,
        lastmod=lastmod,
        status=_text(data.get("status")),
        draft=_truthy(data.get("draft")) or kind == "draft",
        published=data.get("published") is not False,
        layout=_text(data.get("layout")),
        permalink=_text(data.get("permalink")),
        preview=preview,
        description=_text(data.get("description")),
        author=_text(author.get("name")) if isinstance(author, dict) else _text(author),
        tags=[_text(t) for t in _as_list(data.get("tags"))],
        categories=[_text(c) for c in _flatten(_as_list(categories))],
        data=data,
        front_matter=bool(frontmatter.BLOCK.match(raw.removeprefix(frontmatter.BOM))),
        error=error,
        error_line=line,
    )


def _problem(error: yaml.YAMLError) -> str:
    """The parser's own reason, with where it points."""
    problem = getattr(error, "problem", None) or frontmatter.first_line(error)
    line = frontmatter.error_line(error)
    return f"{problem} (line {line})" if line else str(problem)


def _title(title, slug, kind) -> str:
    if title is not None and _text(title):
        return _text(title)
    if kind in ("post", "draft"):
        return " ".join(part.capitalize() for part in re.split(r"[-_]", slug))
    return slug


def _resolve_date(value, filename_date):
    """A YAML date or time is used as it is; a string is parsed the way Jekyll's
    `Utils.parse_date` would; anything else (a Liquid placeholder read as a
    mapping, a number) is not a date and sorts last. The filename's date is the
    fallback for posts only."""
    candidate = filename_date if value is None else value
    raw = _text(candidate)
    if candidate is None:
        return None, raw
    if isinstance(candidate, datetime):
        parsed = candidate
    elif isinstance(candidate, date):
        parsed = datetime(candidate.year, candidate.month, candidate.day)
    elif isinstance(candidate, str) and candidate.strip():
        parsed = _parse_text_date(candidate.strip())
    else:
        parsed = None
    if parsed is not None and parsed.tzinfo is None:
        parsed = parsed.astimezone()  # a date with no zone is local time, as Ruby reads it
    return parsed, raw


TEXT_DATE = re.compile(
    r"\A(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2})(?:\.\d+)?)?\s*(Z|[+-]\d{2}:?\d{2})?)?\Z"
)


def _parse_text_date(text: str) -> datetime | None:
    match = TEXT_DATE.match(text)
    if not match:
        return None
    year, month, day, hour, minute, second, zone = match.groups()
    try:
        parsed = datetime(int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0))
    except ValueError:
        return None
    if zone:
        offset = "+00:00" if zone == "Z" else zone if ":" in zone else f"{zone[:3]}:{zone[3:]}"
        parsed = datetime.fromisoformat(parsed.isoformat() + offset)
    return parsed


def _sort(entries):
    dated = sorted((e for e in entries if e.date), key=lambda e: (-int(e.date.timestamp()), e.source_relative))
    undated = sorted((e for e in entries if not e.date), key=lambda e: e.source_relative)
    return dated + undated


def _truthy(value) -> bool:
    return value is True or _text(value) in ("true", "1")


def _text(value) -> str:
    if value is None:
        return ""
    if value is True or value is False:
        return "true" if value else "false"
    return str(value)


def _as_list(value) -> list:
    if value is None:
        return []
    return list(value) if isinstance(value, list) else [value]


def _uniq(values) -> list:
    out = []
    for value in values:
        if value not in out:
            out.append(value)
    return out


def _flatten(values) -> list:
    out = []
    for value in values:
        out.extend(_flatten(value) if isinstance(value, list) else [value])
    return out


# ── helpers the rest of the platform uses ───────────────────────────────────


def held_back(rel: str, data: dict, now: datetime) -> str | None:
    """Why the site does not build the file at `rel` (a path under the site
    root) whose front matter reads as `data` (`frontmatter.parse`), or None when
    it builds it: the rules `Entry.live` reads — a draft in `_drafts/`,
    `published: false`, `draft: true`, `status: draft`, or a date after `now`
    (the front matter's, or a post's file name's). The exporter asks this before
    it marks the file of a page that is not live, so the reader and the writer
    agree on what already keeps a file out of the build."""
    folders = rel.split("/")[:-1]
    if "_drafts" in folders:
        return "a draft in _drafts/"
    if data.get("published") is False:
        return "published: false"
    if _truthy(data.get("draft")):
        return "draft: true"
    if _text(data.get("status")) == "draft":
        return "status: draft"
    named = DATE_FILENAME.match(rel) if "_posts" in folders else None
    when, _ = _resolve_date(data.get("date"), named.group(1) if named else None)
    if when is not None and when > now:
        return "dated in the future"
    return None


def media(root) -> list[Path]:
    """Images under the source's `assets/` and `images/` trees, plus the image
    generator's `output_dir` when the site names one inside its root; newest
    first. Symlinks are skipped, like everywhere else."""
    site = site_for(root)
    dirs = ["assets", "images"]
    preview = site.config.get("preview_images")
    output_dir = _text(preview.get("output_dir")).strip() if isinstance(preview, dict) else ""
    if output_dir:
        dirs.append(output_dir)
    found: dict[str, Path] = {}
    for name in dict.fromkeys(dirs):
        try:
            base = confine(site.root, site.source, name, "preview_images.output_dir")
        except UnsafePath:
            continue
        if not base.is_dir() or base.is_symlink():
            continue
        for rel in _glob(base, dotmatch=False):
            path = base / rel
            if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file() and not path.is_symlink():
                found[str(path)] = path
    return sorted(found.values(), key=lambda p: p.stat().st_mtime, reverse=True)
