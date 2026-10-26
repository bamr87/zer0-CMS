"""Obsidian wikilinks and embeds as the HTML and Markdown a plugin-less Jekyll renders.

    [[target]]  [[target|Display]]  [[target#Anchor]]  [[target#Anchor|Display]]
    ![[image.png]] → ![](url-or-path)        ![[note]] → a link to the note

A port of zer0-pages's `obsidian/wikilinks.rb`. Resolution is the caller's: a
`resolve(target)` that returns the target's URL or None (`bridge.resolver_for`);
an unresolved target becomes a `wikilink-unresolved` span with the same label,
so a reader sees the same words either way. Code fences and inline code are
left alone (`fence_mask`).
"""

from __future__ import annotations

import posixpath
import re
from typing import Callable, Optional

from .fence_mask import apply_outside, strip

IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
LINK = re.compile(r"(!?)\[\[([^\[\]\n]+)\]\]")

Resolve = Callable[[str], Optional[str]]


def escape_html(text) -> str:
    """The four characters the Ruby bridge escaped — not the apostrophe, which html.escape would."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def slugify(text: str) -> str:
    return re.sub(r"^-+|-+$", "", re.sub(r"[^a-z0-9]+", "-", str(text).lower()))


def is_image(path: str) -> bool:
    return posixpath.splitext(path)[1].lower() in IMAGE_EXTS


def split_once(text: str, separator: str) -> tuple[str, Optional[str]]:
    """Ruby's `text.split(separator, 2)`: the part before and the part after, which is None without one."""
    head, found, tail = text.partition(separator)
    return head, (tail if found else None)


def last_segment(path: str) -> str:
    """Ruby's `path.split('/').last.to_s`, which drops trailing empty segments."""
    parts = path.split("/")
    while parts and not parts[-1]:
        parts.pop()
    return parts[-1] if parts else ""


def render_link(inner: str, embed: bool, resolve: Resolve) -> Optional[str]:
    """One wikilink's body (between the brackets) as HTML or Markdown; None to leave it as written."""
    target, display = split_once(inner, "|")
    target = strip(target)
    display = strip(display) if display is not None else None
    path, anchor = split_once(target, "#")
    path = strip(path)
    anchor = strip(anchor) if anchor is not None else None
    if not path and not anchor:
        return None
    if embed and is_image(path):
        url = resolve(path)
        src = path if url is None else url
        return f"![](<{src}>)" if " " in src else f"![]({src})"
    label = display or last_segment(path) or anchor or ""
    fragment = f"#{slugify(anchor)}" if anchor else ""
    if not path:
        return f'<a href="{escape_html(fragment)}" class="wikilink">{escape_html(label)}</a>'
    url = resolve(path)
    if url is not None:
        return f'<a href="{escape_html(url + fragment)}" class="wikilink">{escape_html(label)}</a>'
    return f'<span class="wikilink-unresolved">{escape_html(label)}</span>'


def convert_chunk(text: str, resolve: Resolve) -> str:
    return LINK.sub(lambda m: render_link(m[2], m[1] == "!", resolve) or m[0], text)


def convert(markdown: str, resolve: Resolve) -> str:
    """Every wikilink and embed outside code fences and inline code, converted."""
    return apply_outside(markdown, lambda chunk: convert_chunk(chunk, resolve))
