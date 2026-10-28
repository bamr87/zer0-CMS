"""What AIEO reads in a document: its text, headers, tables, lists and links.

A port of `apps/aieo/backend/app/services/content_parser.py`. Markdown is
rendered with Python-Markdown (tables, fenced code, nl2br — the source's
extensions) and read with BeautifulSoup, so a Markdown document parses exactly
as it did in AIEO (`tests/aieo/test_analyzers.py`). HTML is read with
BeautifulSoup as it was, with one difference: AIEO counted the words of
html2text's Markdown rendering of the page, and html2text is GPL-licensed, so
here an HTML document's word and character counts are those of the text a
reader sees — a few words fewer than AIEO's on a typical page (no heading
markers, bullets or link targets).
"""

import hashlib

import markdown
from bs4 import BeautifulSoup

EXTENSIONS = ["tables", "fenced_code", "nl2br"]


def parse(content: str, format: str = "markdown") -> dict:
    """The parts of `content` the scorer reads (`format`: markdown or html)."""
    if format == "html":
        soup = BeautifulSoup(content, "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        counted = text
    else:
        soup = BeautifulSoup(markdown.Markdown(extensions=EXTENSIONS).convert(content), "html.parser")
        text = soup.get_text(separator=" ", strip=True)
        counted = content
    return {
        "text": text,
        "headers": headers(soup),
        "tables": tables(soup),
        "lists": lists(soup),
        "links": links(soup),
        "word_count": len(counted.split()),
        "char_count": len(counted),
        "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def headers(soup) -> list[dict]:
    found = []
    for level in range(1, 7):
        for header in soup.find_all(f"h{level}"):
            found.append({"level": level, "text": header.get_text(strip=True), "position": len(found)})
    return found


def tables(soup) -> list[dict]:
    found = []
    for table in soup.find_all("table"):
        rows = [
            cells
            for tr in table.find_all("tr")
            if (cells := [c.get_text(strip=True) for c in tr.find_all(["td", "th"])])
        ]
        if rows:
            found.append({"rows": rows, "column_count": max(len(row) for row in rows), "row_count": len(rows)})
    return found


def lists(soup) -> list[dict]:
    found = []
    for element in soup.find_all(["ul", "ol"]):
        items = [li.get_text(strip=True) for li in element.find_all("li")]
        if items:
            kind = "ordered" if element.name == "ol" else "unordered"
            found.append({"type": kind, "items": items, "item_count": len(items)})
    return found


def links(soup) -> list[dict]:
    return [{"text": a.get_text(strip=True), "url": a["href"]} for a in soup.find_all("a", href=True)]
