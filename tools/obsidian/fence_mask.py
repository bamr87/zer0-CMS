"""Code fences and inline code spans, so the bridge's converters never touch a code sample.

Splits Markdown into the parts inside fenced code blocks (``` or ~~~, up to
three spaces of indent), inside inline code spans (equal backtick runs), and
outside both. A port of zer0-pages's `obsidian/fence_mask.rb`, line for line:
its splits are what every page of the site was built with, so its rules — not
a CommonMark parser's — decide what is code (a fence inside a blockquote is
prose here, an unclosed fence runs to the end, an outer fence hides a nested
one). Python's `str.splitlines` and `str.strip` split and strip more than
Ruby's `each_line` and `strip`, so `lines` and `strip` below are Ruby's.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

OPEN_FENCE = re.compile(r" {0,3}(`{3,}|~{3,})(.*)")
RUBY_SPACE = " \t\n\v\f\r\0"  # what Ruby's String#strip removes


def strip(text: str) -> str:
    return text.strip(RUBY_SPACE)


def lines(text: str) -> list[str]:
    """Ruby's `each_line`: split after every "\n", keeping it; a last line without one is kept too."""
    parts = text.split("\n")
    return [part + "\n" for part in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def chomp(line: str) -> str:
    """Ruby's `chomp`: the line without one trailing "\r\n", "\n" or "\r"."""
    for ending in ("\r\n", "\n", "\r"):
        if line.endswith(ending):
            return line[: -len(ending)]
    return line


def _closes(line: str, char: str, length: int) -> bool:
    stripped = strip(line)
    return bool(stripped) and stripped[0] == char and len(stripped) >= length and stripped == char * len(stripped)


def segments(text: str) -> list[tuple[str, str]]:
    """[("outside"|"code", chunk), ...]; a code chunk is a whole fenced block, its fence lines included."""
    found: list[tuple[str, str]] = []
    outside: list[str] = []
    code: Optional[list[str]] = None
    char, length = "", 0
    for line in lines(text or ""):
        if code is not None:
            code.append(line)
            if _closes(line, char, length):
                found.append(("code", "".join(code)))
                code = None
            continue
        m = OPEN_FENCE.fullmatch(chomp(line))
        if m and not (m[1][0] == "`" and "`" in m[2]):  # a backtick fence's info string has no backtick
            if outside:
                found.append(("outside", "".join(outside)))
                outside = []
            code, char, length = [line], m[1][0], len(m[1])
        else:
            outside.append(line)
    if code is not None:
        found.append(("code", "".join(code)))
    if outside:
        found.append(("outside", "".join(outside)))
    return found


def split_inline(text: str) -> list[tuple[str, str]]:
    """A fence-free chunk as [("outside"|"code", part), ...]; a code part is a span between equal backtick runs."""
    if not text:
        return []
    runs, index = [], 0
    while (start := text.find("`", index)) != -1:
        stop = start
        while stop < len(text) and text[stop] == "`":
            stop += 1
        runs.append((start, stop - start))
        index = stop
    parts, cursor, i = [], 0, 0
    while i < len(runs):
        start, size = runs[i]
        j = i + 1
        while j < len(runs) and runs[j][1] != size:
            j += 1
        if j < len(runs):
            close = runs[j][0] + runs[j][1]
            if start > cursor:
                parts.append(("outside", text[cursor:start]))
            parts.append(("code", text[start:close]))
            cursor, i = close, j + 1
        else:
            i += 1
    if cursor < len(text):
        parts.append(("outside", text[cursor:]))
    return parts


def apply_outside(text: str, change: Callable[[str], str], mask_inline: bool = True) -> str:
    """`text` with `change` applied to every part outside fenced blocks (and inline code, unless told not to)."""
    out = []
    for kind, chunk in segments(text):
        if kind == "code":
            out.append(chunk)
        elif mask_inline:
            out.extend(part if k == "code" else change(part) for k, part in split_inline(chunk))
        else:
            out.append(change(chunk))
    return "".join(out)


def replace_fences(text: str, replace: Callable[[str, str], Optional[str]]) -> str:
    """Every fenced block replaced by `replace(info, body)`, unless that returns None.

    A fence nested inside another is never offered: the outer fence wins, which keeps a page that
    teaches the syntax intact.
    """
    out = []
    for kind, chunk in segments(text):
        if kind == "outside":
            out.append(chunk)
            continue
        block = lines(chunk)
        m = OPEN_FENCE.fullmatch(chomp(block[0]))
        closed = len(block) > 1 and _closes(block[-1], m[1][0], len(m[1]))
        body = "".join(block[1:-1] if closed else block[1:])
        replacement = replace(strip(m[2]), body)
        out.append(chunk if replacement is None else replacement)
    return "".join(out)
