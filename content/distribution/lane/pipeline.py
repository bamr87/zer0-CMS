"""The governed path from a site's page to a LinkedIn post, over the site's own
files — what a content repository's CI (`zer0-linkedin.yml`) and a terminal run
through `manage.py linkedin`:

    page ──▶ draft (pending) ──▶ approve ──▶ preview ──▶ publish ──▶ ledger ──▶ statistics
                                  a person   no network   gated      keyed by URL

`preview` is pure: it reads files and computes, with no network call and no
write, and what a reviewer sees — the exact payload, the guard's findings,
every blocker — is what `publish` sends. `publish` re-reads the draft, rebuilds
the preview and refuses on any blocker in `gates.ORDER`. A live publish needs
`ZER0_LINKEDIN_PUBLISH=1`, which no file and no flag can set; without `live` it
is a rehearsal. The platform's queue (`distribution.services`) runs the same
gates, the same client and the same publish step over its own rows.

A queue run — `publish` with no draft named, which is what CI runs — follows
the site's cadence when it has one (`distribution/cadence.py`, issue #89): it
releases at most one draft, and only while a slot is open, and a draft waits
for its `publish_at:` and for its page to have been live `afterPage`. Without a
cadence a queue run publishes every accepted draft, as before, except one
pinned to a later `publish_at:`. A person's publish of one named draft is never
held. `calendar` shows which draft goes when.

Before a live send of an article, the lane asks the page itself whether it is
up — one GET of the link it shares (`checkLink`, on by default) — so a share
never points at a page that is not live yet: a queue run leaves the draft
waiting, a named publish is refused. The card image is the draft's own
`image:`, else the page's preview, else the site's `fallbackImage`; with
`requirePreview` a share with no image of its own is refused instead.
"""

import itertools
import json
import re
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx

from suggestions.guard import guard_text

from .. import cadence as cadences
from .. import gates
from ..gates import Blocker
from ..ledger import Ledger, LedgerError, entry_for, stamp, unconfirmed_entry, urn_of
from ..linkedin import Error, HTTPError, oauth, plan, posts, statistics
from ..linkedin.client import send
from ..linkedin.session import Session, send_post
from ..permalink import path_for
from . import drafts as queue
from .site import DATED, ConfigError, catalog, default_commentary, read_jsonc, slug

NOTE = "Aggregate statistics for the author's own content. No per-reader data."


@dataclass
class Source:
    entry: object
    url: str
    urn: str | None
    id_key: str = "linkedin_urn"  # what the lane calls a post's id: the X lane's is `post_id`

    def as_dict(self) -> dict:
        e = self.entry
        return {
            "path": e.relative,
            "collection": e.collection,
            "title": e.title,
            "date": e.date_raw,
            "url": self.url,
            self.id_key: self.urn,
        }


@dataclass
class Preview:
    draft: queue.Draft
    kind: str
    key: str | None
    entry: object
    commentary: str
    payload: dict | None
    thumbnail: Path | None
    notes: list
    guard: list
    blockers: list

    @property
    def problems(self) -> list:
        return gates.problems(self.blockers)

    def as_dict(self, root: Path) -> dict:
        return {
            "draft": self.draft.relative,
            "status": self.draft.status,
            "type": self.kind,
            "key": self.key,
            "source": self.entry.relative if self.entry else None,
            "commentary": self.commentary,
            "commentary_length": posts.commentary_length(self.commentary),
            "fold": 140,
            "payload": self.payload,
            "thumbnail": self.thumbnail.relative_to(root).as_posix() if self.thumbnail else None,
            "notes": self.notes,
            "guard": self.guard,
            "blockers": [b.as_dict() for b in self.blockers],
        }


@dataclass
class Outcome:
    state: str  # published, skipped, rehearsed, approved, recorded, waiting (its slot is later), blocked, failed
    draft: queue.Draft | None
    key: str | None = None
    urn: str | None = None
    messages: list = field(default_factory=list)
    preview: Preview | None = None
    id_key: str = "linkedin_urn"

    @property
    def ok(self) -> bool:
        return self.state in ("published", "skipped", "rehearsed", "approved", "recorded", "waiting")

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "draft": self.draft.relative if self.draft else None,
            "key": self.key,
            self.id_key: self.urn,
            "messages": self.messages,
        }


@dataclass
class Planned:
    """A draft's place in the release calendar: the earliest it may go, whether a person pinned that, the time the
    cadence gives it (`at`, None when it finds none, with `reason`), and a problem that keeps it out."""

    draft: queue.Draft
    not_before: datetime | None = None
    pinned: bool = False
    problem: str = ""
    order: int = 0
    at: datetime | None = None
    reason: str = ""

    def ready(self, now) -> bool:
        return not self.problem and (self.not_before is None or self.not_before <= now)

    def describe(self, cadence, now) -> str:
        show = cadence.show if cadence else (lambda t: t.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC"))
        if self.at is None:
            return f"waiting: {self.reason or 'no time found'}"
        if self.at <= now:
            return "waiting: the slot open now went to a draft ahead of it" if cadence else "ready"
        why = "its publish_at" if self.pinned and self.not_before == self.at else "its slot"
        return f"waiting for {why}: {show(self.at)}"

    def as_dict(self) -> dict:
        return {
            "id": self.draft.id,
            "path": self.draft.relative,
            "status": self.draft.status,
            "type": self.draft.type,
            "source": self.draft.text("source"),
            "not_before": _iso(self.not_before),
            "pinned": self.pinned,
            "at": _iso(self.at),
            "reason": self.reason,
            "problem": self.problem,
        }


def _iso(at: datetime | None) -> str | None:
    return at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if at else None


def _instant(raw) -> datetime | None:
    """A ledger stamp or a git date as an aware UTC time; None for anything else."""
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00") if text.endswith("Z") else text)
    except ValueError:
        return None
    return (when if when.tzinfo else when.replace(tzinfo=UTC)).astimezone(UTC)


def banned_patterns(config) -> list:
    """`[{"name", "pattern", "flags"}]` — the extension's banned-patterns file. A broken one adds nothing, so the
    built-in bans still run."""
    if not config.banned_patterns_file:
        return []
    try:
        raw = read_jsonc(config.path(config.banned_patterns_file))
        out = []
        for entry in raw:
            flags = str(entry.get("flags", "i"))
            compiled = re.compile(entry["pattern"], (re.I if "i" in flags else 0) | (re.M if "m" in flags else 0))
            out.append((str(entry["name"]), compiled))
        return out
    except (OSError, ValueError, TypeError, KeyError, AttributeError, re.error):
        return []


def check_commentary(text: str, extra) -> list[dict]:
    """The brand guard (suggestions/guard.py, the extension's rules), plus LinkedIn's own limit once escaped."""
    findings = guard_text(text, extra)
    escaped = posts.commentary_length(text)
    if escaped > plan.COMMENTARY_MAX and len(text) <= 3000:
        message = f"commentary is {escaped} chars once escaped for LinkedIn (max {plan.COMMENTARY_MAX})"
        findings.insert(len(findings) - 1, {"level": "error", "message": message})
    return findings


class Pipeline:
    # The target's name in messages, the command a person runs, the draft key a published post's id goes under, and
    # the errors a publish turns into a failed outcome; the X lane's pipeline (`x_pipeline.XPipeline`) names its own.
    NAME, COMMAND, ID_KEY = "LinkedIn", "linkedin", "linkedin_urn"
    ERRORS = (Error, ConfigError, LedgerError, ValueError)

    def __init__(
        self,
        config,
        *,
        transport=send,
        sleeper=time.sleep,
        clock=None,
        credentials=None,
        page_check: Callable[[str], int | None] | None = None,
    ):
        self.config = config
        self.transport = transport
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(UTC))
        self.credentials = credentials or config.credentials
        self.page_check = page_check or page_status
        self._catalog = None

    @property
    def catalog(self):
        if self._catalog is None:
            self._catalog = catalog(self.config.root, now=self.clock())
        return self._catalog

    @property
    def ledger(self) -> Ledger:
        return Ledger(self.config.path(self.config.ledger))

    def drafts(self) -> list[queue.Draft]:
        return queue.all_drafts(self.config)

    def draft(self, ref) -> queue.Draft:
        return queue.find_required(self.config, ref)

    # ── what can be shared ───────────────────────────────────────────────────
    def canonical_url(self, entry) -> str | None:
        if not self.config.site_url:
            return None
        path = path_for(self.catalog.config, entry)
        return f"{self.config.site_url}{path}" if path else None

    def shareable(self, entry) -> bool:
        structural = slug_stem(entry.source_relative) == "index"
        in_sources = not self.config.sources or entry.collection in self.config.sources
        return (
            entry.live
            and not structural
            and in_sources
            and bool(entry.title.strip())
            and bool(entry.description.strip())
        )

    def sources(self) -> list[Source]:
        """Live content with a title, a description and a public URL, in the configured collections — each with
        the post URN if it was shared."""
        out = []
        for entry in sorted(self.catalog.entries, key=_newest_first):
            if self.shareable(entry) and (url := self.canonical_url(entry)):
                out.append(Source(entry, url, self.ledger.urn_for(url), self.ID_KEY))
        return out

    def resolve_source(self, ref):
        """A page by repository path, source path, `section/YYYY-MM-DD-slug` suffix, or a slug naming one page."""
        wanted = str(ref or "").strip().removeprefix("./").removeprefix("/")
        if not wanted or re.match(r"[a-z][a-z0-9+.-]*://", wanted, re.I):
            return None
        target = _stem(wanted)
        entries = self.catalog.entries
        for entry in entries:
            if wanted in (entry.relative, entry.source_relative) or target in (
                _stem(entry.relative),
                _stem(entry.source_relative),
            ):
                return entry
        suffix = [e for e in entries if _stem(e.source_relative).endswith("/" + target)]
        if len(suffix) == 1:
            return suffix[0]

        def undated(path):
            return DATED.sub("", PurePosixPath(path).name, count=1)

        by_slug = [e for e in entries if undated(_stem(e.source_relative)) == undated(target)]
        return by_slug[0] if len(by_slug) == 1 else None

    # ── drafting and approving ───────────────────────────────────────────────
    def compose(self, ref, commentary=None) -> queue.Draft:
        entry = self.resolve_source(ref)
        if entry is None:
            raise ValueError(f"no page on this site matches {ref!r}")
        if not entry.live:
            raise ValueError(f"{entry.relative} is not live content (draft, unpublished or future)")
        url = self.canonical_url(entry)
        if not url:
            raise ValueError(f"{entry.relative} has no public URL — set the site URL")
        if urn := self.ledger.urn_for(url):
            raise ValueError(f"{entry.relative} was already shared as {urn}")
        body = commentary if str(commentary or "").strip() else default_commentary(entry, self.config.hashtag_limit)
        name = f"{self.clock():%Y-%m-%d}-{slug(entry.source_relative)}"
        meta = {"source": entry.relative, "title": entry.title, "url": url}
        return queue.create(self.config, type="article", slug=name, body=body, meta=meta)

    def compose_update(self, message, *, slug: str) -> queue.Draft:
        return queue.create(self.config, type="update", slug=f"{self.clock():%Y-%m-%d}-{slug}", body=message)

    def approve(self, draft) -> Outcome:
        """pending → approved: a person's decision. The guard's errors block it."""
        draft = queue.read(self.config, draft.path)
        if draft.status != "pending":
            return Outcome("blocked", draft, messages=[f"draft is already {draft.status}"])
        findings = guard_text(draft.commentary, banned_patterns(self.config))
        errors = [f["message"] for f in findings if f["level"] == "error"]
        if errors:
            return Outcome("blocked", draft, messages=[f"brand guard: {'; '.join(errors)}"])
        queue.set_status(draft, "approved")
        return Outcome("approved", queue.read(self.config, draft.path), messages=[f"approved {draft.relative}"])

    # ── preview: the exact artifact, no network, no writes ──────────────────
    def preview(self, draft) -> Preview:
        config = self.config
        blockers = [Blocker("config_error", m) for m in config.errors]
        notes: list[str] = []
        author = config.author
        author_ok = plan.author_type(author) is not None
        if not author_ok:
            message = (
                "no LinkedIn author configured (distribution.linkedin.author)"
                if not author
                else (f"author is not a person or organization URN: {author}")
            )
            blockers.append(Blocker("no_author", message))
        commentary, entry, key, payload, thumbnail = draft.commentary, None, None, None, None
        if draft.type == "update":
            key = f"draft:{draft.relative}"
            if not commentary:
                blockers.append(Blocker("source_missing", "an update needs a body"))
            elif author_ok:
                payload = posts.text_payload(author=author, commentary=commentary)
        elif draft.type == "article":
            source = draft.text("source")
            entry = self.resolve_source(source) if source else None
            url = (self.canonical_url(entry) if entry else None) or draft.text("link") or None
            title = entry.title if entry else draft.text("title")
            description = entry.description if entry else draft.text("description")
            if source and entry is None:
                blockers.append(Blocker("source_missing", f"source {source} does not match a page on this site"))
            elif url is None:
                message = (
                    f"{entry.relative} has no public URL — set the site URL"
                    if entry
                    else ("an article needs a source page or a link")
                )
                blockers.append(Blocker("source_missing", message))
            elif not title.strip() or not description.strip():
                blockers.append(Blocker("source_missing", "the link card needs a title and a description"))
            if not commentary and entry:
                commentary = default_commentary(entry, config.hashtag_limit)
                notes.append("the draft has no body; the page's default commentary will publish")
            if not draft.no_thumbnail:
                thumbnail = self._thumbnail(entry, notes, draft)
                if self.config.require_preview and (thumbnail is None or self._fell_back(thumbnail)):
                    blockers.append(
                        Blocker(
                            "source_missing",
                            "no card image of its own (requirePreview): generate the page's preview image, or name "
                            "one with image: on the draft",
                        )
                    )
            key = url
            if feature := draft.text("feature"):
                # The week's featured article is its own post: ledgered by the week, so the page may also have its
                # share and a week never features twice.
                if not queue.WEEK.match(feature):
                    blockers.append(Blocker("source_missing", f'feature is a week, YYYY-Www, got "{feature}"'))
                key = f"feature:{feature}"
            if author_ok and url and title.strip():
                try:
                    payload = posts.article_payload(
                        author=author, commentary=commentary, source=url, title=title, description=description
                    )
                except ValueError as e:
                    blockers.append(Blocker("source_missing", str(e)))
        elif draft.type == "revision":
            # A correction or a reference added to a post already out: its text changes, its card cannot.
            target = draft.text("revises")
            key = f"draft:{draft.relative}"
            own = {e.get("urn") for _, e in self.ledger.shares()} if self.ledger.readable else set()
            if not plan.POST_URN.match(target):
                blockers.append(
                    Blocker("source_missing", "a revision names the post it revises: revises: urn:li:share:…")
                )
            elif target not in own:
                blockers.append(
                    Blocker(
                        "source_missing",
                        f"{target} is not a post this lane published ({config.ledger}): a revision edits only the "
                        "author's own posts",
                    )
                )
            if not commentary:
                blockers.append(Blocker("source_missing", "a revision needs the post's new text as its body"))
            elif author_ok:
                payload = posts.update_payload(commentary=commentary)
        else:
            blockers.append(
                Blocker("source_missing", f'unknown draft type "{draft.type}" (article, update or revision)')
            )

        guard = check_commentary(commentary, banned_patterns(config))
        errors = [f["message"] for f in guard if f["level"] == "error"]
        if errors:
            blockers.append(Blocker("guard_error", f"brand guard: {'; '.join(errors)}"))
        self._gates(draft, key, blockers)
        return Preview(
            draft, draft.type, key, entry, commentary, payload, thumbnail, notes, guard, gates.ordered(blockers)
        )

    # Where a person looks for a post that may exist, and what they record it by: the X lane names its own.
    POSTS_WHERE, ID_WORD = "author's LinkedIn posts", "URN"

    def credential_missing(self) -> str | None:
        if self.credentials.access or self.credentials.refreshable:
            return None
        return "no LinkedIn credential (LINKEDIN_ACCESS_TOKEN, or a refresh token with the app credentials)"

    def _gates(self, draft, key, blockers):
        """The blockers every lane checks the same way after its target's own: the ledger, approval, arming and the
        credential."""
        config = self.config
        ledger = self.ledger
        if not ledger.readable:
            blockers.append(
                Blocker("ledger_unreadable", f"{config.ledger} is not valid JSON — fix it before publishing")
            )
        elif key and (urn := ledger.urn_for(key)):
            blockers.append(Blocker("already_published", f"already published as {urn}"))
        elif key and (attempt := ledger.unconfirmed(key)):
            blockers.append(
                Blocker(
                    "publish_unconfirmed",
                    (
                        f"an attempt on {attempt.get('attempted_at')} may have posted this ({attempt.get('error')}): check the "
                        f"{self.POSTS_WHERE}, then run `manage.py {self.COMMAND} record {draft.id} {self.ID_WORD}` if it did, "
                        "or publish it with --force if it did not"
                    ),
                )
            )
        accepted = config.publishable_statuses
        if draft.status == "published":
            blockers.append(Blocker("status_not_accepted", "draft is already published"))
        elif draft.status == "pending" and "pending" in config.accept_statuses and "pending" not in accepted:
            blockers.append(
                Blocker(
                    "status_not_accepted",
                    (
                        f"draft is pending: this site publishes a pending draft only once it is merged ({config.MERGED}=1, "
                        "set by the workflow on the default branch); approve it to publish here"
                    ),
                )
            )
        elif draft.status not in accepted:
            blockers.append(
                Blocker(
                    "status_not_accepted",
                    f"draft status is {draft.status} (accepted here: {', '.join(accepted) or 'none'})",
                )
            )
        if not config.publish_armed:
            blockers.append(
                Blocker(
                    "publish_disabled", f"publishing is not armed ({config.ARM}=1 in the environment, and a live run)"
                )
            )
        if missing := self.credential_missing():
            blockers.append(Blocker("no_credential", missing))

    # ── publish ──────────────────────────────────────────────────────────────
    def publish(self, draft, *, live=False, force=False, queued=False) -> Outcome:
        """Without `live`, a rehearsal: the full preview and its blockers, nothing sent, nothing written. A live
        article asks its page first (`checkLink`): one that is not up yet is `waiting` in a queue run (`queued`) and
        `blocked` for a person's publish of the named draft."""
        draft = queue.read(self.config, draft.path)
        preview = self.preview(draft)
        blockers = gates.lifted(preview.blockers, force=force)
        if not live:
            state = "blocked" if gates.problems(blockers) else "rehearsed"
            return Outcome(state, draft, preview.key, messages=[b.message for b in blockers], preview=preview)
        # The post went out on an earlier run but the draft never learned it (the run died between the ledger and
        # the file): finish that run instead of posting again.
        if [b.kind for b in blockers] == ["already_published"] and draft.status in self.config.publishable_statuses:
            urn = self.ledger.urn_for(preview.key)
            queue.set_status(draft, "published", {self.ID_KEY: urn})
            return Outcome(
                "skipped",
                draft,
                preview.key,
                urn,
                [f"already published as {urn}; marked {draft.relative} published"],
                preview,
            )
        if blockers:
            return Outcome("blocked", draft, preview.key, messages=[b.message for b in blockers], preview=preview)
        if (down := self.page_down(draft, self.link_of(preview))) is not None:
            return Outcome("waiting" if queued else "blocked", draft, preview.key, messages=[down], preview=preview)
        try:
            return self._send(draft, preview)
        except self.ERRORS as e:
            messages = [str(e)]
            if preview.key and self.ledger.unconfirmed(preview.key):
                messages.append(
                    f"{self.NAME} did not confirm the post, so it may exist: {self.config.ledger} marks it unconfirmed "
                    f"and no run will send it again until a person checks (`manage.py {self.COMMAND} record {draft.id} "
                    "URN`, or --force)"
                )
            return Outcome("failed", draft, preview.key, messages=messages, preview=preview)

    def publish_queue(self, *, live=False, force=False) -> list[Outcome]:
        """A live run publishes what this process may now; a rehearsal shows every draft the site accepts, so a
        laptop sees what CI will send. `force` is for one named draft, never a queue.

        With a cadence, a run releases at most one draft, and only while a slot is open: pinned drafts that are due
        first, then the rest in queue order. A draft refused by a gate gives the slot to the next; a failed send ends
        the run, since it may have posted. Every other draft is `waiting`, with the time `calendar` gives it."""
        if force:
            raise ValueError("--force applies to one draft: name it")
        statuses = self.config.publishable_statuses if live else self.config.accept_statuses
        drafts = [d for d in self.drafts() if d.status != "published" and d.status in statuses]
        cadence = self.config.cadence
        if cadence is None and not any(d.text("publish_at") for d in drafts):
            return [self.publish(d, live=live, queued=True) for d in drafts]
        now = self.clock()
        planned = {row.draft.id: row for row in self.calendar(drafts, now=now)}
        if cadence is not None:
            open_now = cadence.open_slot(now, self.history()) is not None
            limit = 1
        else:
            open_now, limit = True, len(drafts)
        ready = [d for d in self.release_order(drafts, planned) if planned[d.id].ready(now)]
        outcomes: dict[str, Outcome] = {}
        released = 0
        for draft in ready if open_now else []:
            if released >= limit:
                break
            outcome = self.publish(draft, live=live, queued=True)
            outcomes[draft.id] = outcome
            if outcome.state in ("published", "rehearsed"):
                released += 1
            elif outcome.state == "failed":
                break
        for draft in drafts:
            if draft.id not in outcomes:
                row = planned[draft.id]
                state = "blocked" if row.problem else "waiting"
                outcomes[draft.id] = Outcome(state, draft, messages=[row.problem or row.describe(cadence, now)])
        return [outcomes[d.id] for d in drafts]

    # ── timing: the cadence, a draft's pin and its page's phase (cadence.py) ──
    def history(self) -> list[datetime]:
        """When this lane's ledger says something went out — a published share, or an attempt that may have — so
        the cadence counts what already went, whichever surface sent it."""
        out = []
        for key, entry in self.ledger.entries().items():
            if key.startswith("_") or entry.get("revises"):
                continue  # metadata, and a revision of a post, which puts nothing new in the feed
            raw = entry.get("posted_at") if urn_of(entry) else entry.get("attempted_at")
            if when := _instant(raw):
                out.append(when)
        return out

    def landed(self, entry) -> datetime | None:
        """When a page reached the branch being run: the oldest first-parent commit that touched it — its merge or
        its squash, not the commit on the branch it came from — else its own `date`. A copy with no git history
        has only the date."""
        if entry.path is not None:
            try:
                run = subprocess.run(  # noqa: S603 — fixed argv, no shell; the path is the catalog's own
                    [
                        "git",
                        "-C",
                        str(self.config.root),
                        "log",
                        "--first-parent",
                        "--format=%cI",
                        "--",
                        str(entry.path),
                    ],  # noqa: S607
                    capture_output=True,
                    text=True,
                    timeout=20,
                    check=False,
                )
                stamps = run.stdout.split() if run.returncode == 0 else []
            except (OSError, subprocess.SubprocessError):
                stamps = []
            if stamps and (when := _instant(stamps[-1])):
                return when
        return entry.date

    def timing(self, draft) -> tuple[datetime | None, bool, str]:
        """(not before, pinned, problem): a draft's `publish_at:`, read in the cadence's zone when it names none, and
        — for an article under a cadence — its page's landing plus `afterPage`; whichever is later."""
        cadence = self.config.cadence
        zone = cadence.zone if cadence else ZoneInfo("UTC")
        pin, problem = None, ""
        if raw := draft.text("publish_at"):
            try:
                pin = cadences.moment(raw, zone)
            except ValueError:
                where = cadence.timezone if cadence else "UTC"
                problem = f'publish_at "{raw}" is not a time (like 2026-11-10 09:00, read in {where})'
        phase = None
        if cadence is not None and draft.type == "article" and (source := draft.text("source")):
            entry = self.resolve_source(source)
            landed = self.landed(entry) if entry is not None else None
            phase = landed + cadence.after_page if landed is not None else None
        times = [t for t in (pin, phase) if t is not None]
        return (max(times) if times else None), pin is not None, problem

    def release_order(self, drafts, planned) -> list:
        """Pinned drafts by their pin, then the rest in queue order (the queue folder's, which dated ids keep
        chronological)."""
        pinned = sorted((d for d in drafts if planned[d.id].pinned), key=lambda d: (planned[d.id].not_before, d.id))
        return pinned + [d for d in drafts if not planned[d.id].pinned]

    def calendar(self, drafts=None, *, now=None) -> list["Planned"]:
        """Which draft goes when: under a cadence, each accepted draft in the slot a run will give it (the slot open
        now, if one is, then the slots to come); without one, on the next run once its `publish_at:` has passed."""
        now = now or self.clock()
        if drafts is None:
            statuses = self.config.accept_statuses
            drafts = [d for d in self.drafts() if d.status != "published" and d.status in statuses]
        cadence = self.config.cadence
        rows = {}
        for order, draft in enumerate(drafts):
            not_before, pinned, problem = self.timing(draft)
            rows[draft.id] = Planned(draft, not_before, pinned, problem, order)
        if cadence is None:
            for row in rows.values():
                row.at = None if row.problem else max(row.not_before or now, now)
            return list(rows.values())
        history = self.history()
        times = itertools.chain(
            [now] if cadence.open_slot(now, history) else [], cadence.slots_from(now + timedelta(microseconds=1))
        )
        items = [cadences.Item(r.draft.id, r.not_before, r.pinned, r.order) for r in rows.values() if not r.problem]
        for placement in cadence.plan(items, times=times, taken=history):
            rows[placement.key].at, rows[placement.key].reason = placement.at, placement.reason
        return list(rows.values())

    def record_post(self, draft, urn: str) -> Outcome:
        """A person found the post on LinkedIn — after an unconfirmed attempt, or one made by hand — and records it."""
        self.check_post_id(urn)
        draft = queue.read(self.config, draft.path)
        preview = self.preview(draft)
        if not preview.key:
            raise ValueError(
                f"{draft.relative} has no ledger key: {preview.blockers[0].message if preview.blockers else ''}"
            )
        if not self.ledger.readable:
            raise ConfigError(f"{self.config.ledger} is not valid JSON — fix it first")
        self._record(draft, preview, urn, None)
        queue.set_status(draft, "published", {self.ID_KEY: urn})
        return Outcome("recorded", draft, preview.key, urn, [f"recorded {urn} for {preview.key}"], preview)

    @staticmethod
    def check_post_id(urn):
        if not plan.POST_URN.match(str(urn or "")):
            raise ValueError(f"not a post URN: {urn!r}")

    def _send(self, draft, preview) -> Outcome:
        if draft.type == "revision":
            return self._revise(draft, preview)
        image = (preview.thumbnail.name, preview.thumbnail.read_bytes()) if preview.thumbnail else None
        kind = "update" if draft.update else "article"
        source_file = preview.entry.relative if preview.entry else None

        def doubt(message):
            entry = unconfirmed_entry(
                error=message,
                kind=kind,
                target="linkedin",
                author=self.config.author,
                source_file=source_file,
                now=self.clock(),
            )
            try:
                self.ledger.mark_unconfirmed(preview.key, entry)
            except (OSError, LedgerError):
                pass  # the error going up says the post may exist; a ledger that cannot take it is reported by it

        urn, image_urn = send_post(
            self.session(),
            author=self.config.author,
            payload=preview.payload,
            image=image,
            notes=preview.notes,
            mark_unconfirmed=doubt,
        )
        try:
            self._record(draft, preview, urn, image_urn)
            queue.set_status(draft, "published", {"linkedin_urn": urn})
        except (OSError, LedgerError, ValueError) as e:
            # The post exists. Losing its URN is how the next run posts it again.
            return Outcome(
                "failed",
                draft,
                preview.key,
                urn,
                [
                    f'PUBLISHED {urn} but could not record it ({e}). Add "{preview.key}" => {{"linkedin_urn": "{urn}"}} to '
                    f"{self.config.ledger} and set the draft's status to published before running again."
                ],
                preview,
            )
        return Outcome(
            "published", draft, preview.key, urn, [*preview.notes, f"published {urn}", posts.feed_url(urn)], preview
        )

    def _record(self, draft, preview, urn, image_urn):
        entry = entry_for(
            urn=urn,
            kind="update" if draft.update else "article",
            target="linkedin",
            author=self.config.author,
            source_file=preview.entry.relative if preview.entry else None,
            image_urn=image_urn,
            now=self.clock(),
        )
        self.ledger.record(preview.key, entry)
        if self.config.site_map:
            self.write_site_map()

    def _revise(self, draft, preview) -> Outcome:
        """Set a published post's text to the revision's (PARTIAL_UPDATE). Sending the same text twice changes
        nothing, so a failure is retried by the next run rather than doubted."""
        target = draft.text("revises")
        self.session().run(lambda client: posts.update(client, target, preview.payload))
        entry = entry_for(urn=target, kind="update", target="linkedin", author=self.config.author, now=self.clock())
        entry["revises"] = target  # a revision of a post, not a post: the cadence and the site map leave it out
        try:
            self.ledger.record(preview.key, entry)
            queue.set_status(draft, "published", {"linkedin_urn": target})
        except (OSError, LedgerError, ValueError) as e:
            return Outcome(
                "failed",
                draft,
                preview.key,
                target,
                [f"REVISED {target} but could not record it ({e}): set {draft.relative} to published by hand"],
                preview,
            )
        return Outcome(
            "published",
            draft,
            preview.key,
            target,
            [*preview.notes, f"revised {target}", posts.feed_url(target)],
            preview,
        )

    # ── synchronization: every page on LinkedIn, and LinkedIn on every page ─
    def sync(self) -> list[dict]:
        """Every shareable page against LinkedIn: `shared` (its own post), `featured` (only as a week's feature),
        `queued` (a draft waits for it) or `missing`."""
        queued: dict[str, queue.Draft] = {}
        for d in self.drafts():
            if d.type == "article" and d.status != "published" and (src := d.text("source")):
                if (entry := self.resolve_source(src)) is not None:
                    queued.setdefault(entry.relative, d)
        featured = {
            e.get("source_file"): e.get("urn")
            for key, e in self.ledger.shares()
            if key.startswith("feature:") and e.get("source_file")
        }
        rows = []
        for source in self.sources():
            rel = source.entry.relative
            state = (
                "shared" if source.urn else "featured" if rel in featured else "queued" if rel in queued else "missing"
            )
            rows.append(
                {
                    "path": rel,
                    "url": source.url,
                    "state": state,
                    "urn": source.urn or featured.get(rel),
                    "draft": queued[rel].relative if rel in queued else None,
                }
            )
        return rows

    def draft_missing(self, limit: int | None = None) -> list[queue.Draft]:
        """A pending draft for each page with no post and none waiting, newest first, up to `limit`: the backfill,
        which a person approves and the cadence releases one slot at a time."""
        missing = [row for row in self.sync() if row["state"] == "missing"]
        return [self.compose(row["path"]) for row in missing[: limit if limit is not None else len(missing)]]

    def site_map(self) -> dict:
        """What the site shows beside each page: its LinkedIn posts, keyed by the page's URL path."""
        out: dict[str, dict] = {}
        for key, entry in self.ledger.shares():
            if entry.get("revises"):
                continue
            page = self.resolve_source(entry["source_file"]) if entry.get("source_file") else None
            url = (self.canonical_url(page) if page is not None else None) or (key if "://" in key else None)
            if not url:
                continue
            path = urlsplit(url).path or "/"
            item = out.setdefault(path, {"url": url, "posts": []})
            item["posts"].append(
                {
                    "url": posts.feed_url(entry["urn"]),
                    "posted_at": entry.get("posted_at"),
                    **({"feature": key.split(":", 1)[1]} if key.startswith("feature:") else {}),
                }
            )
        for item in out.values():
            item["posts"].sort(key=lambda p: p.get("posted_at") or "")
        return dict(sorted(out.items()))

    def write_site_map(self) -> bool:
        """Write the site map (`siteMap`) when it changed; True when it did."""
        path = self.config.path(self.config.site_map)
        text = json.dumps(self.site_map(), indent=2, sort_keys=True, ensure_ascii=True) + "\n"
        if path.is_file() and path.read_text(encoding="utf-8") == text:
            return False
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return True

    # ── the week's featured article ─────────────────────────────────────────
    def feature_week(self, week: str | None = None) -> tuple[str, datetime]:
        """The week a feature is drafted for, and its slot: the given ISO week, else this week while its slot is
        still ahead, else next week."""
        weekly = self.config.weekly
        if week:
            if not queue.WEEK.match(week):
                raise ValueError(f"a week is YYYY-Www, got {week!r}")
            year, number = int(week[:4]), int(week[6:])
            monday = date.fromisocalendar(year, number, 1)
            return week, weekly.slot_in(monday)
        today = self.clock().astimezone(weekly.zone).date()
        monday = today - timedelta(days=today.weekday())
        slot = weekly.slot_in(monday)
        if slot <= self.clock():
            monday += timedelta(days=7)
            slot = weekly.slot_in(monday)
        year, number, _ = monday.isocalendar()
        return f"{year}-W{number:02d}", slot

    def weekly_feature(self, week: str | None = None) -> tuple[queue.Draft | None, str]:
        """Draft the week's featured LinkedIn article: the section the ring gives the week, that section's featured
        post (front matter `featured: true` first, then the newest) not featured before, pinned to the week's slot.
        One feature a week: an existing draft or ledger entry for it is the answer."""
        weekly = self.config.weekly
        if weekly is None:
            raise ConfigError(f"no weekly feature configured (distribution.{self.config.BLOCK}.weekly)")
        week, slot = self.feature_week(week)
        if existing := next((d for d in self.drafts() if d.text("feature") == week), None):
            return existing, f"{week} already has its feature: {existing.relative}"
        if self.ledger.entry(f"feature:{week}"):
            return None, f"{week}'s feature already went out"
        section = weekly.section_for(date.fromisocalendar(int(week[:4]), int(week[6:]), 1))
        candidates = [s.entry for s in self.sources() if section_of(s.entry) == section]
        last_featured: dict[str, str] = {}
        for key, entry in self.ledger.entries().items():
            if key.startswith("feature:") and entry.get("source_file"):
                last_featured[entry["source_file"]] = max(last_featured.get(entry["source_file"], ""), key)
        waiting = {d.text("source") for d in self.drafts() if d.text("feature")}
        fresh = [e for e in candidates if e.relative not in last_featured and e.relative not in waiting]
        if fresh:
            fresh.sort(key=lambda e: (e.data.get("featured") is not True, -(e.date.timestamp() if e.date else 0)))
            pick = fresh[0]
        elif candidates:
            pick = min(candidates, key=lambda e: last_featured.get(e.relative, ""))
        else:
            return None, f"no live post in {section} to feature in {week}"
        url = self.canonical_url(pick)
        local = slot.astimezone(weekly.zone)
        draft = queue.create(
            self.config,
            type="article",
            slug=f"{week.lower()}-feature-{slug(pick.source_relative)}",
            body=default_commentary(pick, self.config.hashtag_limit),
            meta={
                "source": pick.relative,
                "title": pick.title,
                "url": url,
                "feature": week,
                "section": section,
                "publish_at": f"{local:%Y-%m-%d %H:%M}",
            },
        )
        return draft, f"{week}: {section} — {pick.relative}, at {local:%a %Y-%m-%d %H:%M} {local.tzname()}"

    # ── the review loop's order ─────────────────────────────────────────────
    def revisit(self) -> list[dict]:
        """The posts this lane published, least recently reviewed first (`_reviewed` in the ledger's metadata),
        then oldest: the order a review loop takes them in, one a run."""
        reviewed = (self.ledger.raw().get("_meta") or {}).get("reviewed") or {}
        rows = [
            {
                "key": key,
                "urn": entry["urn"],
                "source": entry.get("source_file"),
                "posted_at": entry.get("posted_at"),
                "reviewed_at": reviewed.get(key),
            }
            for key, entry in self.ledger.shares()
            if not entry.get("revises")
        ]
        return sorted(rows, key=lambda r: (r["reviewed_at"] or "", r["posted_at"] or ""))

    def mark_reviewed(self, key: str) -> str:
        if not self.ledger.urn_for(key):
            raise ValueError(f"{key} is not a post in {self.config.ledger}")
        reviewed = dict((self.ledger.raw().get("_meta") or {}).get("reviewed") or {})
        reviewed[key] = stamp(self.clock())
        self.ledger.write_meta({"reviewed": dict(sorted(reviewed.items()))})
        return reviewed[key]

    # ── reads ────────────────────────────────────────────────────────────────
    def session(self) -> Session:
        return Session(
            self.credentials,
            api_version=self.config.api_version,
            sleeper=self.sleeper,
            transport=self.transport,
            now=self.clock(),
        )

    def posts(self, count=10) -> list[dict]:
        return self.session().run(lambda client: posts.by_author(client, author=self.config.author, count=count))

    def verify(self, urn) -> dict:
        return self.session().run(lambda client: posts.get(client, urn))

    def organizations(self):
        def work(client):
            pages = statistics.administered(client)
            for page in pages or []:
                page.name = statistics.organization_name(client, page.urn)
            return pages

        return self.session().run(work)

    def statistics(self, *, write=False) -> dict:
        """Aggregate counts for the ledger's posts by the configured author, joined onto content paths through the
        ledger and merged into `.cms/distribution/performance.json` — the file the extension's catering reads."""
        config = self.config
        own, skipped = [], []
        for key, entry in self.ledger.shares():
            mine = (
                plan.POST_URN.match(entry["urn"])
                and entry.get("source_file")
                and (not entry.get("author") or entry.get("author") == config.author)
            )
            (own if mine else skipped).append((key, entry))
        urns = [entry["urn"] for _, entry in own]
        counts = self.session().run(lambda client: read_statistics(client, config.author, urns)) if urns else {}
        performance = {entry["source_file"]: counts[entry["urn"]] for _, entry in own if entry["urn"] in counts}
        result = {
            "performance": performance,
            "matched": [u for u in urns if u in counts],
            "skipped": [key for key, _ in skipped],
            "path": None,
        }
        if write:
            result["path"] = self.write_performance(performance)
        return result

    def performance_path(self) -> str:
        return f"{self.config.cms_root}/distribution/performance.json"

    def write_performance(self, performance: dict) -> str:
        path = self.config.path(self.performance_path())
        try:
            current = json.loads(path.read_text(encoding="utf-8")).get("content") if path.is_file() else {}
        except (OSError, ValueError, AttributeError):
            current = {}
        content = dict(sorted({**(current if isinstance(current, dict) else {}), **performance}.items()))
        payload = {"generated_at": stamp(self.clock()), "note": NOTE, "content": content}
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(payload, indent=2, ensure_ascii=True) + "\n"
        temp = path.with_name(f".{path.name}.tmp")
        temp.write_text(text, encoding="utf-8")
        temp.replace(path)
        return self.performance_path()

    def status(self, *, check=False, warn_days=7) -> dict:
        config, drafts = self.config, self.drafts()
        ledger = self.ledger
        report = {
            "site": str(config.root),
            "configured": config.configured,
            "author": config.author or None,
            "author_type": config.author_type,
            "site_url": config.site_url,
            "api_version": config.api_version,
            "api_version_status": plan.version_status(config.api_version),
            "queue": config.queue,
            "ledger": config.ledger,
            "performance": self.performance_path(),
            # Only when the site keeps one, so a report is the Ruby lane's for every site that does not.
            **({"site_map": config.site_map} if config.site_map else {}),
            "accept_statuses": config.accept_statuses,
            "publishable_statuses": config.publishable_statuses,
            "merged": config.merged,
            "armed": config.publish_armed,
            "credentials": self.credentials.present(),
            "drafts": {s: sum(1 for d in drafts if d.status == s) for s in queue.STATUSES},
            "published": len(ledger.shares()),
            "ledger_readable": ledger.readable,
            "errors": config.errors,
            "warnings": config.warnings,
        }
        if check:
            report["token"] = self.check_token(warn_days=warn_days)
        return report

    def check_token(self, *, warn_days=7) -> dict:
        creds = self.credentials
        if not (creds.access or creds.refreshable):
            return {"ok": False, "problems": ["no LinkedIn credential in the environment"]}
        out = {"ok": True, "problems": [], "notes": []}
        try:
            session = self.session()
            if creds.app:
                info = session.oauth().introspect(session.client().token)
                days = info.days_left(self.clock())
                out.update(
                    active=info.active,
                    status=info.status,
                    scopes=info.scopes,
                    expires_at=info.expires_at.isoformat() if info.expires_at else None,
                    days_left=days,
                )
                if not info.active:
                    out["problems"].append(f"the token is {info.status or 'not active'}")
                if days is not None and days <= warn_days:
                    out["problems"].append(f"the token expires in {days} day(s)")
            else:
                out["notes"].append("no LINKEDIN_CLIENT_ID/SECRET: expiry cannot be read, only whether the token works")
            self._probe(session, out)
        except Error as e:
            return {"ok": False, "problems": [str(e)]}
        out["ok"] = not out["problems"]
        return out

    def _probe(self, session, out):
        try:
            if self.config.author_type == "person":
                out["member"] = session.run(oauth.member)
            else:
                session.run(lambda client: posts.by_author(client, author=self.config.author, count=1))
            out["probe"] = "ok"
        except HTTPError as e:
            if e.forbidden:
                out["probe"] = "forbidden"
                out["notes"].append(
                    f"the token authenticates but may not read {self.config.author}'s posts ({e}); publishing may still work"
                )
            else:
                out["probe"] = "failed"
                out["problems"].append(str(e))

    @staticmethod
    def link_of(preview) -> str | None:
        """The page an article's post links to: its card's source, else a key that is a URL (X's)."""
        article = ((preview.payload or {}).get("content") or {}).get("article") or {}
        if article.get("source"):
            return article["source"]
        key = preview.key or ""
        return key if "://" in key else None

    def page_down(self, draft, url) -> str | None:
        """Why the page an article links to is not up yet (`checkLink`), or None: a 2xx or 3xx answer is up; a 404 or
        a 410 is not published yet; anything else — refused, failing, unreachable — is not confirmed, so the share
        waits rather than send readers somewhere that may not work. A text update has no page."""
        if draft.type != "article" or not url or not self.config.check_link:
            return None
        status = self.page_check(url)
        if status is not None and status < 400:
            return None
        if status in (404, 410):
            return f"{url} answers {status}: the page is not live yet, so the share waits until it is"
        answer = f"answers {status}" if status is not None else "did not answer"
        return (
            f"{url} {answer}, so whether it is live is not confirmed: the share waits (set checkLink: false for a site "
            "that refuses automated requests)"
        )

    def _fell_back(self, thumbnail: Path) -> bool:
        fallback = self.config.fallback_image
        return bool(fallback) and thumbnail == self.config.path(fallback)

    def _image_of(self, draft, notes) -> Path | None:
        """The draft's own card image (`image:`, a repository path), when it names one that can be uploaded."""
        value = draft.text("image") if draft is not None else ""
        if not value or "://" in value:
            if value:
                notes.append(f"image {value} is a URL: name a file in the repository")
            return None
        root = self.config.root
        found = next(
            (p for p in (root / value.lstrip("/"), self.catalog.source / value.lstrip("/")) if p.is_file()),
            None,
        )
        if found is None or not _inside(root, found):
            notes.append(f"image {value} is not on disk")
            return None
        ok, reason = posts.uploadable(found.name, found.stat().st_size)
        if not ok:
            notes.append(f"image {value} is not uploadable: {reason}")
            return None
        return found

    def _thumbnail(self, entry, notes, draft=None) -> Path | None:
        if (own := self._image_of(draft, notes)) is not None:
            return own
        root = self.config.root
        value = entry.preview.strip() if entry else ""
        if value and "://" not in value:
            relative = value.lstrip("/")
            source = self.catalog.source
            found = next(
                (
                    p
                    for p in (source / relative, source / "assets" / relative, root / relative)
                    if p.is_file() and _inside(root, p)
                ),
                None,
            )
            if found is not None:
                ok, reason = posts.uploadable(found.name, found.stat().st_size)
                if ok:
                    return found
                notes.append(f"preview image not uploadable: {reason}")
            else:
                notes.append(f"preview image {value} is not on disk")
        if self.config.fallback_image:
            fallback = self.config.path(self.config.fallback_image)
            ok, reason = (
                posts.uploadable(fallback.name, fallback.stat().st_size)
                if fallback.is_file()
                else (False, f"{self.config.fallback_image} does not exist")
            )
            if ok and _inside(root, fallback):
                notes.append(f"using the fallback card image {self.config.fallback_image}")
                return fallback
            notes.append(f"fallback image not uploadable: {reason or 'outside the repository'}")
        if entry is not None:
            notes.append("posting without a card image")
        return None


def section_of(entry) -> str:
    """A post's section: its first category (the taxonomy's primary, which names its folder), else its folder."""
    categories = entry.data.get("categories")
    first = categories[0] if isinstance(categories, list) and categories else categories
    if first:
        return str(first).strip().lower()
    parts = PurePosixPath(entry.source_relative).parts
    return parts[-2].lower() if len(parts) >= 2 else ""


def page_status(url: str) -> int | None:
    """The HTTP status a page answers with, following redirects; None when it cannot be reached. The lane's one
    request outside LinkedIn's and X's declared calls: a GET of the very page a share links to."""
    try:
        response = httpx.get(
            url, follow_redirects=True, timeout=15.0, headers={"User-Agent": "zer0-CMS distribution lane (page check)"}
        )
    except httpx.HTTPError:
        return None
    return response.status_code


def read_statistics(client, author: str, urns) -> dict:
    kind = plan.author_type(author)
    if kind == "organization":
        return statistics.for_organization(client, organization=author, urns=urns)
    if kind == "person":
        return {urn: statistics.for_member_post(client, urn=urn) for urn in urns}
    raise ConfigError("no LinkedIn author configured")


def _stem(path: str) -> str:
    """The path without its last extension (`a/2026-07-06-x.md` → `a/2026-07-06-x`)."""
    return re.sub(r"\.[^./]+\Z", "", path)


def slug_stem(source_relative: str) -> str:
    """A file's name without its extension or a date prefix: `index` marks a section index, which is structure."""
    return DATED.sub("", PurePosixPath(_stem(source_relative)).name, count=1)


def _inside(root: Path, path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(root) and path.resolve() != root
    except OSError:
        return False


def _newest_first(entry):
    when = entry.date.timestamp() if entry.date else None
    return (when is None, -(when or 0), entry.source_relative)
