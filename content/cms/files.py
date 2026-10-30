"""The file a page exports as: its path in its site and its raw front matter.

An `ArticlePage` or a `StandardPage` is a file of its site (exporters/jekyll.py),
and a person edits that file beside the typed fields, through the studio's API
(`fields.file_path` and `fields.front_matter`, `cms.services.apply_fields`):

- **The file path** (`file_path`, stored as `legacy_path`) is where the exporter
  writes the page, relative to the site's root: a POSIX path with no empty, `.`
  or `..` part and no leading `/`, ending in `.md`, `.markdown` or `.html`, that
  no other page of the site has — on its row, in its latest revision, or as the
  file it was imported from. A dated file name (`YYYY-MM-DD-…`) agrees with the
  page's date in UTC, the day the exporter writes in its `date:`, as Jekyll's
  posts and a site's linter expect. Empty, the exporter picks a path from the
  page's type and collection.
- **The raw front matter** (`front_matter`) is every key no typed field writes —
  `excerpt`, `permalink`, `sources`, `claims` … — as a JSON object in the order
  the file is to have them. A key the exporter writes from a typed field (the
  model's `front_matter_fields`) or from the newsroom (`authors`,
  `corrections`) is refused, naming where to set it, and every value must come
  back from the exporter's YAML (importers/frontmatter.py) as it went in. The
  stored front matter keeps each typed key where its file had it and gives the
  other places to the raw keys, in order, so an imported file's layout survives.

**Moving an imported page.** A page keeps the `ImportedSource` it was read
from, and is that file only while it still is what the import made — the same
content hash, its front matter in the file's key order and the same path
(`ImportedSource.unchanged`). A new path makes it a moved page: the exporter
renders it from its fields at the new path and lists the move
(`ExportReport.moved`); it never deletes the old file, which whoever commits the
export removes. A re-import never moves the page back (a change to the old file
is a conflict) and never makes a second page from the new file (`holder_of`).
"""

import json
import math
import re
from datetime import UTC
from functools import cache
from pathlib import PurePosixPath

import yaml
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.utils.text import capfirst

from importers import frontmatter

SUFFIXES = (".md", ".markdown", ".html")
DATED = re.compile(r"^(\d{4}-\d{2}-\d{2})-")
MAX_PATH = 512  # BasePage.legacy_path's max_length
# What the exporter adds for the newsroom, on any page that has it (newsroom.services.front_matter_for).
NEWSROOM_KEYS = {
    "authors": "the story's bylines, in the Newsroom",
    "corrections": "the page's corrections log, in the Newsroom",
}


# ── raw front matter ───────────────────────────────────────────────────────


@cache
def owned_keys(model) -> dict[str, str]:
    """The front-matter keys raw front matter may not set on a `model` page,
    each with where a person sets it instead."""
    owned = {}
    for key, name in model.front_matter_fields.items():
        label = capfirst(str(model._meta.get_field(name).verbose_name))
        owned[key] = f"the {label} field (`{name}`)"
    return {**owned, **NEWSROOM_KEYS}


def raw_front_matter(page) -> dict:
    """The page's front matter without the keys a typed field writes, in order."""
    owned = owned_keys(type(page))
    return {key: value for key, value in (page.front_matter or {}).items() if key not in owned}


def set_front_matter(page, value):
    """Make `value` (a JSON object; None for none) the page's raw front matter.
    Refuses, by key (`front_matter.<key>`), a key a typed field writes and a
    value the file could not hold as it is."""
    value = {} if value is None else value
    if not isinstance(value, dict):
        raise ValidationError(
            {"front_matter": ['raw front matter is a JSON object, e.g. {"excerpt": "…", "sources": ["https://…"]}']}
        )
    owned = owned_keys(type(page))
    errors = {}
    for key, item in value.items():
        if not key.strip():
            errors["front_matter"] = ["a front-matter key is a name, not empty"]
        elif key in owned:
            errors[f"front_matter.{key}"] = [f"`{key}` is written from {owned[key]}; set it there"]
        elif (problem := _unrepresentable(key, item)) is not None:
            errors[f"front_matter.{key}"] = [problem]
    if errors:
        raise ValidationError(errors)
    page.front_matter = _merged(page.front_matter or {}, value, owned)


def _merged(stored: dict, raw: dict, owned) -> dict:
    """`stored` with its raw keys replaced by `raw`'s: a typed key keeps its
    place, each other place takes the next raw key, and the rest follow — so
    sending back what `raw_front_matter` read changes nothing, order included."""
    incoming = iter(raw.items())
    out = {}
    for key, value in stored.items():
        if key in owned:
            out[key] = value
        elif (pair := next(incoming, None)) is not None:
            out[pair[0]] = pair[1]
    out.update(incoming)
    return out


def _scalars(value):
    if isinstance(value, dict):
        for key, item in value.items():
            yield key
            yield from _scalars(item)
    elif isinstance(value, list):
        for item in value:
            yield from _scalars(item)
    else:
        yield value


def _unrepresentable(key: str, value) -> str | None:
    """Why `{key: value}` would not come back from the exporter's YAML as it
    went in, or None."""
    for item in _scalars({key: value}):
        if isinstance(item, float) and not math.isfinite(item):
            return "a number in front matter is finite"
        if isinstance(item, str):
            try:
                item.encode("utf-8")
            except UnicodeEncodeError:
                return "text in front matter is valid Unicode (no unpaired surrogates)"
    try:
        back, _ = frontmatter.split(frontmatter.join({key: value}, ""))
    except yaml.YAMLError as e:
        return f"this value is not YAML the exporter can write back: {e}".replace("\n", " ")
    if back is None or json.dumps(back) != json.dumps({key: value}):
        return "this value would not read back from YAML as it is"
    return None


# ── the file path ──────────────────────────────────────────────────────────


def set_file_path(page, value, parent=None):
    """Give the page the file path `value` (None or "" leaves the choice to
    the exporter). Refuses (`file_path`) a path that is not a page's file in a
    site, or that another page of the site already has; `parent` is the page a
    new page goes under."""
    value = "" if value is None else value
    if not isinstance(value, str):
        raise _invalid("a file path is text, e.g. pages/_posts/2026-10-28-example.md")
    if not value or value == page.legacy_path:  # the exporter's choice, or the path it has: nothing to check
        page.legacy_path = value
        return
    if (problem := _path_problem(value)) is not None:
        raise _invalid(problem)
    if holder_of(value, site_root(parent or page.get_parent()), page.pk):
        raise _invalid(f"another page of this site already has the file {value}")
    page.legacy_path = value


def _invalid(message: str) -> ValidationError:
    return ValidationError({"file_path": [message]})


def _path_problem(path: str) -> str | None:
    parts = path.split("/")
    if "\\" in path or any(part in ("", ".", "..") for part in parts):
        return "a file path is relative to the site's root: no leading /, and no empty, . or .. folder"
    if any(ord(c) < 32 or c == "\x7f" for c in path) or any(part != part.strip() for part in parts):
        return "a file path has no control characters, and no folder or name starts or ends with a space"
    if len(path) > MAX_PATH:
        return f"a file path is at most {MAX_PATH} characters"
    if parts[-1] in SUFFIXES or not parts[-1].endswith(SUFFIXES):
        return "a page's file is named <name>.md, .markdown or .html"
    return None


def date_problem(page) -> str | None:
    """Why the page's dated file name disagrees with its date, or None."""
    match = DATED.match(PurePosixPath(page.legacy_path).name) if page.legacy_path else None
    when = getattr(page, "date", None)
    if match is None or when is None:
        return None
    if timezone.is_naive(when):
        when = timezone.make_aware(when)
    day = when.astimezone(UTC).date().isoformat()
    if match.group(1) == day:
        return None
    return f"the file name is dated {match.group(1)} and the page's date is {day} (UTC); make them the same day"


def site_root(page):
    """The `SiteRootPage` a page belongs to (inclusive), or None."""
    from .models import SiteRootPage

    return SiteRootPage.objects.ancestor_of(page, inclusive=True).first() if page is not None else None


def _file_models():
    from wagtail.models import get_page_models

    from .models import BasePage

    return [model for model in get_page_models() if issubclass(model, BasePage)]


def holder_of(path: str, root, exclude=None) -> bool:
    """Whether a page of the site under `root` (every site's, without one),
    other than `exclude`, already has `path` as its file: on its row, in its
    latest revision, or as the file it was imported from."""
    from wagtail.models import Page

    from importers.models import ImportedSource

    within = root.path if root is not None else ""
    for model in _file_models():
        if model.objects.filter(path__startswith=within, legacy_path=path).exclude(pk=exclude).exists():
            return True
    in_site = Page.objects.filter(path__startswith=within).exclude(pk=exclude)
    if in_site.filter(latest_revision__content__legacy_path=path).exists():
        return True
    return root is not None and (
        ImportedSource.objects.filter(site_key=root.site_key, legacy_path=path).exclude(page_id=exclude).exists()
    )
