"""A site's content model: its `zer0.json` read the way the extension reads it.

The Front Matter content model (decision D6: the 18 field types of
schemas/zer0.schema.json, field groups, `when` clauses, content folders) is
the field contract on every surface. The extension reads it in
src/core/content/{fields,contentType,folders}.ts; this module is the
platform's Python reading of the same file, so a type resolved here, a field
counted required here and a field found empty here are the extension's
answers. The goldens in src/test/fixtures/golden/content-model/ hold the two
together: src/test/fixtures/golden/generate.py writes them from this module,
src/test/golden.test.ts asserts the TypeScript gives the same answers, and
tests/sites/test_content_model.py that this module still does.

* `jsonc_loads` reads the zer0.json dialect (comments, trailing commas), and
  `validate` checks a file against schemas/zer0.schema.json.
* `model` coerces a file as `resolveConfig` does: a field without a string
  `name` or with a type outside FIELD_TYPES is dropped, a type without a name,
  a folder without a path, a group without an id.
* `inline_field_collections` is `inlineFieldCollections` (fields.ts): each
  `fieldCollection` becomes its group's fields, nested `fields` too, never
  mutating its input, a group that contains itself expanding to nothing.
* `resolve` is `resolveContentType` (contentType.ts): the file's `type`, the
  platform's own type key (zer0.json's `platform`, read as `profileFor` reads
  it without detection: the overlay the schema names brings `fmContentType`),
  the folder that binds exactly one type (the longest folder on whole path
  segments, a wildcard folder matched segment by segment, as folders.ts
  does), the only type, the type named `default`, else DEFAULT_CONTENT_TYPE.
* `missing_fields` is `validateFields` (fields.ts): a field hidden by its
  `when` (the ten operators, JavaScript's comparisons) is not checked, a
  `fields` group is walked against its own mapping, and a blank string or
  `<failed to process>` is empty. PyYAML reads a date as a date, the
  extension as its text: a `when` compares a date by its ISO text.

It needs nothing but the standard library (jsonschema for `validate`), so the
doctor, which runs outside the platform, can use it.
"""

from __future__ import annotations

import json
import os
import posixpath
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from functools import cache
from pathlib import Path

SCHEMA = Path(__file__).resolve().parents[2] / "schemas" / "zer0.schema.json"

# schemas/zer0.schema.json definitions.fieldType, in its order (src/core/shared/types.ts FIELD_TYPES).
FIELD_TYPES = (
    "string",
    "number",
    "boolean",
    "datetime",
    "image",
    "file",
    "choice",
    "tags",
    "categories",
    "taxonomy",
    "draft",
    "list",
    "slug",
    "fields",
    "fieldCollection",
    "divider",
    "heading",
    "contentRelationship",
)
WHEN_OPERATORS = ("eq", "neq", "contains", "notContains", "startsWith", "endsWith", "gt", "gte", "lt", "lte")
PRESENTATION_TYPES = ("divider", "heading")
FAULTY_PLACEHOLDER = "<failed to process>"  # placeholders.ts: a script that failed
WORKSPACE = "[[workspace]]"
CONTENT_TYPE_FIELD = "type"
DEFAULT_TYPE_NAME = "default"
# The platform's own type key, per profile (src/core/platform/profiles/*.ts `typeKey`), and the one the
# overlay brings (src/core/platform/overlays/); every other profile has none.
PROFILE_TYPE_KEYS = {"hugo": "type"}
OVERLAY_TYPE_KEY = "fmContentType"
PLATFORM_IDS = ("jekyll", "mkdocs", "wikijs", "hugo", "docusaurus", "astro", "generic")

# contentType.ts DEFAULT_CONTENT_TYPE: the schema of a site that declares no type. It requires nothing.
DEFAULT_CONTENT_TYPE = {
    "name": DEFAULT_TYPE_NAME,
    "pageBundle": False,
    "fields": [
        {"title": "Title", "name": "title", "type": "string", "single": True},
        {"title": "Description", "name": "description", "type": "string"},
        {"title": "Publishing date", "name": "date", "type": "datetime", "default": "{{now}}", "isPublishDate": True},
        {"title": "Content preview", "name": "preview", "type": "image", "isPreviewImage": True},
        {"title": "Is in draft", "name": "draft", "type": "draft"},
        {"title": "Tags", "name": "tags", "type": "tags"},
        {"title": "Categories", "name": "categories", "type": "categories"},
    ],
}


class _Missing:
    """JavaScript's `undefined`: a key that is not there, which `null` (None) is not."""

    def __repr__(self) -> str:
        return "MISSING"


MISSING = _Missing()


# ── reading ─────────────────────────────────────────────────────────────────

# JSON with comments and trailing commas (the zer0.json dialect): comments go
# first, kept as blank space so line numbers hold, then a comma before a
# closing bracket; strings are matched whole so neither is touched inside one.
_COMMENTS = re.compile(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*.*?\*/', re.S)
_TRAILING = re.compile(r'"(?:\\.|[^"\\])*"|,(?=\s*[\]}])', re.S)


def jsonc_loads(text: str):
    text = text.removeprefix("\ufeff")
    text = _COMMENTS.sub(lambda m: m.group() if m.group().startswith('"') else re.sub(r"[^\n]", " ", m.group()), text)
    return json.loads(_TRAILING.sub(lambda m: m.group() if m.group().startswith('"') else "", text))


@cache
def _schema() -> dict:
    return json.loads(SCHEMA.read_text(encoding="utf-8"))


def validate(data: dict) -> list[str]:
    """Where `zer0.json` breaks schemas/zer0.schema.json, one sentence each."""
    import jsonschema

    validator = jsonschema.Draft7Validator(_schema())
    problems = []
    for error in sorted(validator.iter_errors(data), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        problems.append(f"zer0.json {where}: {error.message[:200]}")
    return problems


# ── the model ───────────────────────────────────────────────────────────────


@dataclass
class Model:
    root: str
    types: list = field(default_factory=list)  # fieldCollections inlined; DEFAULT_CONTENT_TYPE when none declared
    folders: list = field(default_factory=list)  # {"path": absolute POSIX path, "contentTypes": [...] | None}
    groups: list = field(default_factory=list)
    type_key: str | None = None
    validation: bool = True
    declared: int = 0  # how many content types zer0.json declares


def model(data, root) -> Model:
    """`data` (a parsed zer0.json, or None) for the site at `root`, coerced as `resolveConfig` does."""
    data = data if isinstance(data, dict) else {}
    root = Path(os.path.abspath(root)).as_posix()
    groups = [
        {"id": g["id"], "fields": _fields(g.get("fields"))}
        for g in _list(data.get("fieldGroups"))
        if isinstance(g, dict) and isinstance(g.get("id"), str)
    ]
    declared = [
        {**{k: v for k, v in t.items() if k != "fields"}, "fields": _fields(t.get("fields"))}
        for t in _list(data.get("contentTypes"))
        if isinstance(t, dict) and isinstance(t.get("name"), str)
    ]
    folders = [
        {
            "path": _absolute(root, f["path"]),
            "contentTypes": [n for n in f["contentTypes"] if isinstance(n, str)]
            if isinstance(f.get("contentTypes"), list)
            else None,
        }
        for f in _list(data.get("contentFolders"))
        if isinstance(f, dict) and isinstance(f.get("path"), str)
    ]
    validation = data.get("validation") if isinstance(data.get("validation"), dict) else {}
    types = [
        {**t, "fields": inline_field_collections(t["fields"], groups)} for t in (declared or [DEFAULT_CONTENT_TYPE])
    ]
    return Model(
        root=root,
        types=types,
        folders=folders,
        groups=groups,
        type_key=type_key(data.get("platform")),
        validation=validation.get("enabled") if isinstance(validation.get("enabled"), bool) else True,
        declared=len(declared),
    )


def _list(value) -> list:
    return value if isinstance(value, list) else []


def _fields(value) -> list:
    return [f for f in (_field(raw) for raw in _list(value)) if f is not None]


def _field(raw) -> dict | None:
    """`coerceField` (src/core/shared/config.ts), for the keys this module reads."""
    if not isinstance(raw, dict) or not isinstance(raw.get("name"), str) or raw.get("type") not in FIELD_TYPES:
        return None
    out = {"name": raw["name"], "type": raw["type"]}
    for key in ("title", "fieldGroup"):
        if isinstance(raw.get(key), str):
            out[key] = raw[key]
    if isinstance(raw.get("required"), bool):
        out["required"] = raw["required"]
    default = raw.get("default")
    if isinstance(default, (str, int, float)):  # a bool is an int
        out["default"] = default
    elif isinstance(default, list):
        out["default"] = [item for item in default if isinstance(item, str)]
    when = raw.get("when")
    if isinstance(when, dict) and isinstance(when.get("fieldRef"), str) and when.get("operator") in WHEN_OPERATORS:
        out["when"] = {"fieldRef": when["fieldRef"], "operator": when["operator"], "value": when.get("value", MISSING)}
        if isinstance(when.get("caseSensitive"), bool):
            out["when"]["caseSensitive"] = when["caseSensitive"]
    if isinstance(raw.get("fields"), list):
        out["fields"] = _fields(raw["fields"])
    return out


def _absolute(root: str, path: str) -> str:
    """`absPath` (config.ts) in POSIX: `[[workspace]]` is the root, a relative path is under it."""
    expanded = path.replace(WORKSPACE, root).replace("\\", "/")
    return posixpath.normpath(expanded if expanded.startswith("/") else posixpath.join(root, expanded))


def type_key(platform) -> str | None:
    """The platform's own type key: `profileFor` (src/core/platform/detect.ts) without detection —
    the stated platform's key, the overlay's when zer0.json names one on Jekyll, an override's last."""
    platform = platform if isinstance(platform, dict) else {}
    platform_id = platform.get("id") if platform.get("id") in PLATFORM_IDS else "auto"
    key = PROFILE_TYPE_KEYS.get(platform_id)
    if platform_id in ("auto", "jekyll") and platform.get("overlay") in _named_overlays():
        key = OVERLAY_TYPE_KEY
    overrides = platform.get("overrides") if isinstance(platform.get("overrides"), dict) else {}
    front_matter = overrides.get("frontMatter") if isinstance(overrides.get("frontMatter"), dict) else {}
    if "typeKey" in front_matter and (front_matter["typeKey"] is None or isinstance(front_matter["typeKey"], str)):
        key = front_matter["typeKey"]
    return key


def _named_overlays() -> set:
    """The overlays zer0.json can name (the schema's `platform.overlay`, less `auto` and null)."""
    overlay = _schema()["properties"]["platform"]["properties"]["overlay"]
    return {name for name in overlay.get("enum", []) if isinstance(name, str) and name != "auto"}


# ── field collections ───────────────────────────────────────────────────────


def inline_field_collections(fields: list, groups: list) -> list:
    """Each `fieldCollection` replaced by the fields of the group it names, in its
    place and the group's order; nested `fields` sets too. A collection with no
    group, an unknown group or a group that contains itself expands to nothing.
    A new list: running it twice changes nothing."""
    return _inline(fields, groups, frozenset())


def _inline(fields: list, groups: list, seen: frozenset) -> list:
    out = []
    for f in fields:
        if f.get("type") == "fieldCollection":
            group_id = f.get("fieldGroup")
            if not isinstance(group_id, str) or group_id in seen:
                continue
            group = next((g for g in groups if g.get("id") == group_id), None)
            if group is not None:
                out += _inline(_list(group.get("fields")), groups, seen | {group_id})
        elif f.get("type") == "fields":
            out.append({**f, "fields": _inline(_list(f.get("fields")), groups, seen)})
        else:
            out.append(f)
    return out


# ── which type governs a file ───────────────────────────────────────────────


def resolve(site: Model, rel: str, data) -> dict:
    """The content type of the file at `rel` (under the site's root) whose front matter is `data`."""
    data = data if isinstance(data, dict) else {}
    by_name = {}
    for t in site.types:
        by_name.setdefault(t["name"], t)
    declared = data.get(CONTENT_TYPE_FIELD)
    if isinstance(declared, str) and declared in by_name:
        return by_name[declared]
    key = site.type_key
    if key is not None and key != CONTENT_TYPE_FIELD:
        stated = data.get(key)
        if isinstance(stated, str) and stated in by_name:
            return by_name[stated]
    folder = folder_for(site.folders, posixpath.join(site.root, rel))
    bound = (folder or {}).get("contentTypes") or []
    if len(bound) == 1 and bound[0] in by_name:
        return by_name[bound[0]]
    if len(site.types) == 1:
        return site.types[0]
    return by_name.get(DEFAULT_TYPE_NAME, DEFAULT_CONTENT_TYPE)


def folder_for(folders: list, path: str) -> dict | None:
    """`folderForFile` (folders.ts): the folder whose path is the longest prefix of `path` on whole segments."""
    best, best_length = None, 0
    for folder in folders:
        length = _prefix_length(folder["path"], path)
        if length > best_length:
            best, best_length = folder, length
    return best


def _prefix_length(folder: str, path: str) -> int:
    folder = folder.rstrip("/")
    if "*" in folder or "?" in folder:
        segments, candidates = folder.split("/"), path.split("/")
        if len(candidates) <= len(segments):
            return 0
        for segment, candidate in zip(segments, candidates, strict=False):
            if segment == "**":
                return len(folder)
            if not _segment(segment).match(candidate):
                return 0
        return len(folder)
    if path == folder:
        return len(folder)
    return len(folder) if path.startswith(folder + "/") else 0


def _segment(segment: str) -> re.Pattern:
    """One path segment as an anchored pattern: `*` and `?` are the only magic."""
    parts = ("[^/]*" if ch == "*" else "[^/]" if ch == "?" else re.escape(ch) for ch in segment)
    return re.compile("".join(parts) + r"\Z")


# ── which required fields are empty ─────────────────────────────────────────


def missing_fields(site: Model, ctype: dict, data) -> list[str]:
    """Every required field of `ctype` that `data` leaves empty, depth-first in
    declaration order, as a dotted path (`seo.title`); none when the site
    switched validation off."""
    if not site.validation:
        return []
    out: list[str] = []
    _collect(ctype.get("fields") or [], data if isinstance(data, dict) else {}, (), out)
    return out


def _collect(fields: list, data: dict, parents: tuple, out: list) -> None:
    for f in fields:
        if not evaluate_when(f, data, fields):
            continue  # a field the author cannot see is one they cannot fill in
        path = (*parents, f["name"])
        value = data.get(f["name"], MISSING)
        if f["type"] == "fields" and isinstance(f.get("fields"), list):
            _collect(f["fields"], value if isinstance(value, dict) else {}, path, out)
        elif f.get("required") is True and is_empty(f, value):
            out.append(".".join(path))


# String.prototype.trim's whitespace: ECMAScript's WhiteSpace and LineTerminator.
_JS_WHITESPACE = "\t\n\v\f\r \u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


def is_empty(f: dict, value) -> bool:
    """`isEmpty` (fields.ts): a missing key, null, a blank string, `<failed to
    process>`, an empty list or mapping; `false` and `0` are values."""
    if f.get("type") in PRESENTATION_TYPES or f.get("type") == "fieldCollection":
        return True
    if value is MISSING or value is None:
        return True
    if isinstance(value, str):
        return value.strip(_JS_WHITESPACE) == "" or value == FAULTY_PLACEHOLDER
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def evaluate_when(f: dict, data: dict, siblings: list) -> bool:
    """`evaluateWhen` (fields.ts): is the field shown? A field conditioned on a
    hidden field is hidden too; a comparison of values it cannot compare shows it."""
    return _evaluate(f, data, siblings, {f["name"]})


def _evaluate(f: dict, data: dict, siblings: list, seen: set) -> bool:
    when = f.get("when")
    if when is None:
        return True
    parent = next((s for s in siblings if s.get("name") == when["fieldRef"]), None)
    if parent is not None and parent.get("when") is not None and parent["name"] not in seen:
        seen.add(parent["name"])
        if not _evaluate(parent, data, siblings, seen):
            return False
    value = _js(data.get(when["fieldRef"], MISSING))
    if value is MISSING and parent is not None and "default" in parent:
        value = parent["default"]
    if when.get("caseSensitive", True):
        return _compare(when["operator"], value, when["value"])
    return _compare(when["operator"], _lower(value), _lower(when["value"]))


def _js(value):
    """A front-matter value as the extension holds it: dates stay their text."""
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, list):
        return [_js(item) for item in value]
    return value


def _lower(value):
    if isinstance(value, str):
        return value.lower()
    if isinstance(value, list):
        return [item.lower() if isinstance(item, str) else item for item in value]
    return value


def _number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _strict_equal(left, right) -> bool:
    """JavaScript's `===` over JSON values: two lists or mappings are never the same object."""
    if left is MISSING or right is MISSING or left is None or right is None:
        return left is right
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if _number(left) and _number(right):
        return left == right
    if isinstance(left, str) and isinstance(right, str):
        return left == right
    return False


def _js_string(value) -> str:
    """JavaScript's `String(value)` over JSON values."""
    if value is MISSING:
        return "undefined"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e21:
        return str(int(value))
    if isinstance(value, list):
        return ",".join("" if item is None or item is MISSING else _js_string(item) for item in value)
    if isinstance(value, dict):
        return "[object Object]"
    return str(value)


def _compare(operator: str, left, right) -> bool:
    if operator == "eq":
        return _strict_equal(left, right)
    if operator == "neq":
        return not _strict_equal(left, right)
    if operator in ("contains", "notContains"):
        if isinstance(left, str):
            found = _js_string(right) in left
        elif isinstance(left, list):
            found = any(_strict_equal(item, right) for item in left)
        else:
            return True
        return found if operator == "contains" else not found
    if operator == "startsWith":
        return left.startswith(_js_string(right)) if isinstance(left, str) else True
    if operator == "endsWith":
        return left.endswith(_js_string(right)) if isinstance(left, str) else True
    if not (_number(left) and _number(right)):
        return True
    return {"gt": left > right, "gte": left >= right, "lt": left < right, "lte": left <= right}.get(operator, True)
