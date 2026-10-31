"""The governed path from a site's page to an X post, over the site's own files
— the LinkedIn lane's pipeline (`pipeline.py`) with X's preview, publish step,
reads and token check:

    page ──▶ draft (pending) ──▶ approve ──▶ preview ──▶ publish ──▶ ledger
                                  a person   no network   gated      keyed by URL

What is the same is inherited, not copied: the sources, composing, approving,
the gates after the target's own (the ledger, approval, arming, the
credential), the publish flow and recording a post by hand. What X changes: a
post is `{"text": …}` — an article's commentary with the page's URL after it,
whose card X draws from the page's own tags, so there is no image to upload —
its length is counted as X counts it (`x/plan.py`), the account a token posts
as is checked before anything is sent (X posts as whoever the token is), and a
post's id is a number.
"""

from dataclasses import replace

from suggestions.guard import guard_text

from .. import gates
from ..gates import Blocker
from ..ledger import LedgerError, entry_for, unconfirmed_entry
from ..x import Client, Error, HTTPError, plan, posts
from ..x.client import send
from . import drafts as queue
from .pipeline import Outcome, Pipeline, Preview, banned_patterns
from .site import ConfigError, default_commentary


def check_text(commentary: str, link, extra) -> list[dict]:
    """The brand guard on the commentary, plus X's own limit on the whole post — the commentary and the link — as X
    counts it."""
    findings = guard_text(commentary, extra)
    length = plan.weighted_length(plan.post_text(commentary, link))
    if length > plan.TEXT_MAX:
        message = f"the post is {length} characters as X counts them (max {plan.TEXT_MAX}; a link counts 23)"
        findings.insert(len(findings) - 1, {"level": "error", "message": message})
    return findings


class XPreview(Preview):
    def as_dict(self, root) -> dict:
        """The LinkedIn lane's preview with X's measure: the whole post's length as X counts it, and no fold or card
        image."""
        out = {k: v for k, v in super().as_dict(root).items() if k not in ("commentary_length", "fold", "thumbnail")}
        return {**out, "length": plan.weighted_length((self.payload or {}).get("text", "")), "limit": plan.TEXT_MAX}


class XPipeline(Pipeline):
    NAME, COMMAND, ID_KEY = "X", "x", "post_id"
    POSTS_WHERE, ID_WORD = "account's posts on X", "ID"
    ERRORS = (*Pipeline.ERRORS, Error)

    def __init__(self, config, *, transport=send, **options):
        super().__init__(config, transport=transport, **options)

    # An outcome names a post's id as X's lane does: `post_id`.
    def approve(self, draft) -> Outcome:
        return replace(super().approve(draft), id_key=self.ID_KEY)

    def publish(self, draft, **options) -> Outcome:
        return replace(super().publish(draft, **options), id_key=self.ID_KEY)

    def record_post(self, draft, post_id) -> Outcome:
        return replace(super().record_post(draft, post_id), id_key=self.ID_KEY)

    @staticmethod
    def check_post_id(post_id):
        if not plan.POST_ID.match(str(post_id or "")):
            raise ValueError(f"not an X post id (its digits, from x.com/…/status/ID): {post_id!r}")

    def credential_missing(self) -> str | None:
        if self.credentials.complete:
            return None
        missing = [name for name, held in self.credentials.present().items() if not held]
        return f"no X credential ({', '.join(missing)} not set)"

    # ── preview: the exact artifact, no network, no writes ──────────────────
    def preview(self, draft) -> Preview:
        config = self.config
        blockers = [Blocker("config_error", m) for m in config.errors]
        notes: list[str] = []
        if not config.account:
            blockers.append(Blocker("no_author", "no X account configured (distribution.x.account)"))
        commentary, entry, key, link = draft.commentary, None, None, None
        if draft.type == "update":
            key = f"draft:{draft.relative}"
            if not commentary:
                blockers.append(Blocker("source_missing", "an update needs a body"))
        elif draft.type == "article":
            source = draft.text("source")
            entry = self.resolve_source(source) if source else None
            link = (self.canonical_url(entry) if entry else None) or draft.text("link") or None
            if source and entry is None:
                blockers.append(Blocker("source_missing", f"source {source} does not match a page on this site"))
            elif link is None:
                message = f"{entry.relative} has no public URL — set the site URL" if entry else None
                blockers.append(Blocker("source_missing", message or "an article needs a source page or a link"))
            elif not plan.LINK.fullmatch(link):
                blockers.append(Blocker("source_missing", f"the link is not an http(s) URL: {link}"))
            if not commentary and entry:
                commentary = default_commentary(entry, config.hashtag_limit)
                notes.append("the draft has no body; the page's default commentary will publish")
            key = link
        else:
            blockers.append(Blocker("source_missing", f'unknown draft type "{draft.type}" (article or update)'))
        payload = posts.payload(commentary=commentary, link=link) if commentary or link else None
        guard = check_text(commentary, link, banned_patterns(config))
        if errors := [f["message"] for f in guard if f["level"] == "error"]:
            blockers.append(Blocker("guard_error", f"brand guard: {'; '.join(errors)}"))
        self._gates(draft, key, blockers)
        return XPreview(draft, draft.type, key, entry, commentary, payload, None, notes, guard, gates.ordered(blockers))

    # ── publish ──────────────────────────────────────────────────────────────
    def client(self) -> Client:
        return Client(self.credentials, sleeper=self.sleeper, transport=self.transport)

    def _send(self, draft, preview) -> Outcome:
        source_file = preview.entry.relative if preview.entry else None
        client = self.client()
        posts.check_account(client, self.config.account)  # a read: nothing is in doubt if it fails
        try:
            post_id = posts.create(client, preview.payload)
        except HTTPError as e:
            if e.status == 0 or e.status >= 500:
                self._doubt(draft, preview, str(e), source_file)
            raise
        except Error as e:
            self._doubt(draft, preview, str(e), source_file)
            raise
        url = posts.post_url(post_id, self.config.account)
        try:
            self._record(draft, preview, post_id, None)
            queue.set_status(draft, "published", {self.ID_KEY: post_id})
        except (OSError, LedgerError, ValueError) as e:
            # The post exists. Losing its id is how the next run posts it again.
            return Outcome(
                "failed",
                draft,
                preview.key,
                post_id,
                [
                    f'PUBLISHED {url} but could not record it ({e}). Add "{preview.key}" => {{"urn": "{post_id}"}} to '
                    f"{self.config.ledger} and set the draft's status to published before running again."
                ],
                preview,
            )
        return Outcome("published", draft, preview.key, post_id, [*preview.notes, f"published {post_id}", url], preview)

    def _doubt(self, draft, preview, message, source_file):
        entry = unconfirmed_entry(
            error=message,
            kind="update" if draft.update else "article",
            target="x",
            author=self.config.account,
            source_file=source_file,
            now=self.clock(),
        )
        try:
            self.ledger.mark_unconfirmed(preview.key, entry)
        except (OSError, LedgerError):
            pass  # the error going up says the post may exist; a ledger that cannot take it is reported by it

    def _record(self, draft, preview, post_id, image_urn):
        entry = entry_for(
            urn=post_id,
            kind="update" if draft.update else "article",
            target="x",
            author=self.config.account,
            source_file=preview.entry.relative if preview.entry else None,
            now=self.clock(),
        )
        self.ledger.record(preview.key, entry)

    # ── reads ────────────────────────────────────────────────────────────────
    def account(self) -> dict:
        return posts.check_account(self.client(), self.config.account)

    def posts(self, count=10) -> list[dict]:
        client = self.client()
        found = posts.check_account(client, self.config.account)
        return posts.by_account(client, account_id=found["id"], count=count)

    def verify(self, post_id) -> dict:
        self.check_post_id(post_id)
        client = self.client()
        found = posts.lookup(client, [post_id], account_id=posts.check_account(client, self.config.account)["id"])
        if post_id not in found:
            raise Error(f"{post_id} is not a post of @{self.config.account}'s")
        return found[post_id]

    def status(self, *, check=False, warn_days=7) -> dict:
        config, drafts, ledger = self.config, self.drafts(), self.ledger
        report = {
            "site": str(config.root),
            "configured": config.configured,
            "account": config.account or None,
            "site_url": config.site_url,
            "queue": config.queue,
            "ledger": config.ledger,
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
            report["token"] = self.check_token()
        return report

    def check_token(self, **_ignored) -> dict:
        """Whether the credentials work and post as the configured account. An OAuth 1.0a token has no expiry to
        read: it works until its owner revokes it or the app's permission changes."""
        if missing := self.credential_missing():
            return {"ok": False, "problems": [missing]}
        try:
            found = self.account()
        except (Error, ConfigError) as e:
            return {"ok": False, "problems": [str(e)]}
        return {"ok": True, "problems": [], "notes": [], "account": f"@{found['username']}", "account_id": found["id"]}
