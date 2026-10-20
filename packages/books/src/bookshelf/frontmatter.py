"""Read and write the YAML front matter that heads every book and chapter file.

PyYAML is used when it is importable. When it is not, a deliberately small
parser handles the subset of YAML the schema allows (see ``docs/SCHEMA.md``):
scalars, inline ``[a, b]`` lists and block ``- item`` lists, one level deep.
Anything outside that subset raises :class:`FrontMatterError` with a line
number rather than being silently misread.

Keeping the fallback means an author can run ``books validate`` in a bare
checkout with no virtualenv, which is the common case for a prose repository.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

try:  # pragma: no cover - exercised by whichever branch the environment takes
    import yaml as _pyyaml
except ImportError:  # pragma: no cover
    _pyyaml = None

FENCE = "---"
_BOOLS = {"true": True, "yes": True, "on": True, "false": False, "no": False, "off": False}
_NULLS = {"", "null", "~", "none"}
_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")
_NEEDS_QUOTE = re.compile(r"^[\s>|@`%*&!\[\]{}#-]|[:#]\s|[:\s]$|^$")


class FrontMatterError(ValueError):
    """Raised when a document's front matter cannot be parsed."""


@dataclass(frozen=True)
class Document:
    """A markdown file split into its front matter mapping and its body."""

    meta: dict[str, Any]
    body: str
    has_front_matter: bool = True


def split(text: str) -> tuple[str | None, str]:
    """Return ``(raw_front_matter, body)``; the first item is None when absent."""
    if not text.startswith(FENCE):
        return None, text
    lines = text.splitlines(keepends=True)
    if lines[0].strip() != FENCE:
        return None, text
    for index in range(1, len(lines)):
        if lines[index].strip() == FENCE:
            return "".join(lines[1:index]), "".join(lines[index + 1 :])
    raise FrontMatterError("front matter opened with '---' but was never closed")


def parse(text: str) -> Document:
    """Split *text* and parse its front matter into a mapping."""
    raw, body = split(text)
    if raw is None:
        return Document(meta={}, body=body, has_front_matter=False)
    return Document(meta=loads(raw), body=body)


def loads(raw: str) -> dict[str, Any]:
    """Parse a front matter block into a mapping."""
    if _pyyaml is not None:
        try:
            loaded = _pyyaml.safe_load(raw)
        except _pyyaml.YAMLError as exc:
            raise FrontMatterError(str(exc)) from exc
        if loaded is None:
            return {}
        if not isinstance(loaded, dict):
            raise FrontMatterError("front matter must be a mapping of keys to values")
        return loaded
    return _loads_subset(raw)


def _loads_subset(raw: str) -> dict[str, Any]:
    """Parse the documented YAML subset without PyYAML."""
    meta: dict[str, Any] = {}
    pending_key: str | None = None
    pending_list: list[Any] = []

    for lineno, line in enumerate(raw.splitlines(), start=1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue

        stripped = line.strip()
        if stripped.startswith("- "):
            if pending_key is None:
                raise FrontMatterError(f"line {lineno}: list item without a parent key")
            pending_list.append(_scalar(stripped[2:].strip()))
            continue

        if line[:1] in " \t":
            raise FrontMatterError(f"line {lineno}: nested mappings are not supported in front matter")

        if pending_key is not None:
            meta[pending_key] = pending_list
            pending_key, pending_list = None, []

        key, sep, value = line.partition(":")
        if not sep:
            raise FrontMatterError(f"line {lineno}: expected 'key: value', got {line.strip()!r}")
        key = key.strip()
        if not key:
            raise FrontMatterError(f"line {lineno}: empty key")
        value = _strip_comment(value.strip())
        if value == "":
            pending_key, pending_list = key, []
            continue
        if value[0] not in "\"'[" and ": " in value:
            # PyYAML rejects this outright. Rejecting it here too keeps the
            # fallback a strict subset, so a file cannot pass locally without
            # PyYAML and then fail in CI with it.
            raise FrontMatterError(
                f"line {lineno}: value for {key!r} contains ': ' and must be quoted"
            )
        meta[key] = _scalar(value)

    if pending_key is not None:
        meta[pending_key] = pending_list
    return meta


def _strip_comment(value: str) -> str:
    """Drop a trailing ``# comment`` when it sits outside quotes and brackets."""
    quote: str | None = None
    depth = 0
    for index, char in enumerate(value):
        if quote:
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth = max(0, depth - 1)
        elif char == "#" and depth == 0 and index and value[index - 1].isspace():
            return value[:index].rstrip()
    return value


def _scalar(token: str) -> Any:
    """Coerce a single YAML scalar or inline list."""
    token = token.strip()
    if token.startswith("[") and token.endswith("]"):
        return [_scalar(part) for part in _split_inline(token[1:-1]) if part.strip()]
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "\"'":
        return token[1:-1]
    lowered = token.lower()
    if lowered in _NULLS:
        return None
    if lowered in _BOOLS:
        return _BOOLS[lowered]
    if _INT.match(token):
        return int(token)
    if _FLOAT.match(token):
        return float(token)
    return token


def _split_inline(body: str) -> list[str]:
    """Split ``a, "b, c", d`` on commas that sit outside quotes."""
    parts: list[str] = []
    current: list[str] = []
    quote: str | None = None
    for char in body:
        if quote:
            current.append(char)
            if char == quote:
                quote = None
        elif char in "\"'":
            quote = char
            current.append(char)
        elif char == ",":
            parts.append("".join(current))
            current = []
        else:
            current.append(char)
    parts.append("".join(current))
    return parts


def dumps(meta: dict[str, Any]) -> str:
    """Render a mapping as a front matter block, without the ``---`` fences."""
    lines: list[str] = []
    for key, value in meta.items():
        if isinstance(value, (list, tuple)):
            if not value:
                lines.append(f"{key}: []")
            else:
                lines.append(f"{key}: [{', '.join(_render(item) for item in value)}]")
        else:
            lines.append(f"{key}: {_render(value)}")
    return "\n".join(lines) + "\n"


def _render(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if _NEEDS_QUOTE.search(text) or "," in text or text.lower() in _BOOLS or text.lower() in _NULLS:
        escaped = text.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return text


def render(meta: dict[str, Any], body: str) -> str:
    """Rebuild a full markdown document from *meta* and *body*.

    *body* is used verbatim, including its leading newlines, so a round trip
    through :func:`split` and :func:`render` preserves the blank line authors
    conventionally leave under the closing fence.
    """
    return f"{FENCE}\n{dumps(meta)}{FENCE}\n{body}"
