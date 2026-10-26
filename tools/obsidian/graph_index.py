"""The `/assets/data/wiki-index.json` payload the zer0 theme's Obsidian graph view reads.

One entry per document — `{title, basename, url, collection, tags, categories,
aliases, outgoing, excerpt}`, the theme's contract — with its outgoing wikilink
targets found by the same fence-masked parser the bridge converts with, so code
samples never become edges. A port of zer0-pages's `obsidian/graph_index.rb`:
the browser resolves a target against each entry's normalized title, basename
and aliases, so each document's extension-less vault path is added to its
aliases, which is what lets this vault's path-qualified links
(`[[_docs/obsidian/graph]]`) resolve; a target nothing has stays in `outgoing`
and is drawn as a broken node, as intended.
"""

from __future__ import annotations

import datetime as dt
import json
import re
from typing import Optional

from .dataview import to_s
from .fence_mask import segments, split_inline, strip
from .wikilinks import LINK, is_image, last_segment

EXCERPT_LIMIT = 240


def strip_ext(path: str) -> str:
    return re.sub(r"\.(md|markdown)\Z", "", str(path).lstrip("/"), flags=re.IGNORECASE)


def string_list(value) -> list:
    """Ruby's `Array(value).map(&:to_s).reject(&:empty?)`, as front matter lists are read."""
    items = value if isinstance(value, list) else [value]
    return [to_s(item) for item in items if to_s(item)]


def alias_list(aliases, vault_key: str) -> list:
    """The front matter's aliases, then the document's extension-less vault path (once)."""
    found = string_list(aliases)
    if vault_key and vault_key not in found:
        found.append(vault_key)
    return found


def wikilink_target(inner: str, embed: bool) -> Optional[str]:
    """The path part of a wikilink's body — without its |alias, #anchor and ^block — or None for an image embed."""
    path = strip(inner.split("|", 1)[0].split("#", 1)[0].split("^", 1)[0])
    if not path or (embed and is_image(path)):
        return None
    return path


def outgoing_targets(markdown: str) -> list:
    """Each wikilink and note embed's target, once, in order — never from code."""
    targets: list[str] = []
    for kind, chunk in segments(markdown or ""):
        if kind == "code":
            continue
        for part_kind, part in split_inline(chunk):
            if part_kind == "outside":
                for m in LINK.finditer(part):
                    target = wikilink_target(m[2], m[1] == "!")
                    if target and target not in targets:
                        targets.append(target)
    return targets


def wikilink_label(inner: str) -> str:
    target, _, display = inner.partition("|")
    if strip(display):
        return strip(display)
    path, _, anchor = target.partition("#")
    return last_segment(strip(path)) if strip(path) else strip(anchor)


def plain_text(text: str) -> str:
    text = re.sub(r"\{%.*?%\}", " ", text, flags=re.DOTALL)  # Liquid tags
    text = re.sub(r"\{\{.*?\}\}", " ", text, flags=re.DOTALL)  # Liquid output
    text = LINK.sub(lambda m: wikilink_label(m[2]), text)  # wikilinks → their labels
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)  # images → alt text
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)  # links → their text
    text = re.sub(r"<[^>]+>", " ", text)  # HTML tags
    text = re.sub(r"^ {0,3}#{1,6}[ \t]+", "", text, flags=re.MULTILINE)  # heading markers
    text = re.sub(r"^ {0,3}>[ \t]?", "", text, flags=re.MULTILINE)  # blockquote markers
    text = re.sub(r"\[![A-Za-z0-9_]+\][+-]?", "", text)  # callout markers
    text = re.sub(r"\*+", "", text)  # emphasis
    return strip(re.sub(r"[ \t\r\n\f\v]+", " ", text))


def excerpt(markdown: str, limit: int = EXCERPT_LIMIT) -> str:
    """Plain words: no code, no markup, wikilinks as their labels, at most `limit` characters."""
    prose = " ".join(
        " " if kind == "code" else "".join(" " if k == "code" else c for k, c in split_inline(chunk))
        for kind, chunk in segments(markdown or "")
    )
    text = plain_text(prose)
    return text if len(text) <= limit else text[: limit - 1].rstrip(" \t\n\v\f\r\0") + "…"


def build_entry(doc: dict) -> dict:
    vault_key = strip_ext(doc.get("path") or "")
    base = vault_key.rsplit("/", 1)[-1]
    content = str(doc.get("content") or "")
    return {
        "title": to_s(doc["title"] if doc.get("title") is not None else base),
        "basename": base,
        "url": str(doc.get("url") or ""),
        "collection": doc.get("collection"),
        "tags": string_list(doc.get("tags")),
        "categories": string_list(doc.get("categories")),
        "aliases": alias_list(doc.get("aliases"), vault_key),
        "outgoing": outgoing_targets(content),
        "excerpt": excerpt(content),
    }


def build_payload(docs: list, generated_at: Optional[dt.datetime] = None) -> dict:
    stamp = (generated_at or dt.datetime.now(dt.timezone.utc)).replace(microsecond=0)
    entries = [build_entry(doc) for doc in docs]
    iso = stamp.isoformat().replace("+00:00", "Z")
    return {"generated_at": iso, "count": len(entries), "entries": entries}


def to_json(docs: list, generated_at: Optional[dt.datetime] = None) -> str:
    return json.dumps(build_payload(docs, generated_at), indent=2, ensure_ascii=False)
