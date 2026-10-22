"""Fixtures for the research library's tests: the AI layer's people, scripted
provider, worker and API client (tests/ai/conftest.py); a resolver that answers
from a table, so no test touches DNS; recorded HTTP (respx) for every page,
robots.txt and feed, at the address the guard pins the connection to; a
provider that can search the web (a fake); and small documents — a page, a
PDF, a feed — made here rather than fetched. Nothing reaches a network or a
model."""

from decimal import Decimal

import pytest
import respx

from ai.providers.base import Completion, SearchResult
from ai.providers.fake import FakeProvider
from research import fetch
from tests.ai.conftest import alice, api, bob, fake, staff, worker  # noqa: F401 — shared fixtures

PUBLIC = "93.184.216.34"
DNS = {
    "example.com": [PUBLIC],
    "news.example.com": [PUBLIC],
    "intranet.example.com": ["10.0.0.5"],
    "sneaky.example.com": [PUBLIC, "127.0.0.1"],
}
PAGE = """<html lang="en"><head><title>Backups explained | Example News</title>
<meta name="author" content="Ada Lovelace"><meta property="og:site_name" content="Example News">
<meta property="article:published_time" content="2026-10-01T09:00:00Z"></head>
<body><nav>Home | About</nav><article><h1>Backups explained</h1>
<p>Most small websites lose data because nobody copies it anywhere. A nightly backup to a second disk costs almost
nothing and saves the day when the first disk fails.</p>
<p>In a 2025 survey, 40 percent of small site owners had never restored a backup. Testing restores matters as much as
taking backups.</p></article><footer>Copyright</footer></body></html>"""
FEED = """<?xml version="1.0"?><rss version="2.0"><channel><title>Example News</title>
<item><guid>a-1</guid><title>Backups, weekly</title><link>https://news.example.com/a-1</link>
<description>&lt;p&gt;Weekly backups are not enough.&lt;/p&gt;</description><pubDate>Mon, 19 Oct 2026 08:00:00 GMT</pubDate></item>
<item><guid>a-2</guid><title>Restores, tested</title><link>https://news.example.com/a-2</link>
<description>Test your restores.</description></item>
</channel></rss>"""


def at(path: str, scheme: str = "https") -> str:
    """The URL the guarded fetcher really requests: the checked address, not the name."""
    return f"{scheme}://{PUBLIC}{path}"


def tiny_pdf(text: str = "Backups save the day.", title: str = "Nightly Backups") -> bytes:
    """A one-page PDF with `text` on it and `title` in its information dictionary."""
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 400 144] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< /Title ({title}) /Author (Ada) >>".encode(),
    ]
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info 6 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


@pytest.fixture(autouse=True)
def table_dns(monkeypatch):
    """Names resolve from `DNS`; any other name does not resolve."""

    def resolve(host, port):
        if host in DNS:
            return DNS[host]
        try:
            fetch.ipaddress.ip_address(host)
        except ValueError:
            raise OSError(f"{host} does not resolve in the tests") from None
        return [host]

    monkeypatch.setattr(fetch, "resolve", resolve)


@pytest.fixture
def web():
    """Recorded HTTP: a request no route answers fails the test (respx's default)."""
    with respx.mock(assert_all_called=False) as router:
        yield router


@pytest.fixture
def site_web(web):
    """example.com with no robots.txt and the article page."""
    web.get(at("/robots.txt")).respond(404)
    web.get(at("/backups")).respond(200, text=PAGE, headers={"Content-Type": "text/html; charset=utf-8"})
    return web


class SearchingFake(FakeProvider):
    """The fake provider, able to search the web: it answers with `hits`."""

    capabilities = FakeProvider.capabilities | {"search"}

    def __init__(self, hits=(), **kwargs):
        super().__init__(**kwargs)
        self.hits, self.searches = list(hits), []

    def search(self, query, *, max_results=5):
        self.searches.append((query, max_results))
        cost = Decimal("0.0110")
        return Completion(data=self.hits[:max_results], tokens_in=40, tokens_out=10, cost_usd=cost, model="fake-1")


@pytest.fixture
def hits():
    return [
        SearchResult("https://example.com/backups", "Backups explained", "A nightly backup", "2026-10-01"),
        SearchResult("ftp://example.com/old", "Not the web"),
    ]
