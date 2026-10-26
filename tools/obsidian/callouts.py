"""Obsidian and GitHub callouts as the Bootstrap alerts the zer0 theme styles.

    > [!note] Optional Title        > [!NOTE]        > [!tip]+ Folded
    > body markdown...

becomes `<div class="alert alert-info obsidian-callout obsidian-callout-note"
markdown="1">` with the title in a `<strong>` and the body as Markdown, which
kramdown still renders because of `markdown="1"`. A port of zer0-pages's
`obsidian/callouts.rb`; callouts inside code fences are left alone.
"""

from __future__ import annotations

import re

from .fence_mask import apply_outside, chomp, lines, strip

KINDS = {
    "note": "info", "info": "info", "todo": "info",
    "tip": "success", "hint": "success", "success": "success", "check": "success",
    "warning": "warning", "caution": "warning", "attention": "warning",
    "danger": "danger", "error": "danger", "bug": "danger", "failure": "danger", "important": "danger",
    "question": "info", "help": "info", "faq": "info",
    "quote": "secondary", "cite": "secondary",
    "example": "light", "abstract": "light", "summary": "light",
}  # fmt: skip
HEAD = re.compile(r" {0,3}> ?\[!([A-Za-z][A-Za-z0-9_-]*)\]([+-]?)[ \t]*(.*)")
BODY = re.compile(r" {0,3}>")
BODY_MARK = re.compile(r"^ {0,3}> ?")


def convert_chunk(text: str) -> str:
    source, out, i = lines(text), [], 0
    while i < len(source):
        m = HEAD.fullmatch(chomp(source[i]))
        if not m:
            out.append(source[i])
            i += 1
            continue
        kind = m[1].lower()
        title = strip(m[3]) or kind.capitalize()
        body = []
        i += 1
        while i < len(source) and BODY.match(source[i]):
            body.append(BODY_MARK.sub("", source[i], count=1))
            i += 1
        out.append(f'<div class="alert alert-{KINDS.get(kind, "info")} obsidian-callout obsidian-callout-{kind}" markdown="1">\n')
        out.append(f'<strong class="obsidian-callout-title">{title}</strong>\n')
        if body:
            out.append("\n")
            out.extend(body)
            if not body[-1].endswith("\n"):
                out.append("\n")
        out.append("</div>\n")
    return "".join(out)


def convert(markdown: str) -> str:
    """Every callout outside code fences, converted (a callout's head is a line start, so inline code is not masked)."""
    return apply_outside(markdown, convert_chunk, mask_inline=False)
