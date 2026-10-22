#!/usr/bin/env python3
"""Record what a static site builds, and compare two recordings (PLAN P1).

ADR 0006 decision 4: a site keeps its URLs, content, feeds and redirects
whichever way it renders. So every site's Jekyll build is recorded while Jekyll
still runs, and a site moves — to the Jekyll-theme option (P2) or to the React
renderer (P6, P7) — only when its new build reproduces the recording. This is the
recorder and the comparison; the recordings are
`web/site/fixtures/<site>/manifest.json`.

A manifest (`schema: site-manifest/v2`) holds:

  * `paths` — every output file and its media type. An HTML page also has its
    `title`, its `text` and `text_sha256`, the SHA-256 of that text joined with
    spaces. The text is the page's own content as blocks of words: the elements
    the page marks as its entry's content (microformats `e-content`, schema.org
    `articleBody`), else the theme's content column (`bd-content`), else its
    <main>, its <article>s, its <body> — without the header, nav, footer, aside,
    button, svg, time, script, style, noscript and template elements in it, a
    new block at every block element, whitespace collapsed. That leaves out the
    layout around the content (the title banner, reading time, share and edit
    menus, table of contents, sidebars), which another design system lays out
    its own way, and <time>, which Jekyll fills with the build's date on a page
    that has none;
  * `feeds` — each Atom or RSS file's entries (id, link, title, and the
    published and updated instants in UTC), in order; not the feed's own
    update time, which is the build's;
  * `sitemaps` — each sitemap's URLs, sorted; not their lastmod, which is the
    build's time for an undated page;
  * `redirects` — each page that redirects (a meta refresh, as
    jekyll-redirect-from writes them) and its target;
  * `built_with` — when the build's source directory is known: each gem its
    bundle resolved, and the commit its `remote_theme:` resolved to. Neither is
    pinned by the repository, so a comparison prints what changed there and
    does not count it.

The output is deterministic: sorted keys and paths, a trailing newline, and
media types from the table below rather than Python's `mimetypes`, whose
built-in table grows with each release (3.13 added .webp, 3.14 .woff2 and
.ttf), so a manifest written by one interpreter would not match another's.

  build <dir> --site <name> --out <file> [--source <dir>]
                                    write the manifest of a built site; --source is the
                                    directory it was built from (its Gemfile.lock, _config.yml)
  compare [--pages] <recorded> <candidate>
                                    list what differs; exit 1 if anything does. --pages
                                    compares only what a reader reaches: the HTML pages,
                                    feeds, sitemaps and redirects, not the other files
  --check [--pages] [--site <name>]...
                                    rebuild each routed site the way pages.yml does and
                                    compare it with its recording
  --write [--site <name>]...        rebuild and (re)write the recordings

`--check` and `--write` need what pages.yml needs — Ruby, each site's bundle and
the network (gems, remote themes) — and read the route plan from
`bin/zer0 routes --json`. Wherever they run, they build as pages.yml's runners
do: in UTC, and without the caller's build variables (NOT_INHERITED below).
Stdlib only. Tests: tools/tests/test_site_manifest.py; the recordings and how
to refresh them: web/site/fixtures/README.md.
"""

from __future__ import annotations

import argparse
import difflib
import email.utils
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = ROOT / "web" / "site" / "fixtures"
SCHEMA = "site-manifest/v2"

# What pages.yml builds with when no repository variable overrides it.
PAGES_URL = "https://bamr87.github.io"
PAGES_BASE_PATH = "/zer0-CMS"
PAGES_REPO_NWO = "bamr87/zer0-CMS"
# The caller's variables a pages.yml runner does not have and a build reads: JEKYLL_ENV (the
# theme's development-only blocks), JEKYLL_GITHUB_TOKEN, OCTOKIT_ and PAGES_ (what
# jekyll-github-metadata fetches and reports), ZER0_ (a site's Gemfile swaps in a local theme on
# one) and BUNDLE_GEMFILE (another bundle). The rebuild sets its own PAGES_REPO_NWO and ZER0_PAGES_*.
NOT_INHERITED = ("JEKYLL_", "PAGES_", "ZER0_", "OCTOKIT_", "BUNDLE_GEMFILE")

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
ROOTS = ("entry", "column", "main", "article", "body")  # where a page's content is, most specific first
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
GEM = re.compile(
    r"^    ([^\s(]+) \(([^)\s]+)\)$", re.MULTILINE
)  # a resolved spec in Gemfile.lock, e.g. "    jekyll (4.4.1)"
REMOTE_THEME = re.compile(r"""^remote_theme\s*:\s*["']?([^"'\s#]+)""", re.MULTILINE)


def media_type(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name.lstrip(".") else ""
    return TYPES.get(ext, "application/octet-stream")


def collapse(text: str) -> str:
    return " ".join(text.split())


def _roots(tag: str, attrs: list[tuple[str, str | None]]) -> set[str]:
    """The ROOTS an element opens: its own tag, an entry's marked content, the theme's content column."""
    attr = dict(attrs)
    classes = (attr.get("class") or "").split()
    roots = {tag} & {"main", "article", "body"}
    if "e-content" in classes or "articleBody" in (attr.get("itemprop") or "").split():
        roots.add("entry")
    if "bd-content" in classes:
        roots.add("column")
    return roots


class _Page(HTMLParser):
    """One pass over an HTML page: its title, the text blocks under each candidate root, its refresh target."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.open: list[tuple[str, set[str]]] = []  # each open element and the roots it opens
        self.seen: set[str] = set()
        self.blocks: dict[str, list[list[str]]] = {root: [[]] for root in (*ROOTS, "")}  # "" is the whole page
        self.titles: list[list[str]] = []
        self.in_title = False
        self.refresh: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "meta" and self.refresh is None:
            meta = dict(attrs)
            if (meta.get("http-equiv") or "").lower() == "refresh":
                target = re.search(r"url\s*=\s*['\"]?([^'\"]+)", meta.get("content") or "", re.IGNORECASE)
                self.refresh = target.group(1).strip() if target else None
        if tag == "title" and all(open_tag != "svg" for open_tag, _ in self.open):
            self.in_title = True
            self.titles.append([])
        if tag in BLOCK:
            self._break()
        if tag not in VOID:
            roots = _roots(tag, attrs)
            self.open.append((tag, roots))
            self.seen |= roots

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.in_title = False
        if any(open_tag == tag for open_tag, _ in self.open):  # HTML lets an end tag close what is left open inside it
            while self.open.pop()[0] != tag:
                pass
        if tag in BLOCK:
            self._break()

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.titles[-1].append(data)
        if all(open_tag not in SKIP for open_tag, _ in self.open):
            for root in {""}.union(*(roots for _, roots in self.open)):
                self.blocks[root][-1].append(data)

    def _break(self) -> None:
        """A block element starts a new block of words wherever it falls."""
        for blocks in self.blocks.values():
            if blocks[-1]:
                blocks.append([])

    def content(self) -> list[str]:
        root = next((r for r in ROOTS if r in self.seen), "")
        return [text for text in (collapse("".join(parts)) for parts in self.blocks[root]) if text]


def html_facts(raw: bytes) -> tuple[str, list[str], str | None]:
    """(title, the blocks of its content's text, redirect target or None) of one HTML page."""
    page = _Page()
    page.feed(raw.decode("utf-8", "replace"))
    page.close()
    title = collapse("".join(page.titles[0])) if page.titles else ""
    return title, page.content(), page.refresh


def digest(text: list[str]) -> str:
    return hashlib.sha256(" ".join(text).encode("utf-8")).hexdigest()


def _text(element: ET.Element | None) -> str:
    return collapse("".join(element.itertext())) if element is not None else ""


def _instant(value: str) -> str:
    """A feed date as the UTC instant it names, so the same moment spelled another way still matches."""
    try:
        when = datetime.fromisoformat(value) if value[:1].isdigit() else email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return value
    return when.astimezone(UTC).isoformat() if when.tzinfo else when.isoformat()


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
        return "feeds", [
            {
                "id": _text(e.find(ATOM + "id")),
                "link": _atom_link(e),
                "title": _text(e.find(ATOM + "title")),
                "published": _instant(_text(e.find(ATOM + "published"))),
                "updated": _instant(_text(e.find(ATOM + "updated"))),
            }
            for e in root.iter(ATOM + "entry")
        ]
    if root.tag == "rss":
        return "feeds", [
            {
                "id": _text(i.find("guid")) or _text(i.find("link")),
                "link": _text(i.find("link")),
                "title": _text(i.find("title")),
                "published": _instant(_text(i.find("pubDate"))),
                "updated": "",
            }
            for i in root.iter("item")
        ]
    if root.tag in (SITEMAP + "urlset", SITEMAP + "sitemapindex"):
        return "sitemaps", sorted(_text(loc) for loc in root.iter(SITEMAP + "loc"))
    return None


def built_with(source: Path) -> dict:
    """What a build of `source` resolved that the repository does not pin: its gems and its remote theme's commit."""
    lock = source / "Gemfile.lock"
    gems = GEM.findall(lock.read_text(encoding="utf-8")) if lock.is_file() else []
    # "nokogiri (1.18.10-x86_64-linux-gnu)": the platform is the machine's, not the build's
    result: dict = {"gems": {name: version.split("-")[0] for name, version in gems}}
    config = source / "_config.yml"
    theme = REMOTE_THEME.search(config.read_text(encoding="utf-8")) if config.is_file() else None
    if theme:
        nwo, _, ref = theme.group(1).partition("@")
        result["remote_theme"] = {theme.group(1): _head(f"https://github.com/{nwo}", ref or "HEAD")}
    return result


def _head(repository: str, ref: str) -> str:
    """What `ref` of a repository points at now, or "" when git cannot tell (no git, no network, no such ref)."""
    try:
        out = subprocess.run(["git", "ls-remote", repository, ref], capture_output=True, text=True, check=False)
    except OSError:
        return ""
    return (out.stdout.split() or [""])[0]


def manifest(site_dir: Path, site: str, source: dict | None = None) -> dict:
    """The manifest of one built site directory; `source` is what its build resolved (`built_with`)."""
    result: dict = {"schema": SCHEMA, "site": site, "paths": {}, "feeds": {}, "sitemaps": {}, "redirects": {}}
    if source is not None:
        result["built_with"] = source
    for file in sorted(p for p in site_dir.rglob("*") if p.is_file()):
        rel = file.relative_to(site_dir).as_posix()
        entry = result["paths"][rel] = {"type": media_type(rel)}
        if entry["type"] == "text/html":
            entry["title"], entry["text"], target = html_facts(file.read_bytes())
            entry["text_sha256"] = digest(entry["text"])
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


def _text_diff(old: list[str], new: list[str], limit: int = 12) -> list[str]:
    """The blocks a page's text lost (-) and gained (+), the first `limit` of them."""
    lines = [line for line in list(difflib.unified_diff(old, new, lineterm="", n=0))[2:] if not line.startswith("@@")]
    more = [f"… {len(lines) - limit} more"] if len(lines) > limit else []
    return [f"         {line}" for line in lines[:limit] + more]


def compare(recorded: dict, candidate: dict, pages: bool = False) -> list[str]:
    """Every way `candidate` differs from `recorded`, one line each; empty when it reproduces it.

    `pages` compares only what a reader reaches — the HTML pages, feeds, sitemaps and redirects — and
    not the other files (a theme's styles, scripts, fonts and images), which a renderer in another
    design system does not reproduce.
    """
    if recorded.get("schema") != candidate.get("schema"):
        return [f"schema   {recorded.get('schema')} → {candidate.get('schema')}"]
    old, new = (
        {p: e for p, e in m["paths"].items() if not pages or e["type"] == "text/html"} for m in (recorded, candidate)
    )
    diffs = [f"missing  {p}" for p in sorted(old.keys() - new.keys())]
    diffs += [f"extra    {p}" for p in sorted(new.keys() - old.keys())]
    for p in sorted(old.keys() & new.keys()):
        for key in ("type", "title"):
            if old[p].get(key) != new[p].get(key):
                diffs.append(f"{key:<8} {p}: {old[p].get(key)!r} → {new[p].get(key)!r}")
        if old[p].get("text_sha256") != new[p].get("text_sha256"):
            diffs += [f"text     {p}", *_text_diff(old[p].get("text", []), new[p].get("text", []))]
    for section, label in (("feeds", "feed"), ("sitemaps", "sitemap"), ("redirects", "redirect")):
        a, b = recorded.get(section, {}), candidate.get(section, {})
        for p in sorted(a.keys() | b.keys()):
            if p not in b or p not in a:
                diffs.append(f"{label:<8} {p}: {'missing' if p not in b else 'extra'}")
            elif a[p] != b[p]:
                lines = _list_diff(a[p], b[p]) if isinstance(a[p], list) else [f"{a[p]} → {b[p]}"]
                diffs += [f"{label:<8} {p}: {line}" for line in lines]
    return diffs


def resolved_differently(recorded: dict, candidate: dict) -> list[str]:
    """What the two builds resolved differently — gem versions, the theme's commit — to explain a difference."""
    old, new = recorded.get("built_with") or {}, candidate.get("built_with") or {}
    notes = []
    for section in sorted(old.keys() & new.keys()):
        a, b = old[section], new[section]
        if a and b:
            notes += [
                f"{section}: {key} {a.get(key, '(none)')} → {b.get(key, '(none)')}"
                for key in sorted(a.keys() | b.keys())
                if a.get(key) != b.get(key)
            ]
    return notes


def routes() -> list[dict]:
    """The routed sites, as pages.yml plans them (`bin/zer0 routes --json`)."""
    out = subprocess.run(
        [str(ROOT / "bin" / "zer0"), "routes", "--json"], cwd=ROOT, check=True, capture_output=True, text=True
    )
    return json.loads(out.stdout)


def rebuild(route: dict, dest: Path) -> dict | None:
    """Build one routed site into `dest` the way pages.yml's build job does.

    Returns what the build resolved (`built_with`), or None when it failed or wrote no index.html. A
    Gemfile.lock the bundle writes where none is committed is removed again, so the next run resolves
    afresh as CI does.
    """
    source = ROOT / route["bundle_dir"]
    lock = source / "Gemfile.lock"
    locked = lock.exists()
    baseurl = PAGES_BASE_PATH.rstrip("/") + route["route"].rstrip("/")
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "route.yml"
        config.write_text(f'url: "{PAGES_URL}"\nbaseurl: "{baseurl}"\n', encoding="utf-8")
        env = {key: value for key, value in os.environ.items() if not key.startswith(NOT_INHERITED)}
        env.update(
            TZ="UTC",  # pages.yml's runners' zone: Jekyll dates a post, and so its URL, in the process's zone
            LANG="C.UTF-8",
            LC_ALL="C.UTF-8",
            PAGES_REPO_NWO=PAGES_REPO_NWO,
            ZER0_PAGES_CONFIG=str(config),
            ZER0_PAGES_DEST=str(dest),
            ZER0_PAGES_BASEURL=baseurl,
        )
        steps = (
            (["bundle", "install"], source),
            ([str(ROOT / "bin" / "zer0"), "run", "pages", route["name"]], ROOT),
        )
        try:
            built = all(subprocess.run(cmd, cwd=cwd, env=env, check=False).returncode == 0 for cmd, cwd in steps)
            return built_with(source) if built and (dest / "index.html").is_file() else None
        finally:
            if not locked:
                lock.unlink(missing_ok=True)


def report(diffs: list[str], notes: list[str], what: str) -> None:
    for line in diffs:
        print(f"  {line}")
    if notes:
        print("  built with other versions than the recording (not counted):")
        print("\n".join(f"    {note}" for note in notes))
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
    pages_help = "compare only the HTML pages, feeds, sitemaps and redirects, not the other files"
    parser.add_argument("--pages", action="store_true", help=pages_help)
    commands = parser.add_subparsers(dest="command")
    build = commands.add_parser("build", help="write the manifest of a built site directory")
    build.add_argument("dir", type=Path)
    build.add_argument("--site", required=True, dest="name")
    build.add_argument("--out", type=Path, required=True)
    build.add_argument("--source", type=Path, help="the directory it was built from: record what it resolved")
    comparison = commands.add_parser(
        "compare", help="list what differs between two manifests (exit 1 when anything does)"
    )
    comparison.add_argument("--pages", action="store_true", default=argparse.SUPPRESS, help=pages_help)
    comparison.add_argument("recorded", type=Path)
    comparison.add_argument("candidate", type=Path)
    args = parser.parse_args(argv)

    if args.command == "build":
        if not args.dir.is_dir():
            parser.error(f"{args.dir} is not a directory")
        write(args.out, manifest(args.dir, args.name, built_with(args.source) if args.source else None))
        return 0
    if args.command == "compare":
        if not args.recorded.is_file():
            print(f"nothing recorded at {args.recorded}")
            return 1
        recorded, candidate = load(args.recorded), load(args.candidate)
        diffs = compare(recorded, candidate, args.pages)
        report(diffs, resolved_differently(recorded, candidate), f"{args.candidate} against {args.recorded}")
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
            resolved = rebuild(route, Path(tmp) / "site")
            fresh = manifest(Path(tmp) / "site", name, resolved) if resolved is not None else None
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
            old = load(recorded)
            diffs = compare(old, fresh, args.pages)
            report(diffs, resolved_differently(old, fresh), f"{name} against {recorded}")
            failed = failed or bool(diffs)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
