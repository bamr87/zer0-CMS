"""The subset of the Dataview query language zer0-pages's vault uses, evaluated to HTML.

    TABLE <col>[, <col>...] | LIST [<expr>]        col  := expr [AS label]   label := ident | "quoted"
    FROM "folder" [OR "folder"...]  |  FROM "" AND -"excluded" [AND -"..."]
    WHERE clause [AND clause...]                    clause := expr [=|!= expr] | expr (truthy)
    FLATTEN expr AS alias   (repeatable)            GROUP BY expr [AS alias]
    SORT key [ASC|DESC][, key ...]                  LIMIT n

    expr := field.path | "literal" | number | true | false | null | fn(args...)
    fns  := length, default, choice, dateformat, regexreplace, lower, upper
    file fields := file.name, file.folder, file.link, file.path;  rows.<path> after GROUP BY

A port of zer0-pages's `obsidian/dataview.rb`, value for value: `parse` returns
None for anything outside the grammar (the caller falls back to a plain listing)
and `render(query, docs)` takes plain documents `{"title", "url", "path", "fm"}`
— `fm` being the document's data as Jekyll holds it — and returns HTML, or None
when evaluation fails. Values keep Ruby's meanings where Python's differ: only
None and False are falsy, a value prints as Ruby's `to_s` would, sort keys rank
numbers, then times, then booleans, then text, and a missing value sorts last
in either direction. Times are UTC, the zone every build of the site runs in.
"""

from __future__ import annotations

import datetime as dt
import posixpath
import re
from dataclasses import dataclass, field
from functools import cmp_to_key
from typing import Any, Optional

from .fence_mask import lines, strip
from .wikilinks import escape_html

KEYWORD = re.compile(r"(TABLE|LIST|FROM|WHERE|FLATTEN|GROUP\s+BY|SORT|LIMIT)\b", re.IGNORECASE)
SPACE = " \t\r\n\f\v"  # Ruby's \s, which is ASCII only
DATEFORMAT_TOKENS = (("yyyy", "%Y"), ("yy", "%y"), ("MM", "%m"), ("dd", "%d"), ("HH", "%H"), ("mm", "%M"), ("ss", "%S"))


@dataclass(frozen=True)
class Link:
    href: str
    text: str


@dataclass
class Query:
    mode: Optional[str] = None  # "table" or "list"
    columns: list = field(default_factory=list)  # [{"expr", "label"}]
    source: dict = field(default_factory=lambda: {"include": [""], "exclude": []})  # FROM
    where: list = field(default_factory=list)
    flatten: list = field(default_factory=list)  # [{"expr", "alias"}]
    group_by: Optional[dict] = None
    sort: list = field(default_factory=list)  # [{"expr", "dir"}]
    limit: Optional[int] = None


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class Token:
    type: str  # str, num, ident, op
    value: Any


class Tokens:
    def __init__(self, tokens: list) -> None:
        self.tokens, self.pos = tokens, 0

    def peek(self) -> Optional[Token]:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> Optional[Token]:
        token = self.peek()
        self.pos += 1
        return token

    def done(self) -> bool:
        return self.pos >= len(self.tokens)


@dataclass(frozen=True)
class Context:
    """What an expression is evaluated against: a document, with FLATTEN's bindings, or a group's rows."""

    doc: Optional[dict]
    bindings: dict = field(default_factory=dict)
    rows: Optional[list] = None

    def bind(self, name: str, value) -> Context:
        return Context(self.doc, {**self.bindings, name: value}, self.rows)


# ── parse ───────────────────────────────────────────────────────────────────


def parse(text: str) -> Optional[Query]:
    try:
        return _parse(text)
    except Exception:  # noqa: BLE001 — anything outside the grammar is "unsupported", as the Ruby rescue made it
        return None


def _parse(text: str) -> Optional[Query]:
    clauses = clause_lines(text)
    if not clauses:
        return None
    q = Query()
    for clause in clauses:
        if m := re.fullmatch(r"TABLE\s*(.*)", clause, re.IGNORECASE | re.DOTALL):
            if q.mode:
                return None
            q.mode, rest = "table", strip(m[1])
            if rest:
                columns = [parse_column(c) for c in split_top(rest, "comma")]
                if not columns or None in columns:
                    return None
                q.columns = columns
        elif m := re.fullmatch(r"LIST\s*(.*)", clause, re.IGNORECASE | re.DOTALL):
            if q.mode:
                return None
            q.mode, rest = "list", strip(m[1])
            if rest:
                column = parse_column(rest)
                if not column:
                    return None
                q.columns = [column]
        elif m := re.fullmatch(r"FROM\s+(.*)", clause, re.IGNORECASE | re.DOTALL):
            if not (source := parse_from(m[1])):
                return None
            q.source = source
        elif m := re.fullmatch(r"WHERE\s+(.*)", clause, re.IGNORECASE | re.DOTALL):
            for part in split_top(m[1], "and"):
                if not (expr := parse_full_expr(part)):
                    return None
                q.where.append(expr)
        elif m := re.fullmatch(r"FLATTEN\s+(.*)", clause, re.IGNORECASE | re.DOTALL):
            if not (flat := parse_aliased(m[1])):
                return None
            if flat["alias"] is None:  # Ruby's ||=: an empty name ("") is kept
                flat["alias"] = default_alias(flat["expr"])
            if flat["alias"] is None:
                return None
            q.flatten.append(flat)
        elif m := re.fullmatch(r"GROUP\s+BY\s+(.*)", clause, re.IGNORECASE | re.DOTALL):
            if not (group := parse_aliased(m[1])):
                return None
            q.group_by = group
        elif m := re.fullmatch(r"SORT\s+(.*)", clause, re.IGNORECASE | re.DOTALL):
            for part in split_top(m[1], "comma"):
                if not (key := parse_sort_key(part)):
                    return None
                q.sort.append(key)
        elif m := re.fullmatch(r"LIMIT\s+([0-9]+)\s*", clause, re.IGNORECASE):
            q.limit = int(m[1])
        else:
            return None
    return q if q.mode else None


def extract_from(text: str) -> Optional[dict]:
    """The FROM clause of a query that does not parse, for the caller's fallback listing."""
    for line in lines(text or ""):
        if m := re.fullmatch(r"FROM\s+(.*)", strip(line), re.IGNORECASE | re.DOTALL):
            if source := parse_from(m[1]):
                return source
    return None


def clause_lines(text: str) -> Optional[list]:
    clauses: list[str] = []
    for line in lines(text or ""):
        line = strip(line)
        if not line:
            continue
        if KEYWORD.match(line):
            clauses.append(line)
        elif not clauses:
            return None
        else:
            clauses[-1] += " " + line
    return clauses


def parse_from(rest: str) -> Optional[dict]:
    found = re.findall(r'(-?)"((?:[^"\\]|\\.)*)"', rest)
    if not found:
        return None
    include = [folder for negated, folder in found if negated != "-"]
    exclude = [folder for negated, folder in found if negated == "-"]
    return {"include": include or [""], "exclude": exclude}


def _labelled(text: str, key: str) -> Optional[dict]:
    """`expr [AS name]` — a column's label, a FLATTEN's or GROUP BY's alias."""
    try:
        tokens = Tokens(tokenize(strip(text)))
        expr = parse_expr(tokens)
        if not expr:
            return None
        name = None
        if is_keyword(tokens.peek(), "AS"):
            tokens.next()
            token = tokens.next()
            if not token or token.type not in ("ident", "str"):
                return None
            name = token.value
        return {"expr": expr, key: name} if tokens.done() else None
    except ParseError:
        return None


def parse_column(text: str) -> Optional[dict]:
    text = strip(text)
    column = _labelled(text, "label") if text else None
    if column and column["label"] is None:
        column["label"] = text
    return column


def parse_aliased(text: str) -> Optional[dict]:
    return _labelled(text, "alias")


def parse_sort_key(text: str) -> Optional[dict]:
    try:
        tokens = Tokens(tokenize(strip(text)))
        expr = parse_expr(tokens)
        if not expr:
            return None
        direction = "asc"
        if is_keyword(tokens.peek(), "ASC") or is_keyword(tokens.peek(), "DESC"):
            direction = "desc" if tokens.next().value.upper() == "DESC" else "asc"
        return {"expr": expr, "dir": direction} if tokens.done() else None
    except ParseError:
        return None


def parse_full_expr(text: str) -> Optional[tuple]:
    try:
        tokens = Tokens(tokenize(strip(text)))
        expr = parse_expr(tokens)
        return expr if expr and tokens.done() else None
    except ParseError:
        return None


def default_alias(expr: tuple) -> Optional[str]:
    return expr[1][-1] if expr[0] == "field" else None


def is_keyword(token: Optional[Token], word: str) -> bool:
    return bool(token) and token.type == "ident" and token.value.upper() == word


def _is_op(token: Optional[Token], op: str) -> bool:
    return bool(token) and token.type == "op" and token.value == op


def parse_expr(tokens: Tokens) -> Optional[tuple]:
    left = parse_primary(tokens)
    if not left:
        return None
    if _is_op(tokens.peek(), "=") or _is_op(tokens.peek(), "!="):
        op = tokens.next().value
        right = parse_primary(tokens)
        return ("cmp", op, left, right) if right else None
    return left


def parse_primary(tokens: Tokens) -> Optional[tuple]:
    token = tokens.next()
    if not token:
        return None
    if token.type in ("str", "num"):
        return ("lit", token.value)
    if token.type != "ident":
        return None
    word = token.value
    if word.lower() in ("true", "false", "null"):
        return ("lit", {"true": True, "false": False, "null": None}[word.lower()])
    if not _is_op(tokens.peek(), "("):
        return ("field", word.split("."))
    tokens.next()
    args = []
    if not _is_op(tokens.peek(), ")"):
        while True:
            arg = parse_expr(tokens)
            if not arg:
                return None
            args.append(arg)
            if not _is_op(tokens.peek(), ","):
                break
            tokens.next()
    if not _is_op(tokens.peek(), ")"):
        return None
    tokens.next()
    return ("call", word.lower(), args)


def tokenize(text: str) -> list:
    tokens, i = [], 0
    while i < len(text):
        ch = text[i]
        if ch in SPACE:
            i += 1
        elif ch == '"':
            j, buf = i + 1, []
            while j < len(text) and text[j] != '"':
                if text[j] == "\\" and j + 1 < len(text):
                    buf.append(text[j + 1])
                    j += 2
                else:
                    buf.append(text[j])
                    j += 1
            if j >= len(text):
                raise ParseError("unterminated string")
            tokens.append(Token("str", "".join(buf)))
            i = j + 1
        elif text.startswith("!=", i):
            tokens.append(Token("op", "!="))
            i += 2
        elif ch in "=(),":
            tokens.append(Token("op", ch))
            i += 1
        elif re.match(r"[A-Za-z_]", ch):
            j = i
            while j < len(text) and re.match(r"[A-Za-z0-9_\-.]", text[j]):
                j += 1
            tokens.append(Token("ident", text[i:j]))
            i = j
        elif ch.isascii() and ch.isdigit():
            j = i
            while j < len(text) and (text[j] == "." or (text[j].isascii() and text[j].isdigit())):
                j += 1
            number = text[i:j]
            tokens.append(Token("num", _to_f(number) if "." in number else int(number)))
            i = j
        else:
            raise ParseError(f"unexpected character {ch!r}")
    return tokens


def _to_f(number: str) -> float:
    """Ruby's `to_f`: the longest number at the start ("1.2.3" is 1.2), never an error."""
    m = re.match(r"[0-9]+(?:\.[0-9]+)?", number)
    return float(m[0]) if m else 0.0


def split_top(text: str, mode: str) -> list:
    """`text` split at top-level commas ("comma") or AND keywords ("and"), outside parentheses and quotes."""
    parts, buf, depth, i = [], [], 0, 0
    while i < len(text):
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < len(text) and not (text[j] == '"' and text[j - 1] != "\\"):
                j += 1
            stop = j if j < len(text) else len(text) - 1
            buf.append(text[i : stop + 1])
            i = stop + 1
            continue
        depth += {"(": 1, ")": -1}.get(ch, 0)
        if depth == 0:
            if mode == "comma" and ch == ",":
                parts.append("".join(buf))
                buf, i = [], i + 1
                continue
            if (
                mode == "and"
                and text[i : i + 3].upper() == "AND"
                and (i == 0 or text[i - 1] in SPACE)
                and (i + 3 >= len(text) or text[i + 3] in SPACE)
            ):
                parts.append("".join(buf))
                buf, i = [], i + 3
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [strip(p) for p in parts if strip(p)]


# ── render ──────────────────────────────────────────────────────────────────


def render(query: Query, docs: list) -> Optional[str]:
    """The query's HTML over `docs`, or None when evaluating it fails (the caller falls back)."""
    try:
        rows = [Context(doc) for doc in docs]
        for flat in query.flatten:
            flattened = []
            for row in rows:
                value = evaluate(flat["expr"], row)
                if isinstance(value, list):
                    flattened += [row.bind(flat["alias"], item) for item in value] or [row.bind(flat["alias"], None)]
                else:
                    flattened.append(row.bind(flat["alias"], value))
            rows = flattened
        rows = [row for row in rows if all(truthy(evaluate(w, row)) for w in query.where)]
        if query.group_by:
            return render_grouped(query, rows)
        rows = apply_sort(rows, query.sort)
        if query.limit is not None:
            rows = rows[: query.limit]
        return render_table(query, rows, None) if query.mode == "table" else render_list(query, rows, None)
    except Exception:  # noqa: BLE001 — a failed evaluation falls back to a listing, as the Ruby rescue made it
        return None


def render_grouped(query: Query, rows: list) -> str:
    alias = query.group_by["alias"]
    if alias is None:  # Ruby's ||: an empty name ("") is kept
        alias = default_alias(query.group_by["expr"])
    groups: list[tuple[Any, list]] = []
    for row in rows:
        key = evaluate(query.group_by["expr"], row)
        for existing, members in groups:
            if same_key(existing, key):
                members.append(row)
                break
        else:
            groups.append((key, [row]))
    contexts = [Context(None, {"key": key, **({alias: key} if alias is not None else {})}, m) for key, m in groups]
    if query.sort:
        contexts = apply_sort(contexts, query.sort)
    else:
        contexts = sorted(contexts, key=cmp_to_key(lambda a, b: compare(a.bindings["key"], b.bindings["key"], "asc")))
    if query.limit is not None:
        contexts = contexts[: query.limit]
    header = to_s(alias) if alias is not None else "Group"
    return render_table(query, contexts, header) if query.mode == "table" else render_list(query, contexts, header)


def render_table(query: Query, contexts: list, group_header: Optional[str]) -> str:
    heads = ["File" if group_header is None else group_header, *(c["label"] for c in query.columns)]
    html = ['<div class="obsidian-dataview table-responsive">\n', '<table class="table dataview-table">\n<thead>\n<tr>']
    html += [f"<th>{escape_html(to_s(h))}</th>" for h in heads]
    html.append("</tr>\n</thead>\n<tbody>\n")
    for context in contexts:
        grouped = group_header is not None
        first = render_group_key(context.bindings["key"]) if grouped else render_value(file_link(context))
        html.append(f"<tr><td>{first}</td>")
        html += [f"<td>{render_value(evaluate(c['expr'], context))}</td>" for c in query.columns]
        html.append("</tr>\n")
    html.append("</tbody>\n</table>\n</div>\n")
    return "".join(html)


def render_list(query: Query, contexts: list, group_header: Optional[str]) -> str:
    column = query.columns[0] if query.columns else None
    html = ['<ul class="obsidian-dataview dataview-list">\n']
    for context in contexts:
        if group_header is not None:
            html.append(f"<li><strong>{render_group_key(context.bindings['key'])}</strong>\n<ul>\n")
            items = evaluate(column["expr"], context) if column else [file_link(r) for r in context.rows]
            items = items if isinstance(items, list) else [items]
            html += [f"<li>{render_value(item)}</li>\n" for item in items]
            html.append("</ul>\n</li>\n")
        else:
            value = evaluate(column["expr"], context) if column else file_link(context)
            html.append(f"<li>{render_value(value)}</li>\n")
    html.append("</ul>\n")
    return "".join(html)


def render_group_key(key) -> str:
    return "&#8212;" if key is None or not strip(to_s(key)) else render_value(key)


def render_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, Link):
        return f'<a href="{escape_html(value.href)}">{escape_html(value.text)}</a>'
    if isinstance(value, list):
        if value and all(isinstance(item, Link) for item in value):
            return '<ul class="dataview-cell-list">' + "".join(f"<li>{render_value(i)}</li>" for i in value) + "</ul>"
        return ", ".join(render_value(item) for item in value)
    if isinstance(value, dt.date):  # a datetime too
        return escape_html(value.strftime("%Y-%m-%d"))
    return escape_html(to_s(value))


# ── values ──────────────────────────────────────────────────────────────────


def to_s(value) -> str:
    """Ruby's `to_s` for the values front matter holds."""
    if value is None:
        return ""
    if value is True or value is False:
        return "true" if value else "false"
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, list):
        return "[" + ", ".join(inspect(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{inspect(k)}=>{inspect(v)}" for k, v in value.items()) + "}"
    if isinstance(value, dt.datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S %z")
    return str(value)


def inspect(value) -> str:
    if value is None:
        return "nil"
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return to_s(value)


def truthy(value) -> bool:
    return value is not None and value is not False


def same_key(a, b) -> bool:
    """Ruby's Hash key equality (`eql?`): 1 and 1.0 are different keys, True and 1 too."""
    return type(a) is type(b) and a == b


def evaluate(node: tuple, context: Context):
    kind = node[0]
    if kind == "lit":
        return node[1]
    if kind == "field":
        return field_value(node[1], context)
    if kind == "cmp":
        equal = values_equal(evaluate(node[2], context), evaluate(node[3], context))
        return equal if node[1] == "=" else not equal
    return call(node[1], node[2], context)


def field_value(parts: list, context: Context):
    head, rest = parts[0], parts[1:]
    if head == "rows" and context.rows is not None:
        return context.rows if not rest else [field_value(rest, row) for row in context.rows]
    if head in context.bindings:
        return dig(context.bindings[head], rest)
    if context.doc is None:
        return None
    if head == "file":
        return file_field(rest, context.doc)
    return dig((context.doc.get("fm") or {}).get(head), rest)


def file_field(rest: list, doc: dict):
    path = str(doc.get("path") or "")
    name = rest[0] if rest else None
    if name == "name":
        return _basename(path)
    if name == "folder":
        folder = posixpath.dirname(path)
        return "" if folder in (".", "") else folder
    if name == "link":
        return link_for(doc)
    if name == "path":
        return path
    return None


def _basename(path: str) -> str:
    """Ruby's `File.basename(path, '.*')`: the last segment without its extension."""
    name = path.rstrip("/").rsplit("/", 1)[-1]
    stem, dot, _ = name.rpartition(".")
    return stem if dot and stem else name


def file_link(context: Context) -> Optional[Link]:
    return link_for(context.doc) if context.doc is not None else None


def link_for(doc: dict) -> Link:
    title = doc.get("title")
    if title is None:
        title = (doc.get("fm") or {}).get("title")
    if title is None or not to_s(title):
        title = _basename(str(doc.get("path") or ""))
    return Link(to_s(doc.get("url")), to_s(title))


def dig(value, parts: list):
    for part in parts:
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def call(name: str, args: list, context: Context):
    arg = [lambda i=i: evaluate(args[i], context) for i in range(len(args))]
    if name == "length":
        value = arg[0]() if args else None
        if value is None:
            return 0
        if isinstance(value, Link):
            return 2  # a Ruby Struct's length is its member count
        return len(value) if isinstance(value, (str, list, dict)) else 1
    if name == "default":
        value = arg[0]()
        return arg[1]() if value is None or (isinstance(value, (str, list, dict)) and not value) else value
    if name == "choice":
        return arg[1]() if truthy(arg[0]()) else arg[2]()
    if name == "dateformat":
        return dateformat(arg[0](), to_s(arg[1]()))
    if name == "regexreplace":
        value = arg[0]()
        if value is None:
            return None
        pattern, replacement = re.compile(to_s(arg[1]()), re.MULTILINE), to_s(arg[2]())
        return pattern.sub(lambda _: replacement, to_s(value))
    if name == "lower":
        return to_s(arg[0]()).lower()
    if name == "upper":
        return to_s(arg[0]()).upper()
    return None


def dateformat(value, fmt: str) -> str:
    when = to_time(value)
    if when is None:
        return ""
    for token, directive in DATEFORMAT_TOKENS:
        fmt = fmt.replace(token, directive)
    return when.strftime(fmt)


def to_time(value) -> Optional[dt.date]:
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        try:
            return dt.date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def values_equal(a, b) -> bool:
    if a is None and b is None:
        return True
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    return a == b


def apply_sort(contexts: list, keys: list) -> list:
    if not keys:
        return contexts

    def order(a: Context, b: Context) -> int:
        for key in keys:
            result = compare(evaluate(key["expr"], a), evaluate(key["expr"], b), key["dir"])
            if result:
                return result
        return 0

    return sorted(contexts, key=cmp_to_key(order))


def compare(a, b, direction: str) -> int:
    """Ruby's spaceship over sort tokens; nil sorts last in either direction."""
    if a is None and b is None:
        return 0
    if a is None:
        return 1
    if b is None:
        return -1
    ta, tb = sort_token(a), sort_token(b)
    result = (ta > tb) - (ta < tb)
    return -result if direction == "desc" else result


def sort_token(value) -> tuple:
    if isinstance(value, bool):
        return (2, 1.0 if value else 0.0, "")
    if isinstance(value, (int, float)):
        return (0, float(value), "")
    if isinstance(value, dt.datetime):
        return (1, value.timestamp(), "")
    if isinstance(value, dt.date):
        return (1, dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc).timestamp(), "")
    return (3, 0.0, to_s(value).lower())
