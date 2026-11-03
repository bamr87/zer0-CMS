"""Substack (distribution/substack/): the chapter loader over a book's files, the sanctioned feed and copy
adapters, the unofficial adapter recorded with respx (and refused while off), and the sync's idempotency, retries,
containment and unconfirmed ledgering. Nothing reaches Substack."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx
import pytest
import respx

from distribution.ledger import Ledger
from distribution.substack.adapters import (
    CopyAdapter,
    FeedAdapter,
    SubstackError,
    UnofficialApiAdapter,
)
from distribution.substack.chapters import load_book
from distribution.substack.sync import sync

PUB = "https://example.substack.com"
COOKIE = "sid-SECRET-abcdef"
BASE = "https://books.example.test"


@pytest.fixture
def book(tmp_path) -> Path:
    root = tmp_path / "cost-line"
    (root / "chapters").mkdir(parents=True)
    (root / "book.yml").write_text("slug: cost-line\ntitle: The Cost Line\n")
    (root / "chapters" / "ch01.md").write_text(
        "---\ntitle: Cash Flow Imperative\nnumber: 1\nstatus: published\ndate: 2026-11-01\n---\n\nThe tower hums.\n\nIt"
        " never noticed the fire.\n"
    )
    (root / "chapters" / "ch02.md").write_text(
        "---\ntitle: Moving Mountains\nnumber: 2\nstatus: outline\n---\n\nLater.\n"
    )
    return root


def chapters(book):
    return load_book(book, canonical_base=BASE)


def test_loader_maps_status_and_canonical_url(book):
    one, two = chapters(book)
    assert (one.state, two.state) == ("published", "draft")
    assert one.canonical_url == f"{BASE}/cost-line/ch01/"
    assert one.series_title == "The Cost Line" and "<p>The tower hums.</p>" in one.html


def test_loader_needs_a_stable_key(book):
    with pytest.raises(ValueError, match="canonical"):
        load_book(book, canonical_base="")


def test_the_feed_carries_published_chapters_keyed_by_canonical_url(book, tmp_path):
    feed = FeedAdapter(tmp_path / "feed.xml", title="The Cost Line", link=BASE)
    report = sync(chapters(book), feed, Ledger(tmp_path / "ledger.json"))
    assert report.ok and report.counts() == {"sent": 1, "skipped": 1}
    items = ET.parse(tmp_path / "feed.xml").getroot().findall("./channel/item")
    assert [i.findtext("guid") for i in items] == [f"{BASE}/cost-line/ch01/"]
    assert "never noticed" in items[0].findtext("{http://purl.org/rss/1.0/modules/content/}encoded")
    again = sync(
        chapters(book), FeedAdapter(tmp_path / "feed.xml", title="t", link=BASE), Ledger(tmp_path / "ledger.json")
    )
    assert again.counts()["sent"] == 1  # the feed is always the whole set
    assert len(ET.parse(tmp_path / "feed.xml").getroot().findall("./channel/item")) == 1


def test_the_copy_package_is_idempotent(book, tmp_path):
    ledger = Ledger(tmp_path / "ledger.json")
    assert sync(chapters(book), CopyAdapter(tmp_path / "copy"), ledger).counts() == {"sent": 2}
    assert "Canonical URL" in (tmp_path / "copy" / "cost-line" / "ch01.md").read_text()
    assert sync(chapters(book), CopyAdapter(tmp_path / "copy"), ledger).counts() == {"unchanged": 2}
    (book / "chapters" / "ch02.md").write_text("---\ntitle: Moving Mountains\nnumber: 2\n---\n\nRewritten.\n")
    assert sync(chapters(book), CopyAdapter(tmp_path / "copy"), ledger).counts() == {"unchanged": 1, "sent": 1}


def test_the_unofficial_adapter_is_off_by_default():
    with pytest.raises(SubstackError, match="off"):
        UnofficialApiAdapter(publication_url=PUB, session_cookie=COOKIE, enabled=False, publish=False)


def unofficial(publish=False):
    return UnofficialApiAdapter(
        publication_url=PUB, session_cookie=COOKIE, enabled=True, publish=publish, client=httpx.Client()
    )


@respx.mock
def test_unofficial_drafts_then_updates_and_never_publishes_unarmed(book, tmp_path):
    create2 = respx.post(f"{PUB}/api/v1/drafts").mock(
        side_effect=[httpx.Response(200, json={"id": 7}), httpx.Response(200, json={"id": 8})]
    )
    ledger = Ledger(tmp_path / "ledger.json")
    report = sync(chapters(book), unofficial(), ledger)
    assert report.ok and create2.call_count == 2
    assert ledger.entry(f"{BASE}/cost-line/ch01/")["substack_state"] == "draft"
    assert COOKIE not in (tmp_path / "ledger.json").read_text()
    update = respx.put(f"{PUB}/api/v1/drafts/8").mock(return_value=httpx.Response(200, json={"id": 8}))
    (book / "chapters" / "ch02.md").write_text("---\ntitle: Moving Mountains\nnumber: 2\n---\n\nRewritten.\n")
    assert sync(chapters(book), unofficial(), ledger).counts() == {"unchanged": 1, "sent": 1}
    assert update.called


@respx.mock
def test_unofficial_publishes_only_when_armed(book, tmp_path):
    respx.post(f"{PUB}/api/v1/drafts").mock(return_value=httpx.Response(200, json={"id": 9}))
    publish = respx.post(f"{PUB}/api/v1/drafts/9/publish").mock(return_value=httpx.Response(200, json={}))
    ledger = Ledger(tmp_path / "ledger.json")
    sync(chapters(book)[:1], unofficial(publish=True), ledger)
    assert publish.call_count == 1 and json.loads(publish.calls[0].request.content)["send"] is False
    assert ledger.entry(f"{BASE}/cost-line/ch01/")["substack_state"] == "published"


@respx.mock
def test_retryable_failures_are_retried_with_backoff(book, tmp_path):
    respx.post(f"{PUB}/api/v1/drafts").mock(
        side_effect=[httpx.Response(429), httpx.ConnectError("down"), httpx.Response(200, json={"id": 1})]
    )
    waits = []
    report = sync(chapters(book)[:1], unofficial(), Ledger(tmp_path / "l.json"), sleep=waits.append, backoff=1)
    assert report.ok and waits == [1, 2]


@respx.mock
def test_a_doubtful_write_is_ledgered_unconfirmed_and_blocks_until_forced(book, tmp_path):
    route = respx.post(f"{PUB}/api/v1/drafts").mock(return_value=httpx.Response(502))
    ledger = Ledger(tmp_path / "l.json")
    report = sync(chapters(book), unofficial(), ledger, sleep=lambda s: None)
    assert [o.status for o in report.outcomes] == ["unconfirmed", "unconfirmed"]  # contained: both tried
    assert route.call_count == 2  # a doubtful write is never retried
    assert ledger.unconfirmed(f"{BASE}/cost-line/ch01/")
    assert {o.status for o in sync(chapters(book), unofficial(), ledger).outcomes} == {"blocked"}
    route.mock(return_value=httpx.Response(200, json={"id": 3}))
    assert sync(chapters(book), unofficial(), ledger, force=True).ok


@respx.mock
def test_an_expired_session_fails_without_retry_or_leaking_it(book, tmp_path):
    route = respx.post(f"{PUB}/api/v1/drafts").mock(return_value=httpx.Response(401))
    report = sync(chapters(book)[:1], unofficial(), Ledger(tmp_path / "l.json"), sleep=lambda s: None)
    assert report.outcomes[0].status == "failed" and route.call_count == 1
    assert COOKIE not in report.outcomes[0].detail and "SUBSTACK_SESSION_COOKIE" in report.outcomes[0].detail


def test_the_real_library_loads(settings):
    root = Path(__file__).resolve().parents[3] / "packages" / "books" / "library"
    for book_dir in (p for p in root.iterdir() if (p / "book.yml").is_file() and (p / "chapters").is_dir()):
        assert all(c.canonical_url.startswith(BASE) for c in load_book(book_dir, canonical_base=BASE))
