"""Crawling a site for an audit: AIEO's site snapshot discovery (`apps/aieo/backend/app/services/site_snapshot/
discovery.py`) on the research library's guarded fetcher.

Cheap first, as AIEO did: robots.txt (its sitemaps and its rules), then the sitemaps (a sitemap index followed three
levels deep), then the feed (`/feed.xml`, `/atom.xml`, `/feed/`, `/rss.xml`, read with feedparser through
`research.fetch.entries`), then the links of the pages fetched — same host only, never an asset, a date archive, a
pagination or a taxonomy page, never a path robots.txt disallows for the platform's user agent. Every request —
robots.txt, a sitemap, a feed, a page — goes through `research.fetch.get`, so the SSRF guard, the redirect checks,
and the size and time limits hold for each, and it runs only in a worker (an audit's run). A crawl stops at
`max_pages` pages; what it reads becomes the audit's pages and its link map — the hubs most pages link to, and the
orphans no other crawled page links to.
"""

import re
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass, field
from urllib.parse import urldefrag, urljoin, urlparse, urlunparse
from urllib.robotparser import RobotFileParser

from bs4 import BeautifulSoup
from django.conf import settings

from research import fetch

ASSET = re.compile(
    r"\.(png|jpe?g|gif|svg|webp|ico|css|js|mjs|json|xml|txt|pdf|zip|gz|tgz|mp[34]|m4a|mov|avi|webm|woff2?|ttf|eot|"
    r"map|rss|atom)$",
    re.IGNORECASE,
)
TRAP = re.compile(r"/(?:19|20)\d{2}/|/page[-/]?\d+/?$|[?&]page=\d+", re.IGNORECASE)
DENIED = ("/assets/", "/tag/", "/tags/", "/category/", "/categories/", "/page/")
FEEDS = ("/feed.xml", "/atom.xml", "/feed/", "/rss.xml")
XML_DECLARATION = re.compile(rb"<!(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)
HTML = ("text/html", "application/xhtml+xml")


@dataclass
class Fetched:
    url: str
    status: int = 0
    html: str = ""
    title: str = ""
    links: list[str] = field(default_factory=list)
    source: str = "seed"  # how it was found: seed, sitemap, feed, link
    error: str = ""


@dataclass
class Crawl:
    pages: list[Fetched]
    discovery: dict
    robots: str  # present or absent


def host(netloc: str) -> str:
    """Host comparison key: lowercased, 'www.' stripped, port dropped."""
    netloc = (netloc or "").lower().rsplit("@", 1)[-1].split(":", 1)[0]
    return netloc.removeprefix("www.")


def normalize(url: str, base: str) -> str | None:
    """The URL as an identity — fragment dropped, scheme and host lowercased, default port and a trailing
    index.html dropped, slashes collapsed — or None when it is not a page to crawl."""
    url = (url or "").strip()
    if not url or url.lower().startswith(("mailto:", "tel:", "javascript:", "data:", "#")):
        return None
    absolute, _ = urldefrag(urljoin(base, url))
    parts = urlparse(absolute)
    if parts.scheme not in ("http", "https"):
        return None
    netloc = parts.netloc.lower()
    if (parts.scheme, netloc[-3:]) == ("http", ":80") or (parts.scheme, netloc[-4:]) == ("https", ":443"):
        netloc = netloc.rsplit(":", 1)[0]
    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    for index in ("/index.html", "/index.htm"):
        if path.endswith(index):
            path = path[: -len(index) + 1]
    if ASSET.search(path):
        return None
    return urlunparse((parts.scheme, netloc, path, "", parts.query, ""))


def xml_root(body: bytes):
    """Untrusted XML's root, refusing any DTD or entity declaration (no sitemap or feed needs one)."""
    if XML_DECLARATION.search(body):
        return None
    try:
        return ET.fromstring(body)
    except ET.ParseError:
        return None


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _get(url: str):
    """A document through the guarded fetcher, or None when it cannot be had (an error, a non-200)."""
    try:
        got = fetch.get(url)
    except fetch.FetchError:
        return None
    return got if got.status == 200 else None


def robots_for(base: str) -> tuple[RobotFileParser, list[str], bool]:
    """The site's robots.txt rules, the sitemaps it declares, and whether it has one."""
    rules = RobotFileParser()
    got = _get(urljoin(base, "/robots.txt"))
    if got is None:
        rules.allow_all = True
        return rules, [], False
    rules.parse(got.text().splitlines())
    return rules, list(rules.site_maps() or []), True


def sitemap_urls(sitemaps: list[str], depth: int = 0, seen: set | None = None) -> list[str]:
    """The page URLs of a sitemap or a sitemap index (nested at most three levels)."""
    seen = seen if seen is not None else set()
    found: list[str] = []
    if depth > 3:
        return found
    for address in sitemaps:
        if address in seen:
            continue
        seen.add(address)
        got = _get(address)
        root = xml_root(got.body) if got is not None else None
        if root is None:
            continue
        locations = [el.text.strip() for el in root.iter() if _local(el.tag) == "loc" and el.text and el.text.strip()]
        if _local(root.tag) == "sitemapindex":
            found += sitemap_urls(locations, depth + 1, seen)
        else:
            found += locations
    return found


def feed_urls(base: str) -> list[str]:
    for candidate in FEEDS:
        got = _get(urljoin(base, candidate))
        if got is None:
            continue
        try:
            _, items = fetch.entries(got.body)
        except fetch.FetchError:
            continue
        urls = [item["url"] for item in items if item.get("url")]
        if urls:
            return urls
    return []


def read_page(url: str, source: str) -> Fetched:
    try:
        got = fetch.get(url)
    except fetch.FetchError as e:
        return Fetched(url, source=source, error=str(e))
    page = Fetched(got.url, got.status, source=source)
    if got.status >= 400:
        page.error = f"the site answered HTTP {got.status}"
        return page
    if got.content_type.split(";", 1)[0].strip().lower() not in HTML:
        page.error = f"not a web page ({got.content_type or 'no content type'})"
        return page
    page.html = got.text()
    soup = BeautifulSoup(page.html, "html.parser")
    page.title = soup.title.get_text(strip=True)[:500] if soup.title else ""
    page.links = [a["href"] for a in soup.find_all("a", href=True)]
    return page


def crawl(base: str, *, max_pages: int = 25) -> Crawl:
    """Pages of the site at `base`, discovered cheap-first and fetched in order until `max_pages` are read."""
    root = host(urlparse(base).netloc)
    rules, declared, present = robots_for(base)
    agent = settings.RESEARCH_USER_AGENT
    order: list[tuple[str, str]] = []
    queued: set[str] = set()

    def add(url: str, source: str) -> bool:
        """Queue a page of this site the crawl may read; True when it was not queued before."""
        found = normalize(url, base)
        if not found or found in queued or host(urlparse(found).netloc) != root or TRAP.search(found):
            return False
        if any((urlparse(found).path or "/").startswith(prefix) for prefix in DENIED):
            return False
        if not rules.can_fetch(agent, found):
            return False
        queued.add(found)
        order.append((found, source))
        return True

    add(base, "seed")
    counts = {"sitemap": 0, "feed": 0, "link": 0}
    for url in sitemap_urls(declared or [urljoin(base, "/sitemap.xml")]):
        counts["sitemap"] += add(url, "sitemap")
    for url in feed_urls(base):
        counts["feed"] += add(url, "feed")

    pages: list[Fetched] = []
    for url, source in iter_queue(order):
        if len(pages) >= max_pages:
            break
        page = read_page(url, source)
        pages.append(page)
        for link in page.links:
            counts["link"] += add(urljoin(page.url, link), "link")
    discovery = {
        "source": "sitemap" if counts["sitemap"] else ("feed" if counts["feed"] else "links"),
        "sitemap_urls": counts["sitemap"],
        "feed_urls": counts["feed"],
        "link_followed": counts["link"],
        "robots_sitemaps": len(declared),
        "queued": len(order),
    }
    return Crawl(pages, discovery, "present" if present else "absent")


def iter_queue(order: list):
    """The queue in order, including what is added to it while it is read."""
    i = 0
    while i < len(order):
        yield order[i]
        i += 1


def link_map(pages: list[Fetched], base: str, limit: int = 10) -> dict:
    """Which crawled pages the others link to most (hubs) and which no other crawled page links to (orphans)."""
    crawled = {normalize(p.url, base) for p in pages if not p.error}
    inbound: Counter = Counter()
    for page in pages:
        if page.error:
            continue
        me = normalize(page.url, base)
        targets = {normalize(link, page.url) for link in page.links}
        inbound.update(t for t in targets if t in crawled and t != me)
    seed = normalize(base, base)
    return {
        "hubs": [{"url": url, "inbound": n} for url, n in inbound.most_common(limit)],
        "orphans": sorted(url for url in crawled if url != seed and inbound[url] == 0),
    }
