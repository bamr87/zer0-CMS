"""Fetching what a person or a feed points at, without letting a URL reach inside the network.

`get(url)` is the only way research reaches the web, and only ever in a worker
(`post(url, body)`, the same guard and deadline, is how an automation notifies a
webhook):

* http and https only, and no credentials in the URL;
* the SSRF guard: the host is resolved and every address it resolves to must
  be public — not private, loopback, link-local, carrier-grade NAT, multicast,
  reserved or unspecified, IPv4-mapped forms included — and the connection
  goes to the address that was checked (the URL carries the address, `Host`
  and TLS SNI carry the name), so a DNS answer that changes between the check
  and the connection cannot move it; environment proxies are not used;
* redirects followed by hand, every hop checked again, at most five;
* the body read up to `RESEARCH_MAX_BYTES`, and the whole exchange — every
  hop's connection, headers and body — cancelled once it has taken
  `RESEARCH_FETCH_TIMEOUT` seconds, however slowly the server answers (only
  resolving a name is left to the resolver's own timeout).

`robots(url)` asks the site's robots.txt — through `get`, under the same guard —
whether our user agent may fetch the page: `allowed`, `disallowed`, or
`unknown` when there is no robots.txt to read (`robots_rules` gives the rules
themselves, for a crawl that also reads the sitemaps they declare). `extract` turns a body into text
and metadata (HTML through trafilatura, PDF through pypdf, plain text and
Markdown as they are) and `entries` reads a feed with feedparser — from bytes
already fetched, handed over as a stream, so neither library opens a URL or a
file itself.
"""

import asyncio
import html
import ipaddress
import re
import socket
from dataclasses import asdict, dataclass, field
from io import BytesIO
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import feedparser
import httpx
from charset_normalizer import from_bytes
from django.conf import settings
from django.utils.html import strip_tags

ALLOWED, DISALLOWED, UNKNOWN = "allowed", "disallowed", "unknown"
MAX_REDIRECTS = 5
MAX_PDF_PAGES = 500
HTML_TYPES = ("text/html", "application/xhtml+xml")
HEADING = re.compile(r"^#{1,6}\s+(.+)$", re.MULTILINE)
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class FetchError(Exception):
    """The page could not be fetched or read; the message says why, for the person who asked."""


class Blocked(FetchError):
    """The URL points somewhere research does not go (the SSRF guard)."""


@dataclass
class Fetched:
    url: str
    status: int
    content_type: str
    body: bytes
    headers: dict
    charset: str = ""

    def text(self) -> str:
        return self.body.decode(self.charset or "utf-8", errors="replace")


@dataclass
class Extracted:
    text: str
    title: str = ""
    author: str = ""
    site_name: str = ""
    published: str = ""
    language: str = ""
    metadata: dict = field(default_factory=dict)


# ── the guard ──────────────────────────────────────────────────────────────


def resolve(host: str, port: int) -> list[str]:
    """Every address `host` resolves to (tests replace this, so they never touch DNS)."""
    return sorted({info[4][0] for info in socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)})


def public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%", 1)[0])
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def checked(url: str) -> tuple[str, int]:
    """(host, port) of an http(s) URL with no credentials in it, else `Blocked`."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise Blocked(f"only http and https URLs are fetched, not {url[:200]!r}")
    if parts.username or parts.password:
        raise Blocked("a URL with credentials in it is not fetched")
    try:
        return parts.hostname, parts.port or (443 if parts.scheme == "https" else 80)
    except ValueError as e:
        raise Blocked(f"{url[:200]!r} has no valid port") from e


def refuse_private_literal(url: str) -> None:
    """Refuse at once a URL whose host is a non-public address written out; a name is checked when it is fetched."""
    host, _ = checked(url)
    try:
        literal = public(host)
    except ValueError:
        return  # a name, resolved and checked by the worker
    if not literal:
        raise Blocked(f"{host} is not a public address; research fetches only the public web")


def pinned(url: str) -> tuple[str, str, str]:
    """(the URL with the checked address in place of the name, the `Host` header, the name for TLS)."""
    host, port = checked(url)
    try:
        addresses = resolve(host, port)
    except OSError as e:
        raise FetchError(f"{host} does not resolve") from e
    if not addresses:
        raise FetchError(f"{host} does not resolve")
    if not all(public(a) for a in addresses):
        raise Blocked(f"{host} is not a public address; research fetches only the public web")
    parts = urlsplit(url)
    address = f"[{addresses[0]}]" if ":" in addresses[0] else addresses[0]
    netloc = f"{address}:{parts.port}" if parts.port else address
    return urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, "")), parts.netloc, host


def get(url: str, *, headers: dict | None = None) -> Fetched:
    """GET `url` under the guard and the limits, following redirects; any HTTP status comes back.

    The whole exchange — every hop's connection, status line, headers and body — runs under one deadline,
    `RESEARCH_FETCH_TIMEOUT` seconds, by cancelling it (httpx's own timeouts bound each read, so a server sending a
    byte at a time would never trip them). Only resolving a name is outside it: that is bounded by the resolver."""
    limit = settings.RESEARCH_FETCH_TIMEOUT
    try:
        return asyncio.run(asyncio.wait_for(_get(url, headers or {}), limit))
    except TimeoutError as e:
        raise FetchError(f"the page took longer than {limit:g} seconds") from e
    except httpx.HTTPError as e:
        raise FetchError(f"could not fetch {url[:200]}: {e}") from e


def post(url: str, body: bytes, *, headers: dict | None = None) -> int:
    """POST `body` to `url` under the same guard and the same one deadline as `get`; the status it answered. No
    redirect is followed — a notification is never replayed somewhere else — and the answer's body is not read."""
    limit, host = settings.RESEARCH_FETCH_TIMEOUT, urlsplit(url).hostname or "the address"
    try:
        return asyncio.run(asyncio.wait_for(_post(url, body, headers or {}), limit))
    except TimeoutError as e:
        raise FetchError(f"{host} did not answer within {limit:g} seconds") from e
    except httpx.HTTPError as e:
        raise FetchError(f"{host} could not be reached: {type(e).__name__}") from e


def _client() -> httpx.AsyncClient:
    """No proxy from the environment and no redirect followed by httpx (`get` follows them by hand)."""
    return httpx.AsyncClient(
        trust_env=False, follow_redirects=False, timeout=httpx.Timeout(settings.RESEARCH_FETCH_TIMEOUT)
    )


async def _post(url: str, body: bytes, headers: dict) -> int:
    async with _client() as client:
        target, host, name = pinned(url)
        sent = {"User-Agent": settings.RESEARCH_USER_AGENT, **headers, "Host": host}
        async with client.stream(
            "POST", target, content=body, headers=sent, extensions={"sni_hostname": name}
        ) as reply:
            return reply.status_code


async def _get(url: str, headers: dict) -> Fetched:
    async with _client() as client:
        for _ in range(MAX_REDIRECTS + 1):
            target, host, name = pinned(url)
            sent = {"User-Agent": settings.RESEARCH_USER_AGENT, **headers, "Host": host}
            async with client.stream("GET", target, headers=sent, extensions={"sni_hostname": name}) as response:
                if response.has_redirect_location:
                    url = urljoin(url, response.headers["location"])
                    continue
                body = await _read(response)
                kind = response.headers.get("content-type", "")
                charset = response.charset_encoding or ""
                return Fetched(url, response.status_code, kind, body, dict(response.headers), charset)
    raise FetchError(f"more than {MAX_REDIRECTS} redirects")


async def _read(response) -> bytes:
    limit = settings.RESEARCH_MAX_BYTES
    if int(response.headers.get("content-length") or 0) > limit:
        raise FetchError(f"the page is larger than {limit} bytes")
    body = bytearray()
    async for chunk in response.aiter_bytes():
        body += chunk
        if len(body) > limit:
            raise FetchError(f"the page is larger than {limit} bytes")
    return bytes(body)


def robots_rules(url: str) -> RobotFileParser | None:
    """The robots.txt of `url`'s site, read through `get` (the guard), or None when there is none to read."""
    parts = urlsplit(url)
    try:
        found = get(urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", "")))
    except FetchError:
        return None
    if found.status != 200:
        return None
    parser = RobotFileParser()
    parser.parse(decode(found.body, found.charset).splitlines())
    return parser


def robots(url: str) -> str:
    """What the site's robots.txt says about our fetching `url`."""
    rules = robots_rules(url)
    if rules is None:
        return UNKNOWN
    return ALLOWED if rules.can_fetch(settings.RESEARCH_USER_AGENT, url) else DISALLOWED


# ── reading what came back ─────────────────────────────────────────────────


def extract(body: bytes, content_type: str = "", *, url: str = "", filename: str = "", charset: str = "") -> Extracted:
    """Text and metadata from a page, a PDF, or plain text or Markdown, without the control characters a database
    refuses (`clean`)."""
    kind = content_type.split(";", 1)[0].strip().lower()
    name = filename.lower()
    if kind == "application/pdf" or name.endswith(".pdf"):
        found = _pdf(body)
    elif kind in HTML_TYPES or name.endswith((".html", ".htm")):
        found = _html(body, url)
    elif kind.startswith("text/") or name.endswith((".txt", ".md", ".markdown")):
        found = _text(decode(body, charset))
    else:
        raise FetchError(f"{kind or name or 'this file'} is not a web page, a PDF or text")
    return Extracted(**clean(asdict(found)))


def clean(value):
    """A string — or the strings in a dict or a list — without NUL and the other control characters but tab and line
    breaks: Postgres keeps no NUL in text or JSON, and a page or a file can carry any byte."""
    if isinstance(value, str):
        return CONTROL.sub("", value)
    if isinstance(value, dict):
        return {key: clean(item) for key, item in value.items()}
    if isinstance(value, list):
        return [clean(item) for item in value]
    return value


def decode(body: bytes, charset: str = "") -> str:
    """Text from bytes: in the charset the server declared; else UTF-8 (a byte-order mark dropped); else what
    charset-normalizer reads in them — UTF-16 or UTF-32 by their mark or without one, a legacy code page."""
    if charset:
        try:
            return body.decode(charset, errors="replace")
        except LookupError:
            pass  # a charset Python does not know: read the bytes for what they are
    try:
        text = body.decode("utf-8-sig")
        if "\x00" not in text:  # UTF-16 without a mark is valid UTF-8, with a NUL beside every letter
            return text
    except UnicodeDecodeError:
        pass
    best = from_bytes(body).best()
    return str(best) if best is not None else body.decode("utf-8", errors="replace")


def _html(body: bytes, url: str) -> Extracted:
    from trafilatura import bare_extraction

    document = bare_extraction(body, url=url or None, with_metadata=True, include_comments=False)
    found = document.as_dict() if document is not None else {}
    if not (found.get("text") or "").strip():
        raise FetchError("the page has no readable text")
    keep = ("description", "hostname", "categories", "tags", "image")
    return Extracted(
        text=found["text"].strip(),
        title=found.get("title") or "",
        author=found.get("author") or "",
        site_name=found.get("sitename") or "",
        published=found.get("date") or "",
        language=found.get("language") or "",
        metadata={k: found[k] for k in keep if found.get(k)},
    )


def _pdf(body: bytes) -> Extracted:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(BytesIO(body))
        if reader.is_encrypted and not reader.decrypt(""):
            raise FetchError("the PDF is encrypted")
        pages = reader.pages
        text = "\n\n".join((page.extract_text() or "").strip() for page in pages[:MAX_PDF_PAGES])
        info = reader.metadata
    except PdfReadError as e:
        raise FetchError(f"not a PDF it can read: {e}") from e
    if not text.strip():
        raise FetchError("the PDF has no text to read (a scan needs OCR first)")
    return Extracted(
        text=text.strip(),
        title=str(info.title or "") if info else "",
        author=str(info.author or "") if info else "",
        metadata={"pages": len(pages)},
    )


def _text(text: str) -> Extracted:
    heading = HEADING.search(text)
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return Extracted(text=text.strip(), title=(heading.group(1) if heading else first)[:200].strip())


def plain(markup: str) -> str:
    """Text from a feed's HTML: tags dropped, entities read, blank runs collapsed."""
    return re.sub(r"\n{3,}", "\n\n", html.unescape(strip_tags(markup or ""))).strip()


def entries(body: bytes) -> tuple[str, list[dict]]:
    """A feed's title and its items (guid, url, title, author, published, text), newest as the feed orders them.

    feedparser is handed a stream, never the bytes themselves: given bytes or a string it first tries them as a
    file name (`open(body)`), so a feed whose body is a path would have the worker read its own disk."""
    parsed = feedparser.parse(BytesIO(body))
    if parsed.bozo and not parsed.entries:
        raise FetchError("not a feed it can read")
    items = []
    for entry in parsed.entries:
        content = entry.get("content") or []
        markup = content[0].get("value", "") if content else entry.get("summary", "")
        guid = entry.get("id") or entry.get("link") or entry.get("title") or ""
        items.append(
            {
                "guid": guid[:1000],
                "url": entry.get("link", ""),
                "title": plain(entry.get("title", ""))[:500],
                "author": entry.get("author", "")[:255],
                "published": (entry.get("published") or entry.get("updated") or "")[:40],
                "text": plain(markup),
            }
        )
    return clean(parsed.feed.get("title", "")), clean(items)
