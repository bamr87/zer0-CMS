"""Reading and surgically editing a Jekyll front-matter block (PLAN G4).

The Python port of the Rails catalog's `Zer0Cms::Cms::FrontMatter`, itself the
port of the extension's line surgery (src/core/content/serialize.ts
`updateFrontMatterKeys`), with the same contract:

* Only the lines a change touches are rewritten. Comments, blank lines, key
  order, quoting and every other key stay byte-identical.
* A key owns a *range* of lines — its own line plus every line its value spans
  (block sequences, nested mappings, block scalars, wrapped quoted scalars).
  Blank lines and comments after a value stay outside it.
* A new key goes in before the closing fence, after the last line with
  content. `None` deletes a key — every duplicate of it, so an earlier
  duplicate is not resurrected; `NULL` writes an explicit null.
* Scalars are quoted by YAML's rules, and a list is written in the style the
  file already uses for that key (flow `[a, b]` or a block sequence).
* Dates stay strings: a value equal to what the file already holds — including
  the raw text of a date or a number — is not a change, and a plain date given
  back as text keeps its plain spelling.
* CRLF line endings, a BOM and a `...` closing fence survive.

Key ranges come from the YAML parser's own node marks (PyYAML's composer, a
port of libyaml as Psych is), so the surgery and the parser cannot disagree
about where a value ends. Every edit is verified by reading the block back: if
it does not load to exactly the intended data, `update_keys` raises `EditError`
rather than return text Jekyll would read differently. No YAML library writes
back a file with its untouched lines byte-identical, which is why this is line
surgery over PyYAML rather than a round-trip dump.

This module needs PyYAML and nothing from Django, so the doctor can run it
outside the platform (`python -m sites.doctor`).
"""

from __future__ import annotations

import math
import re
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import yaml

# Jekyll 4.4's own detection (Jekyll::Document::YAML_FRONT_MATTER_REGEXP): the
# opening `---`, the block, and a closing `---` or `...` line.
BLOCK = re.compile(r"\A(---\s*\n.*?\n?)^((---|\.\.\.)\s*$\n?)", re.S | re.M)
BOM = "﻿"
_RUBY_SPACE = " \t\n\v\f\r\0"  # what Ruby's strip removes, so quoting matches the Rails port


class _Null:
    """`NULL` in a change set writes an explicit null; `None` deletes the key."""

    def __repr__(self):
        return "frontmatter.NULL"


NULL = _Null()


class EditError(Exception):
    """An edit that cannot be placed without guessing: an unclosed fence, a block
    that is not a YAML mapping or does not parse, or a value that would not read
    back as itself."""


class NotAMapping(yaml.YAMLError):
    """The block parsed, but to something other than a mapping (Jekyll refuses
    the same file)."""


class _FrozenKey(tuple):
    """A mapping key that is itself a collection — `date: {{date}}` is a mapping
    whose key is a mapping. Jekyll's YAML reads it; Python's dict cannot hold an
    unhashable key, so it is kept as a frozen tuple instead of failing."""


def _freeze(value):
    if isinstance(value, dict):
        return _FrozenKey((_freeze(k), _freeze(v)) for k, v in value.items())
    if isinstance(value, list):
        return _FrozenKey(_freeze(v) for v in value)
    return value


class Loader(yaml.SafeLoader):
    """YAML as Jekyll reads front matter: dates and times typed, aliases allowed,
    nothing but plain data constructed, and a collection used as a key kept."""

    def construct_mapping(self, node, deep=False):
        if isinstance(node, yaml.MappingNode):
            self.flatten_mapping(node)
        mapping = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=True)
            if not isinstance(key, Hashable):
                key = _freeze(key)
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping

    def construct_yaml_timestamp(self, node):
        """`date: 2026-13-45` looks like a date and is not one: a YAML error, as
        Jekyll's parser makes it, rather than Python's ValueError."""
        try:
            return super().construct_yaml_timestamp(node)
        except ValueError as e:
            raise yaml.constructor.ConstructorError(None, None, f"not a date: {node.value}", node.start_mark) from e


Loader.add_constructor("tag:yaml.org,2002:timestamp", Loader.construct_yaml_timestamp)


def load_data(text: str) -> dict:
    """A YAML block as a dict: an empty block is `{}`; anything but a mapping
    raises `NotAMapping`; a syntax error raises PyYAML's own error."""
    loaded = yaml.load(text, Loader=Loader)  # noqa: S506 — Loader is a SafeLoader
    if loaded is None or loaded is False:
        loaded = {}
    if not isinstance(loaded, dict):
        raise NotAMapping(f"front matter is a {type(loaded).__name__}, not a mapping")
    return loaded


def compose(text: str):
    return yaml.compose(text, Loader=Loader)  # noqa: S506 — composing builds nodes, never objects


def first_line(error: Exception) -> str:
    lines = str(error).splitlines()
    return lines[0].strip() if lines else ""


def error_line(error: yaml.YAMLError) -> int | None:
    """The 1-based line a YAML error points at, the way Psych reports it: the
    context's mark when there is one, else the problem's."""
    mark = getattr(error, "context_mark", None) or getattr(error, "problem_mark", None)
    return mark.line + 1 if mark is not None else None


@dataclass
class Document:
    """A parsed file. `raw` is the YAML between the fences (None without a
    block); `fence_style` is the closing fence (`---` or `...`); `newline` is the
    opening fence's line ending."""

    data: dict
    body: str
    raw: str | None
    fence_style: str | None
    newline: str
    bom: bool
    errors: list = field(default_factory=list)
    head: str | None = None

    @property
    def front_matter(self) -> bool:
        return self.fence_style is not None

    @property
    def raw_values(self) -> dict:
        """Each top-level key holding a scalar, as written before YAML typed it —
        so a form shows `2025-11-29T16:46:02.000Z`, not a datetime."""
        if self.head is None or self.errors:
            return {}
        try:
            root = compose(self.head)
        except yaml.YAMLError:
            return {}
        if not isinstance(root, yaml.MappingNode):
            return {}
        return {
            k.value: v.value for k, v in root.value if isinstance(k, yaml.ScalarNode) and isinstance(v, yaml.ScalarNode)
        }


def parse(text: str | None, *, strict: bool = False) -> Document:
    """Parse `text`. Lenient by default (a block that does not load leaves `data`
    empty and the reason in `errors`); `strict=True` raises the YAML error."""
    text = "" if text is None else str(text)
    bom = text.startswith(BOM)
    src = text[1:] if bom else text
    match = BLOCK.match(src)
    if not match:
        newline = "\r\n" if "\r\n" in src else "\n"
        return Document(data={}, body=src, raw=None, fence_style=None, newline=newline, bom=bom)
    head = match.group(1)
    opening_end = head.index("\n")
    newline = "\r\n" if head[:opening_end].endswith("\r") else "\n"
    errors, data = [], {}
    try:
        data = load_data(head)
    except yaml.YAMLError as e:
        if strict:
            raise
        errors.append(f"{type(e).__name__}: {first_line(e)}")
    return Document(
        data=data,
        body=src[match.end() :],
        raw=head[opening_end + 1 :],
        fence_style=match.group(3),
        newline=newline,
        bom=bom,
        errors=errors,
        head=head,
    )


def update_keys(text: str | None, changes: dict) -> str:
    """Rewrite only the keys in `changes` (`None` deletes, `NULL` writes a null)
    and return the new text — `text` itself when nothing changes. A file without
    front matter gains a block. Raises `EditError` instead of guessing."""
    text = "" if text is None else str(text)
    changes = {str(k): normalize(v) for k, v in dict(changes).items()}
    if not changes:
        return text
    bom = BOM if text.startswith(BOM) else ""
    src = text[len(bom) :]
    match = BLOCK.match(src)
    if not match:
        return bom + new_block(src, changes)
    head = match.group(1)
    opening_end = head.index("\n") + 1
    eol = "\r\n" if head[:opening_end].endswith("\r\n") else "\n"
    lines = re.findall(r"[^\n]*\n|[^\n]+\Z", head[opening_end:])
    edited = _Surgery(lines, eol).apply(changes)
    if edited is None:
        return text
    return bom + head[:opening_end] + "".join(edited) + match.group(2) + src[match.end() :]


def new_block(src: str, changes: dict) -> str:
    """Front matter for a file that has none: keys in the order given, with the
    text's own line ending."""
    if re.match(r"---[ \t]*\r?\n", src):
        raise EditError("the file opens with an unclosed `---` fence")
    sets = {k: v for k, v in changes.items() if v is not None}
    if not sets:
        return src
    eol = "\r\n" if "\r\n" in src else "\n"
    edited = _Surgery([], eol).apply(sets) or []
    return f"---{eol}{''.join(edited)}---{eol}{src}"


def dump(data: dict, eol: str = "\n") -> str:
    """A whole block for `data`, fences included (a new file's front matter)."""
    out = new_block("", {str(k): normalize(v) for k, v in data.items()})
    return out if eol == "\n" else out.replace("\n", eol)


def normalize(value):
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) and not isinstance(value, _FrozenKey):
        return [normalize(v) for v in value]
    return value


def same_value(left, right) -> bool:
    """Equality that does not let `1 == 1.0`, `True == 1` or a date equal a datetime."""
    if isinstance(left, dict):
        return (
            isinstance(right, dict)
            and len(left) == len(right)
            and all(k in right and same_value(v, right[k]) for k, v in left.items())
        )
    if isinstance(left, list):
        return isinstance(right, list) and len(left) == len(right) and all(map(same_value, left, right))
    if isinstance(left, float):
        return isinstance(right, float) and (left == right or (math.isnan(left) and math.isnan(right)))
    if isinstance(left, datetime):
        return isinstance(right, datetime) and left == right
    return type(left) is type(right) and left == right


# ── scalar rules (serialize.ts needsStructuralQuotes / needsQuotes) ─────────

LEADING_INDICATOR = re.compile(r"\A[,\[\]{}#&*!|>'\"%@`]")
INDICATOR_PAIR = re.compile(r"\A[-?:](?:[ \t\r\n\f\v]|\Z)")
UNPRINTABLE = "\x00-\x08\x0a-\x1f\x7f\x85  ﻿"
ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r", "\t": "\\t"}


def needs_structural_quotes(value: str) -> bool:
    """The text would not survive as a plain scalar at all."""
    return bool(
        value == ""
        or value != value.strip(_RUBY_SPACE)
        or LEADING_INDICATOR.match(value)
        or INDICATOR_PAIR.match(value)
        or re.search(r":(?:[ \t\r\n\f\v]|\Z)", value)
        or re.search(r"[ \t\r\n\f\v]#", value)
        or re.search("[\x00-\x1f\x7f\x85  ﻿]", value)
    )


def typed(text: str):
    """What YAML makes of `text` as a plain scalar: a str, or the date, number,
    boolean or null it resolves to."""
    loader = Loader("")
    try:
        tag = loader.resolve(yaml.ScalarNode, text, (True, False))
        return loader.construct_object(yaml.ScalarNode(tag, text))
    finally:
        loader.dispose()


def plain_ok(value: str, *, flow: bool = False) -> bool:
    """Plain is safe when the text is structurally plain and YAML would read it
    back as this very string (not true, 3, 2026-01-01, null, …)."""
    if needs_structural_quotes(value) or (flow and re.search(r"[,\[\]{}]", value)):
        return False
    try:
        resolved = typed(value)
    except yaml.YAMLError:
        return False
    return isinstance(resolved, str) and resolved == value


def double_quote(value: str) -> str:
    """A double-quoted YAML scalar: backslash first, then quotes."""
    escaped = re.sub(
        f'[\\\\"\n\r\t]|[{UNPRINTABLE}]', lambda m: ESCAPES.get(m.group(), f"\\u{ord(m.group()):04X}"), value
    )
    return f'"{escaped}"'


def single_quote(value: str) -> str | None:
    if re.search(f"[{UNPRINTABLE}]", value) or "\t" in value:
        return None
    return "'" + value.replace("'", "''") + "'"


def _quoted(node) -> bool:
    return isinstance(node, yaml.ScalarNode) and node.style in ("'", '"')


def _family(value) -> str | None:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, date):
        return "date"
    return None


# ── the line surgery ────────────────────────────────────────────────────────


@dataclass
class _Pair:
    key: str
    key_node: yaml.ScalarNode
    value: yaml.Node
    first: int
    last: int


class _Surgery:
    """One pass of edits over a block's lines (each line with its own ending)."""

    def __init__(self, lines: list[str], eol: str):
        self.lines = list(lines)
        self.eol = eol

    def apply(self, changes: dict) -> list[str] | None:
        """The edited lines, or None when nothing changed."""
        data, _, _ = self._analyze()
        expected = dict(data)
        changed = False
        for key, value in changes.items():
            data, pairs, root = self._analyze()
            matches = [p for p in pairs if p.key == key]
            delete = value is None
            if value is NULL:
                value = None
            if delete:
                if not matches:
                    continue
                self._guard_line_breaks()
                for pair in reversed(matches):
                    del self.lines[pair.first : pair.last + 1]
                expected.pop(key, None)
            elif matches:
                pair = matches[-1]
                if self._unchanged(pair.value, data.get(key), value):
                    continue
                self._guard_line_breaks()
                replacement, read = self._emit_existing(pair, value, root, pairs)
                self.lines[pair.first : pair.last + 1] = [line + self.eol for line in replacement]
                expected[key] = read
            else:
                self._guard_line_breaks()
                added, read = self._emit_new(key, value, root, pairs)
                at = self._insertion_point(pairs)
                self.lines[at:at] = [line + self.eol for line in added]
                expected[key] = read
            changed = True
        if not changed:
            return None
        self._verify(expected)
        return self.lines

    def _yaml(self) -> str:
        return "".join(self.lines)

    def _analyze(self):
        text = self._yaml()
        try:
            data = load_data(text)
            root = compose(text)
        except yaml.YAMLError as e:
            raise EditError(f"front matter does not parse: {first_line(e)}") from e
        if root is None:
            return data, [], None
        if not isinstance(root, yaml.MappingNode) or root.flow_style is True:
            raise EditError("front matter is not a block mapping")
        pairs = [
            _Pair(key.value, key, value, key.start_mark.line, self._last_line(key, value))
            for key, value in root.value
            if isinstance(key, yaml.ScalarNode)
        ]
        return data, pairs, root

    def _last_line(self, key, value) -> int:
        """A block value's end mark is the start of the line after it; the range
        then gives back trailing blank lines and comments that sit no deeper than
        the key, so they stay between keys."""
        last = value.end_mark.line
        if value.end_mark.column == 0 and last > key.start_mark.line:
            last -= 1
        last = min(last, len(self.lines) - 1)
        while last > key.start_mark.line:
            content = self.lines[last].removesuffix("\n").removesuffix("\r")
            stripped = content.lstrip(_RUBY_SPACE)
            comment = stripped.startswith("#") and len(content) - len(stripped) <= key.start_mark.column
            if stripped and not comment:
                break
            last -= 1
        return last

    def _guard_line_breaks(self):
        """Line numbers come from the parser, which also breaks lines at a bare
        CR, NEL, LS and PS; these lines split at LF only. Refuse rather than
        rewrite the wrong line."""
        if re.search("\r(?!\n)|[\x85  ]", self._yaml()):
            raise EditError("front matter contains a bare CR or a Unicode line separator")

    def _insertion_point(self, pairs) -> int:
        content = [i for i, line in enumerate(self.lines) if line.strip(_RUBY_SPACE)]
        at = content[-1] + 1 if content else 0
        tail = pairs[-1] if pairs else None
        if tail and isinstance(tail.value, yaml.ScalarNode) and self._keeps_trailing_lines(tail):
            at = len(self.lines)
        return at

    def _keeps_trailing_lines(self, pair) -> bool:
        return bool(re.search(r":\s*[|>][0-9]*\+", self.lines[pair.key_node.start_mark.line]))

    @staticmethod
    def _unchanged(node, current, value) -> bool:
        if same_value(current, value):
            return True
        return (
            isinstance(node, yaml.ScalarNode)
            and isinstance(value, str)
            and node.value == value
            and not isinstance(current, str)
        )

    # ── emission ──

    def _emit_existing(self, pair, value, root, pairs):
        indent = pair.key_node.start_mark.column
        token = self._key_token(pair.key_node)
        if self._typed_plain(pair.value, value):
            return [f"{' ' * indent}{token}: {value}"], typed(value)
        return self._emit_verified(token, value, indent, self._hints_for(pair.value, root, pairs, indent))

    def _emit_new(self, key, value, root, pairs):
        indent = pairs[0].key_node.start_mark.column if pairs else 0
        token = key if plain_ok(key) else double_quote(key)
        return self._emit_verified(token, value, indent, self._hints_for(None, root, pairs, indent))

    @staticmethod
    def _typed_plain(node, value) -> bool:
        """A plain scalar that YAML typed (a date, a number, a boolean) given back
        as text of the same type keeps its plain spelling: the file said
        `date: 2026-01-01`, the form sends "2026-02-01", the file keeps a date."""
        if not (isinstance(node, yaml.ScalarNode) and node.style is None and isinstance(value, str)):
            return False
        if "\n" in value or needs_structural_quotes(value):
            return False
        try:
            current, read = _family(typed(node.value)), _family(typed(value))
        except yaml.YAMLError:
            return False
        return current is not None and current == read

    def _emit_verified(self, token, value, indent, hints):
        attempts = [hints]
        if isinstance(value, str) and "\n" in value:
            attempts.append({**hints, "block_scalars": False})
        for attempt in attempts:
            lines = _Emitter(attempt).key_lines(token, value, indent)
            if self._reads_back(lines, indent, value):
                return lines, value
        raise EditError(f"could not write {token} so that it reads back unchanged")

    @staticmethod
    def _reads_back(lines, indent, value) -> bool:
        text = "\n".join(line[indent:] for line in lines) + "\n"
        try:
            loaded = load_data(text)
        except (yaml.YAMLError, EditError):
            return False
        return len(loaded) == 1 and same_value(next(iter(loaded.values())), value)

    @staticmethod
    def _key_token(node) -> str:
        if node.style == "'":
            return single_quote(node.value) or double_quote(node.value)
        if node.style == '"':
            return double_quote(node.value)
        return node.value if plain_ok(node.value) else double_quote(node.value)

    def _hints_for(self, node, root, pairs, indent) -> dict:
        """How this file writes things: the key's own style first, then the
        file's habit (the first list, the most common quote), then defaults."""
        hints = {"quote": self._file_quote(root), "list": "block", "list_indent": 2, "map_indent": 2}
        hints["block_scalars"] = True
        sample = next((p.value for p in pairs if isinstance(p.value, yaml.SequenceNode)), None)
        if sample is not None:
            self._sequence_hints(hints, sample, indent)
        sample_map = next((p.value for p in pairs if isinstance(p.value, yaml.MappingNode) and p.value.value), None)
        if sample_map is not None:
            hints["map_indent"] = sample_map.value[0][0].start_mark.column - indent
        if isinstance(node, yaml.SequenceNode):
            self._sequence_hints(hints, node, indent, own=True)
        elif isinstance(node, yaml.MappingNode):
            if node.value:
                hints["map_indent"] = node.value[0][0].start_mark.column - indent
        elif isinstance(node, yaml.ScalarNode):
            if node.style == "'":
                hints["quote"] = "single"
            elif node.style == '"':
                hints["quote"] = "double"
            hints["scalar"] = "quoted" if _quoted(node) else "plain"
        if hints["map_indent"] <= 0:
            hints["map_indent"] = 2
        return hints

    def _sequence_hints(self, hints, node, indent, own=False):
        if node.flow_style is True:
            hints["list"] = "flow"
        else:
            hints["list"] = "block"
            if node.value:
                line = self.lines[node.value[0].start_mark.line]
                hints["list_indent"] = max(len(line) - len(line.lstrip(" ")) - indent, 0)
        quoted = next((c for c in node.value if _quoted(c)), None)
        if quoted is not None and own:
            hints["item_quote"] = "single" if quoted.style == "'" else "double"

    @staticmethod
    def _file_quote(root) -> str:
        counts = {"'": 0, '"': 0}
        stack = [root] if root is not None else []
        while stack:
            node = stack.pop()
            if isinstance(node, yaml.ScalarNode):
                if node.style in counts:
                    counts[node.style] += 1
            elif isinstance(node, yaml.MappingNode):
                stack.extend(n for pair in node.value for n in pair)
            elif isinstance(node, yaml.SequenceNode):
                stack.extend(node.value)
        return "single" if counts["'"] > counts['"'] else "double"

    def _verify(self, expected):
        try:
            actual = load_data(self._yaml())
        except yaml.YAMLError as e:
            raise EditError(f"the edited front matter does not parse: {first_line(e)}") from e
        if not same_value(actual, expected):
            raise EditError("the edited front matter would not read back as intended")


class _Emitter:
    """`key: value` and everything under it as lines (no line endings), with the
    file's hints."""

    def __init__(self, hints: dict):
        self.hints = hints

    def key_lines(self, token: str, value, indent: int) -> list[str]:
        label = f"{' ' * indent}{token}:"
        if value is None:
            return [label]
        if isinstance(value, list):
            return self._list_lines(label, value, indent)
        if isinstance(value, dict):
            return self._map_lines(label, value, indent)
        if isinstance(value, str):
            if "\n" in value and self.hints["block_scalars"]:
                header, body = _literal(value, indent + 2)
                return [f"{label} {header}", *body]
            prefer_plain = self.hints.get("scalar") != "quoted"
            return [f"{label} {self._string(value, self.hints['quote'], prefer_plain)}"]
        return [f"{label} {_scalar(value)}"]

    def _list_lines(self, label, items, indent):
        if not items:
            return [f"{label} []"]
        if self.hints["list"] == "flow" and all(map(_flow_scalar, items)):
            return [f"{label} [{', '.join(self._flow_item(i) for i in items)}]"]
        pad = indent + self.hints["list_indent"]
        return [label, *(line for item in items for line in self._sequence_item(item, pad))]

    def _map_lines(self, label, mapping, indent):
        if not mapping:
            return [f"{label} {{}}"]
        child = indent + self.hints["map_indent"]
        return [label, *(line for k, v in mapping.items() for line in self._nested(_child_key(k), v, child))]

    def _sequence_item(self, item, pad) -> list[str]:
        prefix = f"{' ' * pad}- "
        if isinstance(item, dict):
            if not item:
                return [f"{prefix}{{}}"]
            inner = [line for k, v in item.items() for line in self._nested(_child_key(k), v, pad + 2)]
            inner[0] = prefix + inner[0][pad + 2 :]
            return inner
        if isinstance(item, list):
            if not item:
                return [f"{prefix}[]"]
            if all(map(_flow_scalar, item)):
                return [f"{prefix}[{', '.join(self._flow_item(i) for i in item)}]"]
            inner = [line for sub in item for line in self._sequence_item(sub, pad + 2)]
            inner[0] = prefix + inner[0].lstrip(_RUBY_SPACE)
            return inner
        if isinstance(item, str):
            quote = self.hints.get("item_quote") or self.hints["quote"]
            return [f"{prefix}{self._string(item, quote, True, multiline=True)}"]
        return [f"{prefix}{_scalar(item)}"]

    def _nested(self, token, value, indent):
        """Children of a list item or a nested map never use block scalars —
        their indentation rules are where hand-written YAML goes wrong."""
        return _Emitter({**self.hints, "block_scalars": False, "scalar": None}).key_lines(token, value, indent)

    def _flow_item(self, item) -> str:
        if not isinstance(item, str):
            return _scalar(item)
        if plain_ok(item, flow=True):
            return item
        return _quote(item, self.hints.get("item_quote") or self.hints["quote"])

    @staticmethod
    def _string(value, quote, prefer_plain, multiline=False) -> str:
        if multiline and "\n" in value:
            return double_quote(value)
        if prefer_plain and plain_ok(value):
            return value
        return _quote(value, quote)


def _quote(value, quote) -> str:
    return (quote == "single" and single_quote(value)) or double_quote(value)


def _child_key(key) -> str:
    text = str(key)
    if isinstance(key, str) and plain_ok(text):
        return text
    if isinstance(key, int) and not isinstance(key, bool) and typed(text) == key:
        return text
    return double_quote(text)


def _flow_scalar(item) -> bool:
    return not isinstance(item, (list, dict)) and not (isinstance(item, str) and "\n" in item)


def _scalar(value) -> str:
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return _float(value)
    if isinstance(value, datetime):
        return _time(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value if plain_ok(value) else double_quote(value)
    raise EditError(f"cannot write a {type(value).__name__} as front matter")


def _float(value: float) -> str:
    """A float YAML 1.1 reads back as one: a dot in the mantissa, a signed exponent."""
    if math.isnan(value):
        return ".nan"
    if math.isinf(value):
        return ".inf" if value > 0 else "-.inf"
    mantissa, _, exponent = repr(value).partition("e")
    if "." not in mantissa:
        mantissa += ".0"
    if not exponent:
        return mantissa
    return f"{mantissa}e{exponent if exponent[0] in '+-' else '+' + exponent}"


def _time(value: datetime) -> str:
    text = value.strftime("%Y-%m-%dT%H:%M:%S")
    if value.microsecond:
        text += f".{value.microsecond:06d}".rstrip("0")
    offset = value.utcoffset()
    if offset is None:
        return text
    if offset == timedelta(0):
        return text + "Z"
    minutes = int(offset.total_seconds()) // 60
    sign = "+" if minutes >= 0 else "-"
    hours, minutes = divmod(abs(minutes), 60)
    return f"{text}{sign}{hours:02d}:{minutes:02d}"


def _literal(value: str, indent: int):
    """A literal block scalar: `|` keeps one trailing newline, `|-` none, `|+`
    several; an indentation indicator when the first line starts with a space."""
    chomp = "+" if value.endswith("\n\n") else ("" if value.endswith("\n") else "-")
    parts = value.split("\n")
    if value.endswith("\n"):
        parts.pop()
    first = next((p for p in parts if p), "")
    indicator = "2" if first.startswith(" ") else ""
    return f"|{indicator}{chomp}", ["" if not p else " " * indent + p for p in parts]
