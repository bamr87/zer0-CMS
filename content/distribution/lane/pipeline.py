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
"""

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from suggestions.guard import guard_text

from .. import gates
from ..gates import Blocker
from ..ledger import Ledger, LedgerError, entry_for, stamp, unconfirmed_entry
from ..linkedin import Error, HTTPError, oauth, plan, posts, statistics
from ..linkedin.client import send
from ..linkedin.session import Session, send_post
from ..permalink import path_for
from . import drafts as queue
from .site import ARM_VARIABLE, DATED, MERGED_VARIABLE, ConfigError, catalog, default_commentary, read_jsonc, slug

NOTE = "Aggregate statistics for the author's own content. No per-reader data."


@dataclass
class Source:
    entry: object
    url: str
    urn: str | None

    def as_dict(self) -> dict:
        e = self.entry
        return {
            "path": e.relative,
            "collection": e.collection,
            "title": e.title,
            "date": e.date_raw,
            "url": self.url,
            "linkedin_urn": self.urn,
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
    state: str  # published, skipped, rehearsed, approved, recorded, blocked, failed
    draft: queue.Draft | None
    key: str | None = None
    urn: str | None = None
    messages: list = field(default_factory=list)
    preview: Preview | None = None

    @property
    def ok(self) -> bool:
        return self.state in ("published", "skipped", "rehearsed", "approved", "recorded")

    def as_dict(self) -> dict:
        return {
            "state": self.state,
            "draft": self.draft.relative if self.draft else None,
            "key": self.key,
            "linkedin_urn": self.urn,
            "messages": self.messages,
        }


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
    def __init__(self, config, *, transport=send, sleeper=time.sleep, clock=None, credentials=None):
        self.config = config
        self.transport = transport
        self.sleeper = sleeper
        self.clock = clock or (lambda: datetime.now(UTC))
        self.credentials = credentials or config.credentials
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
                out.append(Source(entry, url, self.ledger.urn_for(url)))
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
                thumbnail = self._thumbnail(entry, notes)
            key = url
            if author_ok and url and title.strip():
                try:
                    payload = posts.article_payload(
                        author=author, commentary=commentary, source=url, title=title, description=description
                    )
                except ValueError as e:
                    blockers.append(Blocker("source_missing", str(e)))
        else:
            blockers.append(Blocker("source_missing", f'unknown draft type "{draft.type}" (article or update)'))

        guard = check_commentary(commentary, banned_patterns(config))
        errors = [f["message"] for f in guard if f["level"] == "error"]
        if errors:
            blockers.append(Blocker("guard_error", f"brand guard: {'; '.join(errors)}"))
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
                        f"author's LinkedIn posts, then run `manage.py linkedin record {draft.id} URN` if it did, or publish "
                        "it with --force if it did not"
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
                        f"draft is pending: this site publishes a pending draft only once it is merged ({MERGED_VARIABLE}=1, "
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
                    "publish_disabled", f"publishing is not armed ({ARM_VARIABLE}=1 in the environment, and a live run)"
                )
            )
        if not (self.credentials.access or self.credentials.refreshable):
            blockers.append(
                Blocker(
                    "no_credential",
                    "no LinkedIn credential (LINKEDIN_ACCESS_TOKEN, or a refresh token with the app credentials)",
                )
            )
        return Preview(
            draft, draft.type, key, entry, commentary, payload, thumbnail, notes, guard, gates.ordered(blockers)
        )

    # ── publish ──────────────────────────────────────────────────────────────
    def publish(self, draft, *, live=False, force=False) -> Outcome:
        """Without `live`, a rehearsal: the full preview and its blockers, nothing sent, nothing written."""
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
            queue.set_status(draft, "published", {"linkedin_urn": urn})
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
        try:
            return self._send(draft, preview)
        except (Error, ConfigError, LedgerError, ValueError) as e:
            messages = [str(e)]
            if preview.key and self.ledger.unconfirmed(preview.key):
                messages.append(
                    f"LinkedIn did not confirm the post, so it may exist: {self.config.ledger} marks it unconfirmed and "
                    f"no run will send it again until a person checks (`manage.py linkedin record {draft.id} URN`, or --force)"
                )
            return Outcome("failed", draft, preview.key, messages=messages, preview=preview)

    def publish_queue(self, *, live=False, force=False) -> list[Outcome]:
        """A live run publishes every draft this process may; a rehearsal shows every draft the site accepts, so a
        laptop sees what CI will send. `force` is for one named draft, never a queue."""
        if force:
            raise ValueError("--force applies to one draft: name it")
        statuses = self.config.publishable_statuses if live else self.config.accept_statuses
        return [self.publish(d, live=live) for d in self.drafts() if d.status != "published" and d.status in statuses]

    def record_post(self, draft, urn: str) -> Outcome:
        """A person found the post on LinkedIn — after an unconfirmed attempt, or one made by hand — and records it."""
        if not plan.POST_URN.match(str(urn or "")):
            raise ValueError(f"not a post URN: {urn!r}")
        draft = queue.read(self.config, draft.path)
        preview = self.preview(draft)
        if not preview.key:
            raise ValueError(
                f"{draft.relative} has no ledger key: {preview.blockers[0].message if preview.blockers else ''}"
            )
        if not self.ledger.readable:
            raise ConfigError(f"{self.config.ledger} is not valid JSON — fix it first")
        self._record(draft, preview, urn, None)
        queue.set_status(draft, "published", {"linkedin_urn": urn})
        return Outcome("recorded", draft, preview.key, urn, [f"recorded {urn} for {preview.key}"], preview)

    def _send(self, draft, preview) -> Outcome:
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

    def _thumbnail(self, entry, notes) -> Path | None:
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
