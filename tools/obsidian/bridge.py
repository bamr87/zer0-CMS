"""The Obsidian bridge: what zer0-pages's Jekyll plugins did to a page, as plain functions.

The site was one Obsidian vault and one Jekyll site, joined by plugins that ran
inside the build (`pages/_plugins/obsidian_bridge.rb`). These are their pure
helpers, ported: the wikilink index and its resolver, a Dataview query's
documents (`docs_for`), the Markdown transform (Dataview fences, then wikilinks,
then callouts — code untouched) and the HTML pass that put the base URL on
root-relative links. `vault.py` runs them over an exported tree before a
plugin-less Jekyll builds it, and over the built pages after.
"""

from __future__ import annotations

import posixpath
import re
from typing import Callable, Optional

from . import callouts, dataview, wikilinks
from .fence_mask import replace_fences, strip

MD_EXTS = (".md", ".markdown")


def strip_ext(path: str) -> str:
    return re.sub(r"\.(md|markdown)\Z", "", re.sub(r"\A/+", "", str(path)), flags=re.IGNORECASE)


def _aliases(aliases) -> list:
    items = aliases if isinstance(aliases, list) else [aliases]
    return [dataview.to_s(a) for a in items if dataview.to_s(a)]


def build_index(entries: list) -> dict:
    """Wikilink target → URL, from `{"path", "url", "aliases"}` entries.

    Keys are each path without its extension, each alias, and each basename that only one entry
    has — each also lower-cased, since Obsidian resolves without regard to case. The first entry to
    claim a key keeps it.
    """
    index: dict = {}
    counts: dict = {}
    for entry in entries:
        key = strip_ext(entry.get("path") or "")
        if not key:
            continue
        index[key] = entry.get("url")
        index.setdefault(key.lower(), entry.get("url"))
        for alias in _aliases(entry.get("aliases")):
            index.setdefault(alias, entry.get("url"))
            index.setdefault(alias.lower(), entry.get("url"))
        base = posixpath.basename(key).lower()
        counts[base] = counts.get(base, 0) + 1
    for entry in entries:
        key = strip_ext(entry.get("path") or "")
        base = posixpath.basename(key)
        if key and counts.get(base.lower()) == 1:
            index.setdefault(base, entry.get("url"))
            index.setdefault(base.lower(), entry.get("url"))
    return index


def resolver_for(index: dict) -> Callable[[str], Optional[str]]:
    """A wikilink target → its URL, or None; tried as written, bare, rooted and with a slash, each in any case."""

    def resolve(target: str) -> Optional[str]:
        t = strip(str(target or ""))
        if not t:
            return None
        bare = strip_ext(t)
        candidates = [t, bare, "/" + bare] + ([] if t.endswith("/") else [t + "/"])
        for candidate in candidates:
            if candidate in index:
                return index[candidate]
            if candidate.lower() in index:
                return index[candidate.lower()]
        return None

    return resolve


def in_folder(path: str, folder: str) -> bool:
    return folder == "" or path == folder or path.startswith(folder + "/")


def docs_for(pool: list, source: dict) -> list:
    """The documents a query's FROM selects: under any included folder, under no excluded one."""
    selected = [d for d in pool if any(in_folder(str(d["path"]), f) for f in source.get("include") or [])]
    return [d for d in selected if not any(f and in_folder(str(d["path"]), f) for f in source.get("exclude") or [])]


def render_dataview(body: str, pool: list) -> str:
    """A ```dataview fence's replacement: the query's HTML, or a plain listing of what its FROM selects."""
    query = dataview.parse(body)
    if query:
        html = dataview.render(query, docs_for(pool, query.source))
        if html is not None:
            return "\n" + html
    source = dataview.extract_from(body) or {"include": [], "exclude": []}
    items = "\n".join(
        f'<li><a href="{wikilinks.escape_html(dataview.to_s(d.get("url")))}">'
        f'{wikilinks.escape_html(dataview.to_s(d["path"] if d.get("title") is None else d["title"]))}</a></li>'
        for d in docs_for(pool, source)
    )
    return (
        "\n<!-- obsidian-bridge: unsupported dataview query, plain listing fallback -->\n"
        f'<ul class="obsidian-dataview dataview-fallback">\n{items}\n</ul>\n'
    )


def transform(content: str, resolve: Callable[[str], Optional[str]], pool: list) -> str:
    """A page's Markdown with its Dataview fences, wikilinks and callouts resolved; code untouched."""
    out = replace_fences(content, lambda info, body: render_dataview(body, pool) if info.lower() == "dataview" else None)
    return callouts.convert(wikilinks.convert(out, resolve))


CODE = re.compile(r"(<pre\b.*?</pre>|<code\b.*?</code>)", re.IGNORECASE | re.DOTALL)
ROOTED = re.compile(r"\b(href|src)=([\"'])(/[^\"']*)\2")


def postprocess_html(html: str, baseurl: Optional[str], site_url: str = "") -> str:
    """A built page with the base URL on its root-relative href and src values, and literal
    `{{ site.url }}` / `{{ site.baseurl }}` replaced — never inside <pre> or <code>."""
    if not baseurl:
        return html

    def prefix(m: re.Match) -> str:
        value = m[3]
        if value.startswith("//") or value == baseurl or value.startswith(baseurl + "/"):
            return m[0]
        return f"{m[1]}={m[2]}{baseurl}{value}{m[2]}"

    def outside_code(part: str) -> str:
        part = re.sub(r"\{\{\s*site\.url\s*\}\}", lambda _: site_url + baseurl, part)
        part = re.sub(r"\{\{\s*site\.baseurl\s*\}\}", lambda _: baseurl, part)
        return ROOTED.sub(prefix, part)

    code = re.compile(r"<(pre|code)\b", re.IGNORECASE)
    return "".join(part if code.match(part) else outside_code(part) for part in CODE.split(html))
