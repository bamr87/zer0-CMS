"""The ways a chapter reaches Substack, behind one interface.

`SubstackAdapter.push(chapter, previous)` carries one chapter and returns where
it went (`Pushed`), or raises `SubstackError`; `finish()` runs once after a
sync (the feed writes its file there). `previous` is the ledger's entry for the
chapter's key, so an adapter can update what it made instead of making another.

* `FeedAdapter` — **sanctioned**. An RSS 2.0 feed of the book's *published*
  chapters, full text in `content:encoded`, each item's `guid` its canonical
  URL. Substack's post importer (Settings → Import/Export → Import posts) reads
  it; "Update existing posts" on a re-import updates instead of duplicating.
  Drafts are left out: Substack publishes what it imports.
* `CopyAdapter` — **sanctioned**. Per chapter, an `.html` (paste into the
  Substack editor) and a `.md` with the canonical URL on top: a person makes
  the draft; works for drafts and published chapters alike.
* `UnofficialApiAdapter` — **unofficial, off by default**. Substack's own
  undocumented web endpoints (`/api/v1/drafts`), authenticated by a session
  cookie the operator supplies through the environment. Refused unless
  `ZER0_SUBSTACK_UNOFFICIAL` is on; publishes only when the chapter is
  published *and* `ZER0_SUBSTACK_PUBLISH` is on, otherwise it leaves a draft.
  It may break or breach Substack's terms at any time (docs/SUBSTACK.md).
"""

import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from pathlib import Path
from typing import Protocol
from xml.sax.saxutils import escape

import httpx

from .chapters import Chapter


class SubstackError(Exception):
    """A push failed. `retryable`: trying again may work (a 429, a 5xx, a dropped connection). `doubt`: the write
    may have landed anyway, so the ledger marks the chapter unconfirmed and nothing resends it until a person
    checks. The message is safe to show and log: it never carries a credential."""

    def __init__(self, message: str, *, retryable: bool = False, doubt: bool = False):
        super().__init__(message)
        self.message, self.retryable, self.doubt = message, retryable, doubt


class Skipped(Exception):
    """Not an error: this adapter does not carry this chapter (a draft, for the feed)."""


@dataclass(frozen=True)
class Pushed:
    external_id: str
    url: str = ""
    state: str = "draft"  # what the chapter is on Substack now


class SubstackAdapter(Protocol):
    name: str
    sanctioned: bool

    def push(self, chapter: Chapter, previous: dict | None) -> Pushed: ...

    def finish(self) -> None: ...


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as out:
            out.write(text)
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


# ── Sanctioned: the importer's RSS feed ─────────────────────────────────────


class FeedAdapter:
    name, sanctioned = "feed", True

    def __init__(self, path, *, title: str, link: str, description: str = ""):
        self.path, self.title, self.link, self.description = Path(path), title, link, description
        self.items: list[Chapter] = []

    def push(self, chapter: Chapter, previous: dict | None) -> Pushed:
        if chapter.state != "published":
            raise Skipped("a draft is left out of the feed: Substack's importer publishes what it imports")
        self.items.append(chapter)
        return Pushed(external_id=chapter.canonical_url, url=chapter.canonical_url, state="feed")

    def finish(self) -> None:
        _atomic_write(self.path, self.render())

    def render(self) -> str:
        def item(c: Chapter) -> str:
            when = ""
            if c.published_at:
                try:
                    stamp = datetime.fromisoformat(c.published_at).replace(tzinfo=UTC)
                    when = f"<pubDate>{format_datetime(stamp)}</pubDate>"
                except ValueError:
                    when = ""
            body = c.html.replace("]]>", "]]]]><![CDATA[>")
            return (
                f"<item><title>{escape(c.title)}</title><link>{escape(c.canonical_url)}</link>"
                f'<guid isPermaLink="true">{escape(c.canonical_url)}</guid>{when}'
                f"<description>{escape(c.subtitle)}</description>"
                f"<content:encoded><![CDATA[{body}]]></content:encoded></item>"
            )

        items = "".join(item(c) for c in sorted(self.items, key=lambda c: c.number))
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">'
            f"<channel><title>{escape(self.title)}</title><link>{escape(self.link)}</link>"
            f"<description>{escape(self.description or self.title)}</description>{items}</channel></rss>\n"
        )


# ── Sanctioned: a copy package a person pastes ──────────────────────────────


class CopyAdapter:
    name, sanctioned = "copy", True

    def __init__(self, directory):
        self.directory = Path(directory)

    def push(self, chapter: Chapter, previous: dict | None) -> Pushed:
        stem = self.directory / chapter.series / f"ch{chapter.number:02d}"
        note = f"Canonical URL: {chapter.canonical_url}"
        head = f"<h1>{escape(chapter.title)}</h1>" + (
            f"<h3>{escape(chapter.subtitle)}</h3>" if chapter.subtitle else ""
        )
        _atomic_write(stem.with_suffix(".html"), f"<!-- {escape(note)} -->\n{head}\n{chapter.html}\n")
        sub = f"\n## {chapter.subtitle}\n" if chapter.subtitle else ""
        _atomic_write(stem.with_suffix(".md"), f"<!-- {note} -->\n# {chapter.title}\n{sub}\n{chapter.body_markdown}")
        return Pushed(external_id=str(stem.with_suffix(".html")), state="copy")

    def finish(self) -> None:
        return None


# ── Unofficial: Substack's undocumented web endpoints (off by default) ──────


def _doc(markdown_text: str) -> str:
    """The body as Substack's editor document: one paragraph per Markdown paragraph, text only — the editor's node
    schema is undocumented, so nothing richer is guessed at."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", markdown_text) if p.strip()]
    content = [{"type": "paragraph", "content": [{"type": "text", "text": p}]} for p in paragraphs]
    return json.dumps({"type": "doc", "content": content})


class UnofficialApiAdapter:
    name, sanctioned = "unofficial-api", False

    def __init__(self, *, publication_url: str, session_cookie: str, enabled: bool, publish: bool, client=None):
        if not enabled:
            raise SubstackError(
                "the unofficial Substack adapter is off: it uses Substack's undocumented endpoints — set "
                "ZER0_SUBSTACK_UNOFFICIAL=1 only after reading docs/SUBSTACK.md"
            )
        if not publication_url.startswith("https://"):
            raise SubstackError("SUBSTACK_PUBLICATION_URL must be the publication's https address")
        if not session_cookie:
            raise SubstackError("no Substack session: set SUBSTACK_SESSION_COOKIE in the environment")
        self.base, self.publish_allowed = publication_url.rstrip("/"), publish
        self._client = client or httpx.Client(timeout=20)
        self._headers = {"Cookie": f"substack.sid={session_cookie}", "Accept": "application/json"}

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        write = method != "GET"
        try:
            response = self._client.request(method, f"{self.base}/api/v1/{path}", json=body, headers=self._headers)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as e:
            raise SubstackError(f"Substack could not be reached ({type(e).__name__})", retryable=True) from e
        except httpx.HTTPError as e:
            raise SubstackError(f"Substack did not answer ({type(e).__name__})", retryable=True, doubt=write) from e
        status = response.status_code
        if 200 <= status < 300:
            try:
                data = response.json()
            except ValueError:
                data = {}
            return data if isinstance(data, dict) else {}
        if status in (401, 403):
            raise SubstackError(f"Substack refused the session ({status}): set a fresh SUBSTACK_SESSION_COOKIE")
        if status == 404:
            raise SubstackError(f"Substack has no {path} here (404): the undocumented endpoint may have changed")
        if status == 429:
            raise SubstackError("Substack is rate limiting (429)", retryable=True)
        if status >= 500:
            raise SubstackError(f"Substack failed ({status})", retryable=True, doubt=write)
        raise SubstackError(f"Substack refused the request ({status})")

    def push(self, chapter: Chapter, previous: dict | None) -> Pushed:
        body = {
            "draft_title": chapter.title,
            "draft_subtitle": chapter.subtitle,
            "draft_body": _doc(f"{chapter.body_markdown}\n\nOriginally published at {chapter.canonical_url}"),
            "type": "newsletter",
            "audience": "everyone",
        }
        draft_id = str((previous or {}).get("urn") or "")
        if draft_id and (previous or {}).get("substack_state") != "published":
            data = self._call("PUT", f"drafts/{draft_id}", body)
        elif draft_id:
            raise SubstackError(
                "this chapter is already published on Substack; edit it there (the adapter never rewrites a live post)"
            )
        else:
            data = self._call("POST", "drafts", body)
            draft_id = str(data.get("id") or "")
            if not draft_id:
                raise SubstackError("Substack answered without the draft's id", doubt=True)
        state = "draft"
        if chapter.state == "published" and self.publish_allowed:
            self._call("POST", f"drafts/{draft_id}/publish", {"send": False, "share_automatically": False})
            state = "published"
        slug = str(data.get("slug") or "")
        return Pushed(external_id=draft_id, url=f"{self.base}/p/{slug}" if slug else "", state=state)

    def finish(self) -> None:
        return None
