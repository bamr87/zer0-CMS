#!/usr/bin/env python3
"""Record what a static site builds, and compare two recordings (PLAN P1).

ADR 0006 decision 4: a site keeps its URLs, content, feeds and redirects
whichever way it renders. So every routed site's Jekyll build is recorded while
Jekyll still runs, and a site moves — to the Jekyll-theme option (P2) or to the
React renderer (P6, P7) — only when its new build reproduces the recording.
This is the recorder and the comparison; the recordings are
`web/site/fixtures/<site>/manifest.json`.

A manifest (`schema: site-manifest/v1`) holds:

  * `paths` — every output file and its media type; an HTML page also has its
    `title` and `text_sha256`, the SHA-256 of its main text: the text of its
    <main> (else of its <article>s, else of its <body>) without the header,
    nav, footer, aside, button, svg, time, script, style, noscript and template
    elements in it, a space at every block boundary, whitespace collapsed — the
    words a reader reads, not the markup or the theme's chrome around them.
    <time> is left out because Jekyll dates a document that has no date of its
    own with the time of the build, and a digest must not change by the day;
  * `feeds` — each Atom or RSS file's entries (id, link, title), in order;
  * `sitemaps` — each sitemap's URLs, sorted;
  * `redirects` — each page that redirects (a meta refresh, as
    jekyll-redirect-from writes them) and its target.

The output is deterministic: sorted keys and paths, a trailing newline, and
media types from the table below rather than Python's `mimetypes`, whose
built-in table grows with each release (3.13 added .webp, 3.14 .woff2 and
.ttf), so a manifest written by one interpreter would not match another's.

  build <dir> --site <name> --out <file>   write the manifest of a built site
  compare <recorded> <candidate>           list what differs; exit 1 if anything does
  --check [--site <name>]...               rebuild each routed site the way pages.yml
                                           does and compare it with its recording
  --write [--site <name>]...               rebuild and (re)write the recordings

`--check` and `--write` need what pages.yml needs — Ruby, each site's bundle and
the network (gems, remote themes) — and read the route plan from
`bin/zer0 routes --json`. Stdlib only. Tests: tools/tests/test_site_manifest.py;
the recordings and how to refresh them: web/site/fixtures/README.md.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "web" / "site" / "fixtures"
SCHEMA = "site-manifest/v1"

# What pages.yml builds with when no repository variable overrides it.
PAGES_URL = "https://bamr87.github.io"
PAGES_BASE_PATH = "/zer0-CMS"
PAGES_REPO_NWO = "bamr87/zer0-CMS"

TYPES = {
    "atom": "application/atom+xml",
    "avif": "image/avif",
    "bmp": "image/bmp",
    "css": "text/css",
    "csv": "text/csv",
    "eot": "application/vnd.ms-fontobject",
    "gif": "image/gif",
    "htm": "text/html",
    "html": "text/html",
    "ico": "image/vnd.microsoft.icon",
    "jpeg": "image/jpeg",
    "jpg": "image/jpeg",
    "js": "text/javascript",
    "json": "application/json",
    "map": "application/json",
    "md": "text/markdown",
    "mjs": "text/javascript",
    "mp3": "audio/mpeg",
    "mp4": "video/mp4",
    "otf": "font/otf",
    "pdf": "application/pdf",
    "png": "image/png",
    "rss": "application/rss+xml",
    "scss": "text/x-scss",
    "svg": "image/svg+xml",
    "ttf": "font/ttf",
    "txt": "text/plain",
    "webm": "video/webm",
    "webmanifest": "application/manifest+json",
    "webp": "image/webp",
    "woff": "font/woff",
    "woff2": "font/woff2",
    "xml": "application/xml",
    "xsl": "application/xslt+xml",
    "yaml": "application/yaml",
    "yml": "application/yaml",
    "zip": "application/zip",
}
FEED_TYPES = {"application/xml", "application/atom+xml", "application/rss+xml"}
ROOTS = ("main", "article", "body")
SKIP = frozenset(
    {"header", "nav", "footer", "aside", "button", "svg", "time", "script", "style", "noscript", "template"}
)
VOID = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
BLOCK = frozenset(
    "address article aside blockquote body br caption dd details dialog div dl dt fieldset figcaption figure footer "
    "form h1 h2 h3 h4 h5 h6 header hgroup hr li main nav ol p pre section summary table tbody td tfoot th thead "
    "tr ul".split()
)
ATOM = "{http://www.w3.org/2005/Atom}"
SITEMAP = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def media_type(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name.lstrip(".") else ""
    return TYPES.get(ext, "application/octet-stream")


def collapse(text: str) -> str:
    return " ".join(text.split())


class _Page(HTMLParser):
    """One pass over an HTML page: its title, the text under each candidate root, its refresh target."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open: list[str] = []
        self.seen: set[str] = set()
        self.text: dict[str, list[str]] = {root: [] for root in (*ROOTS, "")}
        self.titles: list[list[str]] = []
        self.in_title = False
        self.refresh: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta" and self.refresh is None:
            meta = dict(attrs)
            if (meta.get("http-equiv") or "").lower() == "refresh":
                target = re.search(r"url\s*=\s*['\"]?([^'\"]+)", meta.get("content") or "", re.I)
                self.refresh = target.group(1).strip() if target else None
        if tag == "title" and "svg" not in self.open:
            self.in_title = True
            self.titles.append([])
        if tag in BLOCK:
            self._break()
        if tag not in VOID:
            self.open.append(tag)
            self.seen.add(tag)

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if tag in self.open:  # HTML lets an end tag close the elements left open inside it
            while self.open.pop() != tag:
                pass
        if tag in BLOCK:
            self._break()

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.titles[-1].append(data)
        if SKIP.isdisjoint(self.open):
            for root, parts in self.text.items():
                if not root or root in self.open:
                    parts.append(data)

    def _break(self) -> None:
        """A block boundary separates words wherever it falls; collapsing removes the extra spaces."""
        for parts in self.text.values():
            parts.append(" ")

    def main_text(self) -> str:
        root = next((r for r in ROOTS if r in self.seen), "")
        return collapse("".join(self.text[root]))


def html_facts(raw: bytes) -> tuple[str, str, str | None]:
    """(title, SHA-256 of the main text, redirect target or None) of one HTML page."""
    page = _Page()
    page.feed(raw.decode("utf-8", "replace"))
    page.close()
    title = collapse("".join(page.titles[0])) if page.titles else ""
    return title, hashlib.sha256(page.main_text().encode("utf-8")).hexdigest(), page.refresh


def _text(element: ET.Element | None) -> str:
    return collapse("".join(element.itertext())) if element is not None else ""


def _atom_link(entry: ET.Element) -> str:
    links = [link for link in entry.findall(ATOM + "link") if link.get("rel", "alternate") == "alternate"]
    return links[0].get("href", "") if links else ""


def xml_facts(raw: bytes) -> tuple[str, list] | None:
    """("feeds", entries) for an Atom or RSS feed, ("sitemaps", urls) for a sitemap, else None."""
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return None
    if root.tag == ATOM + "feed":
        entries = root.iter(ATOM + "entry")
        return "feeds", [
            {"id": _text(e.find(ATOM + "id")), "link": _atom_link(e), "title": _text(e.find(ATOM + "title"))}
            for e in entries
        ]
    if root.tag == "rss":
        items = root.iter("item")
        return "feeds", [
            {
                "id": _text(i.find("guid")) or _text(i.find("link")),
                "link": _text(i.find("link")),
                "title": _text(i.find("title")),
            }
            for i in items
        ]
    if root.tag in (SITEMAP + "urlset", SITEMAP + "sitemapindex"):
        return "sitemaps", sorted(_text(loc) for loc in root.iter(SITEMAP + "loc"))
    return None


def manifest(site_dir: Path, site: str) -> dict:
    """The manifest of one built site directory."""
    result: dict = {"schema": SCHEMA, "site": site, "paths": {}, "feeds": {}, "sitemaps": {}, "redirects": {}}
    for file in sorted(p for p in site_dir.rglob("*") if p.is_file()):
        rel = file.relative_to(site_dir).as_posix()
        entry = result["paths"][rel] = {"type": media_type(rel)}
        if entry["type"] == "text/html":
            entry["title"], entry["text_sha256"], target = html_facts(file.read_bytes())
            if target is not None:
                result["redirects"][rel] = target
        elif entry["type"] in FEED_TYPES:
            facts = xml_facts(file.read_bytes())
            if facts:
                result[facts[0]][rel] = facts[1]
    return result


def dumps(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps(data), encoding="utf-8")


def _list_diff(old: list, new: list) -> list[str]:
    old_keys = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in old]
    new_keys = [json.dumps(item, sort_keys=True, ensure_ascii=False) for item in new]
    missing = [f"missing {k}" for k in old_keys if k not in new_keys]
    extra = [f"extra {k}" for k in new_keys if k not in old_keys]
    return missing + extra or ["reordered"]


def compare(recorded: dict, candidate: dict) -> list[str]:
    """Every way `candidate` differs from `recorded`, one line each; empty when it reproduces it."""
    if recorded.get("schema") != candidate.get("schema"):
        return [f"schema   {recorded.get('schema')} → {candidate.get('schema')}"]
    old, new = recorded["paths"], candidate["paths"]
    diffs = [f"missing  {p}" for p in sorted(old.keys() - new.keys())]
    diffs += [f"extra    {p}" for p in sorted(new.keys() - old.keys())]
    for p in sorted(old.keys() & new.keys()):
        for key in ("type", "title"):
            if old[p].get(key) != new[p].get(key):
                diffs.append(f"{key:<8} {p}: {old[p].get(key)!r} → {new[p].get(key)!r}")
        if old[p].get("text_sha256") != new[p].get("text_sha256"):
            diffs.append(f"text     {p}")
    for section, label in (("feeds", "feed"), ("sitemaps", "sitemap"), ("redirects", "redirect")):
        a, b = recorded.get(section, {}), candidate.get(section, {})
        for p in sorted(a.keys() | b.keys()):
            if p not in b or p not in a:
                diffs.append(f"{label:<8} {p}: {'missing' if p not in b else 'extra'}")
            elif a[p] != b[p]:
                lines = _list_diff(a[p], b[p]) if isinstance(a[p], list) else [f"{a[p]} → {b[p]}"]
                diffs += [f"{label:<8} {p}: {line}" for line in lines]
    return diffs


def routes() -> list[dict]:
    """The routed sites, as pages.yml plans them (`bin/zer0 routes --json`)."""
    out = subprocess.run(
        [str(ROOT / "bin" / "zer0"), "routes", "--json"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return json.loads(out.stdout)


def rebuild(route: dict, dest: Path) -> bool:
    """Build one routed site into `dest` the way pages.yml's build job does; True when it built an index.html."""
    baseurl = PAGES_BASE_PATH.rstrip("/") + route["route"].rstrip("/")
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "route.yml"
        config.write_text(f'url: "{PAGES_URL}"\nbaseurl: "{baseurl}"\n', encoding="utf-8")
        env = {
            **os.environ,
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8",
            "PAGES_REPO_NWO": PAGES_REPO_NWO,
            "ZER0_PAGES_CONFIG": str(config),
            "ZER0_PAGES_DEST": str(dest),
            "ZER0_PAGES_BASEURL": baseurl,
        }
        steps = (
            (["bundle", "install"], ROOT / route["bundle_dir"]),
            ([str(ROOT / "bin" / "zer0"), "run", "pages", route["name"]], ROOT),
        )
        return (
            all(subprocess.run(cmd, cwd=cwd, env=env).returncode == 0 for cmd, cwd in steps)
            and (dest / "index.html").is_file()
        )


def report(diffs: list[str], what: str) -> None:
    for line in diffs:
        print(f"  {line}")
    # flushed, so the verdict lands after its site's build log rather than after every site's
    print(f"{what}: {len(diffs)} difference(s)" if diffs else f"{what}: identical", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--check", action="store_true", help="rebuild the routed sites and compare each with its recording"
    )
    mode.add_argument("--write", action="store_true", help="rebuild the routed sites and (re)write their recordings")
    parser.add_argument("--site", action="append", default=[], help="only this routed site (repeatable)")
    parser.add_argument(
        "--fixtures", type=Path, default=FIXTURES, help="the recordings: <fixtures>/<site>/manifest.json"
    )
    commands = parser.add_subparsers(dest="command")
    build = commands.add_parser("build", help="write the manifest of a built site directory")
    build.add_argument("dir", type=Path)
    build.add_argument("--site", required=True, dest="name")
    build.add_argument("--out", type=Path, required=True)
    comparison = commands.add_parser(
        "compare", help="list what differs between two manifests (exit 1 when anything does)"
    )
    comparison.add_argument("recorded", type=Path)
    comparison.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)

    if args.command == "build":
        if not args.dir.is_dir():
            parser.error(f"{args.dir} is not a directory")
        write(args.out, manifest(args.dir, args.name))
        return 0
    if args.command == "compare":
        diffs = compare(load(args.recorded), load(args.candidate))
        report(diffs, f"{args.candidate} against {args.recorded}")
        return 1 if diffs else 0
    if not (args.check or args.write):
        parser.print_help()
        return 2

    plan = routes()
    unknown = sorted(set(args.site) - {r["name"] for r in plan})
    if unknown:
        parser.error(f"not a routed site: {', '.join(unknown)} (bin/zer0 routes)")
    failed = False
    for route in plan:
        name = route["name"]
        if args.site and name not in args.site:
            continue
        recorded = args.fixtures / name / "manifest.json"
        with tempfile.TemporaryDirectory() as tmp:
            built = rebuild(route, Path(tmp) / "site")
            fresh = manifest(Path(tmp) / "site", name) if built else None
        if fresh is None:
            print(f"{name}: the build failed (see above)", file=sys.stderr)
            failed = True
        elif args.write:
            write(recorded, fresh)
            print(f"{name}: recorded {len(fresh['paths'])} paths in {recorded}", flush=True)
        elif not recorded.is_file():
            print(f"{name}: nothing recorded at {recorded}", flush=True)
            failed = True
        else:
            diffs = compare(load(recorded), fresh)
            report(diffs, f"{name} against {recorded}")
            failed = failed or bool(diffs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
