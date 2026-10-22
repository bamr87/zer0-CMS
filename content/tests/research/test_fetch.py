"""The guarded fetcher (research/fetch.py): http(s) only; a name that resolves
to a private, loopback or link-local address — or a redirect to one — is
refused before any connection; the connection goes to the address that was
checked, with the name in `Host` and in TLS SNI; a body over the limit is
refused; robots.txt is read; and pages, PDFs, text and feeds are extracted
from bytes. Every request is recorded (respx) and every name resolves from a
table: nothing reaches a network."""

import pytest
from django.test import override_settings

from research import fetch

from .conftest import FEED, PAGE, at, tiny_pdf


@pytest.mark.parametrize(
    "url",
    [
        "http://intranet.example.com/admin",
        "http://sneaky.example.com/",
        "http://127.0.0.1:8000/admin/",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::ffff:10.0.0.1]/",
        "file:///etc/passwd",
        "gopher://example.com/",
        "http://user:secret@example.com/",
    ],
)
def test_a_url_that_leads_off_the_public_web_is_refused_before_any_request(url, web):
    with pytest.raises(fetch.Blocked):
        fetch.get(url)
    assert web.calls.call_count == 0


def test_an_address_written_out_is_refused_at_once_and_a_name_is_left_to_the_worker():
    for url in ("http://127.0.0.1/", "http://10.1.2.3/x", "http://[fe80::1]/"):
        with pytest.raises(fetch.Blocked):
            fetch.refuse_private_literal(url)
    fetch.refuse_private_literal("https://example.com/backups")  # resolved and checked when it is fetched
    fetch.refuse_private_literal("https://93.184.216.34/")


def test_the_connection_goes_to_the_checked_address_with_the_name_in_host_and_sni(web):
    route = web.get(at("/backups?page=2")).respond(200, text="ok", headers={"Content-Type": "text/plain"})
    got = fetch.get("https://example.com/backups?page=2#top")
    sent = route.calls.last.request
    assert got.status == 200 and got.body == b"ok" and got.url == "https://example.com/backups?page=2#top"
    assert sent.headers["host"] == "example.com" and sent.extensions["sni_hostname"] == "example.com"
    assert sent.headers["user-agent"].startswith("zer0-cms-research/")


def test_redirects_are_followed_and_every_hop_is_checked_again(web):
    web.get(at("/old")).respond(301, headers={"Location": "/new"})
    web.get(at("/new")).respond(200, text="moved")
    assert fetch.get("https://example.com/old").body == b"moved"
    web.get(at("/out")).respond(302, headers={"Location": "http://intranet.example.com/secrets"})
    with pytest.raises(fetch.Blocked, match="not a public address"):
        fetch.get("https://example.com/out")
    web.get(at("/loop")).respond(302, headers={"Location": "/loop"})
    with pytest.raises(fetch.FetchError, match="more than 5 redirects"):
        fetch.get("https://example.com/loop")


@override_settings(RESEARCH_MAX_BYTES=100)
def test_a_body_over_the_limit_is_refused(web):
    web.get(at("/big")).respond(200, content=b"x" * 101)
    web.get(at("/said-big")).respond(200, content=b"x", headers={"Content-Length": "5000"})
    for path in ("/big", "/said-big"):
        with pytest.raises(fetch.FetchError, match="larger than 100 bytes"):
            fetch.get(f"https://example.com{path}")


def test_robots_txt_is_asked(web):
    robots = "User-agent: zer0-cms-research\nDisallow: /private\n\nUser-agent: *\nDisallow: /\n"
    web.get(at("/robots.txt")).respond(200, text=robots)
    assert fetch.robots("https://example.com/private/x") == fetch.DISALLOWED
    assert fetch.robots("https://example.com/public") == fetch.ALLOWED
    web.get(at("/robots.txt", "http")).respond(404)
    assert fetch.robots("http://example.com/anything") == fetch.UNKNOWN


def test_a_page_a_pdf_and_text_are_extracted_with_their_metadata():
    page = fetch.extract(PAGE.encode(), "text/html; charset=utf-8", url="https://example.com/backups")
    assert page.title == "Backups explained" and page.author == "Ada Lovelace" and page.site_name == "Example News"
    assert page.published == "2026-10-01" and "A nightly backup" in page.text and "Copyright" not in page.text
    pdf = fetch.extract(tiny_pdf(), "application/pdf")
    assert pdf.text == "Backups save the day." and pdf.title == "Nightly Backups" and pdf.metadata == {"pages": 1}
    notes = fetch.extract(b"Intro line\n\n# Backups, a guide\n\nKeep two copies.", filename="guide.md")
    assert notes.title == "Backups, a guide" and notes.text.endswith("Keep two copies.")
    assert fetch.extract(b"First line\nsecond", "text/plain").title == "First line"
    for body, kind in (
        (b"\x89PNG....", "image/png"),
        (b"not a pdf", "application/pdf"),
        (b"<html></html>", "text/html"),
    ):
        with pytest.raises(fetch.FetchError):
            fetch.extract(body, kind)


def test_text_is_read_in_its_own_encoding_and_kept_free_of_control_characters():
    words = "Back up nightly.\nKeep two copies."
    for body in (words.encode("utf-16"), words.encode("utf-16-le"), words.encode("utf-32"), words.encode("utf-8-sig")):
        assert fetch.extract(body, filename="notes.txt").text == words  # Notepad's "Unicode" is UTF-16 with a mark
    assert fetch.extract("Café".encode("latin-1"), "text/plain", charset="latin-1").text == "Café"
    assert fetch.extract(b"Caf\xc3\xa9", "text/plain", charset="no-such-charset").text == "Café"
    noisy = fetch.extract(b"Back\x00 up\x07 nightly.\tKeep\r\ntwo\x1b copies.", "text/plain")
    assert noisy.text == "Back up nightly.\tKeep\r\ntwo copies." and noisy.title == "Back up nightly.\tKeep"
    assert fetch.clean({"tags": ["a\x00b"], "pages": 2}) == {"tags": ["ab"], "pages": 2}


def test_a_feed_is_read_into_items_with_plain_text():
    title, items = fetch.entries(FEED.encode())
    assert title == "Example News" and [i["guid"] for i in items] == ["a-1", "a-2"]
    assert items[0] == {
        "guid": "a-1",
        "url": "https://news.example.com/a-1",
        "title": "Backups, weekly",
        "author": "",
        "published": "Mon, 19 Oct 2026 08:00:00 GMT",
        "text": "Weekly backups are not enough.",
    }
    with pytest.raises(fetch.FetchError, match="not a feed"):
        fetch.entries(b"\x00\x01 binary nonsense")


def test_a_feed_body_that_names_a_file_is_read_as_text_never_opened(tmp_path):
    local = tmp_path / "worker-feed.xml"
    local.write_text(FEED.replace("Example News", "A FILE ON THE WORKER"))
    for body in (str(local).encode(), bytes(local)):
        with pytest.raises(fetch.FetchError, match="not a feed"):
            fetch.entries(body)  # the bytes are the feed: a path in them is text, not a file to open
