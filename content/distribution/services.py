"""Distribution's commands: channels and their connections, composing a post,
the brand guard, approval, the gates, publishing (in a worker), the ledger and
statistics. Views, tools, the consumer and the workers call these; nothing else
writes the tables.

    compose ──▶ guard ──▶ approve ──▶ publish (202) ──▶ worker: gates again ──▶ published | failed
    a person,    the brand   a person    a person with        LinkedIn, WordPress,       ledger, keyed by
    an agent or  guard       who may     the right, an armed   GitHub, a newsletter       canonical URL
    a published  (findings   publish     channel and the
    page         stored)     the page    deployment's switch

The gates are `gates.ORDER`, the same as a site's own lane's: a post publishes
only when a person approved it, the channel is armed (`Channel.armed`) and the
deployment armed the kind (`DISTRIBUTION_ARMED`, from `ZER0_LINKEDIN_PUBLISH`,
`ZER0_WORDPRESS_PUBLISH`, `ZER0_GITHUB_PR_PUBLISH`, `ZER0_EMAIL_PUBLISH`), the
ledger has no entry for its key — in the channel's rows and, for a LinkedIn
channel with a `ledger_file`, in the site's own ledger file, where the
extension and CI write — and the brand guard has no error. The worker runs the
gates again before anything leaves.
"""

import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import UTC
from pathlib import Path
from types import SimpleNamespace

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.utils import timezone
from wagtail.models import Page

from ai import crypto
from ai.providers import NotConfigured
from ops.errors import Conflict, Forbidden, Invalid, NotFound
from suggestions.guard import extra_patterns, guard_text

from . import gates, permalink
from .gates import Blocker
from .ledger import Ledger, LedgerError, serialize, urn_of
from .linkedin import Error as LinkedInError
from .linkedin import HTTPError, oauth, plan, posts, statistics
from .linkedin.session import Credentials, Session, send_post
from .models import (
    IDENTITY,
    SECRETS,
    SETTINGS,
    Channel,
    DistributionPost,
    Kind,
    LedgerEntry,
    Statistic,
    manages_channels,
)
from .transports import TransportError

log = logging.getLogger(__name__)
FINAL = (DistributionPost.Status.PUBLISHED, DistributionPost.Status.REJECTED)
EDITABLE = ("title", "description", "commentary", "kind")


def _detail(field_name, message):
    return [{"field": field_name, "code": "invalid", "message": message}]


# ── who may do what ─────────────────────────────────────────────────────────


def may_manage(user) -> bool:
    return manages_channels(user)


def may_compose(post_or_page, user) -> bool:
    page = post_or_page.page if isinstance(post_or_page, DistributionPost) else post_or_page
    if page is None:
        return manages_channels(user)
    return page.specific.permissions_for_user(user).can_edit()


def may_publish(post, user) -> bool:
    """Approving and publishing are publishing acts: the right to publish the page (a text update, which has no
    page, is the channel managers')."""
    if user is None or not user.is_authenticated or user.username.startswith("agent:"):
        return False
    if post.page is None:
        return manages_channels(user)
    return post.page.specific.permissions_for_user(user).can_publish()


def armed_for_kind(kind: str) -> bool:
    return kind in settings.DISTRIBUTION_ARMED


# ── channels ────────────────────────────────────────────────────────────────


def clean_settings(kind: str, values: dict) -> dict:
    values = values or {}
    unknown = sorted(set(values) - set(SETTINGS[kind]))
    if unknown:
        raise Invalid(
            f"a {kind} channel does not take {', '.join(unknown)}", details=_detail("settings", ", ".join(unknown))
        )
    out = {k: v for k, v in values.items() if v not in (None, "")}
    if kind == Kind.LINKEDIN:
        if out.get("author") and plan.author_type(out["author"]) is None:
            raise Invalid(
                "author must be urn:li:organization:{id} or urn:li:person:{id}", details=_detail("settings", "author")
            )
        if out.get("api_version") and plan.version_status(out["api_version"]) == "invalid":
            raise Invalid("api_version must be YYYYMM", details=_detail("settings", "api_version"))
        if out.get("ledger_file"):
            text = str(out["ledger_file"]).replace("\\", "/")
            if text.startswith("/") or ".." in text.split("/"):
                raise Invalid("ledger_file is a path inside the site", details=_detail("settings", "ledger_file"))
    if kind == Kind.WORDPRESS and out.get("url"):
        if not re.match(r"https?://[^\s/]+", str(out["url"])):
            raise Invalid("url is the WordPress site's address, http(s)", details=_detail("settings", "url"))
        if out.get("status", "draft") not in ("draft", "pending", "private", "publish"):
            raise Invalid("status is draft, pending, private or publish", details=_detail("settings", "status"))
    if kind == Kind.GITHUB_PR and out.get("repo") and not re.fullmatch(r"[\w.-]+/[\w.-]+", str(out["repo"])):
        raise Invalid("repo is owner/name", details=_detail("settings", "repo"))
    return out


@transaction.atomic
def save_channel(user, *, channel=None, **fields) -> Channel:
    if not manages_channels(user):
        raise Forbidden("setting up a channel needs the right to manage channels")
    channel = channel or Channel(created_by=user)
    kind = fields.get("kind", channel.kind)
    if channel.pk and kind != channel.kind:
        raise Invalid("a channel's kind does not change: make another channel", details=_detail("kind", "fixed"))
    before = {k: channel.setting(k) for k in IDENTITY.get(kind, ())} if channel.pk else None
    site_before = channel.site_id if channel.pk else None
    for name in ("site", "kind", "name", "newsletter", "auto_draft", "armed"):
        if name in fields:
            setattr(channel, name, fields[name])
    if "settings" in fields:
        channel.settings = clean_settings(kind, fields["settings"])
    if kind == Kind.EMAIL:
        if channel.newsletter is None:
            raise Invalid(
                "an email channel sends one of the site's newsletters", details=_detail("newsletter", "required")
            )
        if channel.newsletter.site_id != channel.site_id:
            raise Invalid("the newsletter belongs to another site", details=_detail("newsletter", "other site"))
    elif "newsletter" in fields and fields["newsletter"] is not None:
        raise Invalid("only an email channel has a newsletter", details=_detail("newsletter", "email only"))
    moved = before is not None and (before != {k: channel.setting(k) for k in before} or site_before != channel.site_id)
    if moved:
        channel.forget_credentials()  # it points somewhere else now: the credential was for there
    channel.save()
    return channel


@transaction.atomic
def set_credentials(channel, user, values: dict) -> Channel:
    if not manages_channels(user):
        raise Forbidden("changing a channel's credential needs the right to manage channels")
    unknown = sorted(set(values) - set(SECRETS[channel.kind]))
    if unknown or not any(values.values()):
        raise Invalid(
            f"a {channel.kind} channel's credential is {', '.join(SECRETS[channel.kind]) or 'none'}",
            details=_detail("credentials", ", ".join(unknown) or "empty"),
        )
    channel.set_credentials(values)
    channel.last_error = ""
    channel.save()
    return channel


@transaction.atomic
def rotate_credentials(**_signal) -> int:
    """Every channel's credential and pending OAuth code under the AI layer's first key, for `manage.py
    rotate_ai_credentials` (it sends `ai.crypto.credentials_rotated` in its transaction). One no key can read stops
    the rotation, naming the channel, before anything is written."""
    rows = list(Channel.objects.exclude(credential_encrypted="", pending_encrypted=""))
    fresh = []
    for channel in rows:
        try:
            fresh.append(
                [crypto.encrypt(crypto.decrypt(v)) for v in (channel.credential_encrypted, channel.pending_encrypted)]
            )
        except crypto.InvalidToken as e:
            raise NotConfigured(
                f"the credential of the channel {channel.name!r} was encrypted with a key that is gone: add that key to "
                "AI_CREDENTIAL_KEYS (or its SECRET_KEY to SECRET_KEY_FALLBACKS) and rotate again, or connect the "
                "channel again"
            ) from e
    for channel, (credential, pending) in zip(rows, fresh, strict=True):
        Channel.objects.filter(pk=channel.pk).update(credential_encrypted=credential, pending_encrypted=pending)
    return len(rows)


def disconnect(channel, user) -> Channel:
    if not manages_channels(user):
        raise Forbidden("disconnecting a channel needs the right to manage channels")
    channel.forget_credentials()
    channel.armed = False
    channel.save()
    return channel


def linkedin_app() -> tuple[str, str]:
    return settings.LINKEDIN_CLIENT_ID, settings.LINKEDIN_CLIENT_SECRET


def start_connect(channel, user, redirect_uri: str) -> dict:
    """The consent URL for the account's owner, with a fresh `state` and a PKCE verifier the caller keeps for this
    browser session (and nowhere else) until LinkedIn comes back."""
    if not manages_channels(user):
        raise Forbidden("connecting a channel needs the right to manage channels")
    if channel.kind != Kind.LINKEDIN:
        raise Invalid("only a LinkedIn channel connects through LinkedIn's consent screen; set the others' credential")
    client_id, client_secret = linkedin_app()
    if not client_id or not client_secret:
        raise Conflict(
            "set LINKEDIN_CLIENT_ID and LINKEDIN_CLIENT_SECRET for the platform before connecting an account"
        )
    state, verifier = oauth.new_state(), oauth.new_verifier()
    author_type = plan.author_type(channel.setting("author")) or "organization"
    scopes = channel.setting("scopes") or oauth.scopes_for(author_type)
    url = oauth.OAuth(client_id, client_secret).authorize_url(
        redirect_uri=redirect_uri, state=state, scopes=list(scopes), code_challenge=oauth.challenge(verifier)
    )
    return {"url": url, "state": state, "verifier": verifier}


@transaction.atomic
def finish_connect(channel, *, code: str, verifier: str, redirect_uri: str) -> Channel:
    """LinkedIn came back with a code: keep it (encrypted) for the worker, which exchanges it."""
    from .tasks import exchange_code

    if not code:
        raise Invalid("LinkedIn sent no authorization code")
    channel.set_pending({"code": code, "verifier": verifier, "redirect_uri": redirect_uri})
    channel.last_error = ""
    channel.save(update_fields=["pending_encrypted", "last_error", "updated_at"])
    transaction.on_commit(lambda: exchange_code.delay(channel.pk))
    return channel


def exchange(channel) -> Channel:
    """In the worker: the code for a token, stored encrypted; who it is, when `openid` was granted."""
    pending = channel.pending()
    if not pending:
        return channel
    client_id, client_secret = linkedin_app()
    try:
        flow = oauth.OAuth(client_id, client_secret)
        token = flow.exchange(
            code=pending["code"], redirect_uri=pending["redirect_uri"], code_verifier=pending["verifier"]
        )
        account = ""
        if "openid" in token.scopes:
            account = oauth.member(_client(channel, token.access_token))["name"]
    except (LinkedInError, ValueError) as e:
        Channel.objects.filter(pk=channel.pk).update(pending_encrypted="", last_error=f"LinkedIn: {e}"[:1000])
        return channel
    channel.set_pending(None)
    channel.set_credentials({"access_token": token.access_token, "refresh_token": token.refresh_token or ""})
    channel.expires_at, channel.refresh_expires_at = token.expires_at, token.refresh_expires_at
    channel.scopes, channel.account, channel.last_error = token.scopes, account or channel.account, ""
    channel.save()
    return channel


def linkedin_credentials(channel) -> Credentials:
    """The channel's token, or — with none stored — the environment's (LINKEDIN_ACCESS_TOKEN …), as the Rails CMS
    fell back; the app's id and secret are the deployment's."""
    stored = channel.credentials()
    client_id, client_secret = linkedin_app()
    if stored:
        return Credentials(stored.get("access_token", ""), stored.get("refresh_token", ""), client_id, client_secret)
    env = Credentials.from_env(os.environ)
    return Credentials(
        env.access_token, env.refresh_token, client_id or env.client_id, client_secret or env.client_secret
    )


def _client(channel, token):
    from .linkedin import Client

    return Client(token, api_version=channel.setting("api_version", plan.DEFAULT_API_VERSION))


def session_for(channel) -> Session:
    def keep(token):
        """A refreshed token replaces the stored one, so the next run does not refresh again."""
        stored = channel.credentials()
        if stored:
            channel.set_credentials({**stored, "access_token": token.access_token})
            channel.expires_at = token.expires_at
            channel.save(update_fields=["credential_encrypted", "expires_at", "connected_at", "updated_at"])

    return Session(
        linkedin_credentials(channel),
        api_version=channel.setting("api_version", plan.DEFAULT_API_VERSION),
        on_refresh=keep,
    )


def check(channel) -> Channel:
    """In the worker: ask the target whether the credential works, and who it publishes as."""
    from .transports import github_check, wordpress_check

    now = timezone.now()
    try:
        if channel.kind == Kind.LINKEDIN:
            report = check_linkedin(channel)
        elif channel.kind == Kind.WORDPRESS:
            report = wordpress_check(channel, channel.credentials())
        elif channel.kind == Kind.GITHUB_PR:
            report = github_check(channel, channel.credentials())
        else:
            confirmed = channel.newsletter.subscribers.filter(status="confirmed").count() if channel.newsletter else 0
            report = {
                "ok": channel.newsletter is not None,
                "account": channel.newsletter.name if channel.newsletter else "",
                "notes": [f"{confirmed} confirmed subscriber(s)"],
            }
    except (TransportError, LinkedInError) as e:
        report = {"ok": False, "problems": [str(e)]}
    problems = "; ".join(report.get("problems", []))
    Channel.objects.filter(pk=channel.pk).update(
        checked_at=now, last_check=report, last_error=problems[:1000], account=report.get("account") or channel.account
    )
    channel.refresh_from_db()
    return channel


def check_linkedin(channel) -> dict:
    creds = linkedin_credentials(channel)
    if not (creds.access or creds.refreshable):
        return {"ok": False, "problems": ["no LinkedIn credential: connect the channel"]}
    session = session_for(channel)
    out = {"ok": True, "problems": [], "notes": []}
    if creds.app:
        info = session.oauth().introspect(session.client().token)
        days = info.days_left()
        out.update(
            active=info.active,
            scopes=info.scopes,
            days_left=days,
            expires_at=info.expires_at.isoformat() if info.expires_at else None,
        )
        if not info.active:
            out["problems"].append(f"the token is {info.status or 'not active'}")
        elif days is not None and days <= 7:
            out["problems"].append(f"the token expires in {days} day(s)")
    author = channel.setting("author")
    try:
        if plan.author_type(author) == "person":
            out["account"] = session.run(oauth.member)["name"]
        elif author:
            session.run(lambda client: posts.by_author(client, author=author, count=1))
        out["probe"] = "ok"
    except HTTPError as e:
        if e.forbidden:
            out["notes"].append(f"the token authenticates but may not read {author}'s posts; publishing may still work")
        else:
            out["problems"].append(str(e))
    out["ok"] = not out["problems"]
    return out


# ── the canonical URL ───────────────────────────────────────────────────────


def site_root_of(page):
    from cms.models import SiteRootPage

    root = page.get_ancestors(inclusive=True).type(SiteRootPage).last()
    return root.specific if root else None


def jekyll_config_of(root) -> dict:
    """The site's `_config.yml` from its checkout when the platform can read it (permalinks need its styles,
    collections and defaults), else the parts the importer kept."""
    from importers.jekyll import read_config

    if root.source_root:
        folder = (Path(settings.REPO_ROOT) / root.source_root).resolve()
        if folder.is_relative_to(Path(settings.REPO_ROOT).resolve()) and (folder / "_config.yml").is_file():
            try:
                return read_config(folder)
            except (OSError, ValueError):
                pass  # an unreadable checkout falls back to what the import kept
    return dict(root.jekyll_config or {})


def canonical_url(page) -> str | None:
    """The URL the page is read at — what every lane keys the ledger by. A Jekyll-backed site's page has the URL
    Jekyll gives its file (`permalink.path_for`, as the site's own lane computes it); any other page, Wagtail's."""
    from cms.models import ArticlePage, CollectionPage
    from exporters.jekyll import front_matter_for
    from exporters.jekyll import path_for as file_path

    page = page.specific
    stated = (page.front_matter or {}).get("canonical_url") if hasattr(page, "front_matter") else None
    if isinstance(stated, str) and re.match(r"https?://", stated):
        return stated
    root = site_root_of(page)
    config = jekyll_config_of(root) if root is not None else {}
    base = str(config.get("url") or "").rstrip("/")
    if root is not None and base and page.pk != root.pk:
        source = str(config.get("source") or ".").strip("/")
        rel = page.legacy_path or file_path(page, root)
        if source not in ("", ".") and rel.startswith(source + "/"):
            rel = rel[len(source) + 1 :]
        parent = page.get_parent().specific
        collection = parent.collection if isinstance(parent, CollectionPage) else ""
        kind = "page" if not collection else "post" if collection == "posts" else "document"
        data = front_matter_for(page)
        date = getattr(page, "date", None)
        date_raw = str(data.get("date") or (f"{date:%Y-%m-%d}" if isinstance(page, ArticlePage) and date else ""))
        entry = permalink.Entry(
            source_relative=rel, kind=kind, collection=collection, data=data, date_raw=date_raw, date=date
        )
        path = permalink.path_for(config, entry)
        return f"{base}{str(config.get('baseurl') or '').rstrip('/')}{path}" if path else None
    try:
        url = page.get_full_url()
    except (AttributeError, ValueError):
        return None
    return url if url and re.match(r"https?://", url) else None


def default_commentary(page, limit: int = 3) -> str:
    """The site's lane's seed (`lane.site.default_commentary`): the sub-title, excerpt or description as the
    hook, then up to three hashtags from the tags — never the title, which the card already shows."""
    from exporters.jekyll import front_matter_for

    from .lane.site import default_commentary as seed

    page = page.specific
    data = front_matter_for(page)
    tags = [t.name for t in page.tags.all()] if hasattr(page, "tags") else data.get("tags") or []
    description = page.search_description or str(data.get("description") or "")
    return seed(SimpleNamespace(data=data, description=description, tags=list(tags)), limit)


# ── the guard ───────────────────────────────────────────────────────────────


def guard(text: str, channel) -> list[dict]:
    """The brand guard (suggestions/guard.py, the extension's rules, with the active brand rules and the channel's
    site's own), and for LinkedIn its own limit once the text is escaped."""
    findings = guard_text(text or "", extra_patterns(channel.site))
    if channel.kind == Kind.LINKEDIN:
        escaped = posts.commentary_length(text)
        if escaped > plan.COMMENTARY_MAX and len(text or "") <= 3000:
            message = f"commentary is {escaped} chars once escaped for LinkedIn (max {plan.COMMENTARY_MAX})"
            findings.insert(len(findings) - 1, {"level": "error", "message": message})
    return findings


def guard_errors(findings) -> list[str]:
    return [f["message"] for f in findings if f["level"] == "error"]


# ── composing ───────────────────────────────────────────────────────────────


@transaction.atomic
def compose(
    channel,
    *,
    user,
    page=None,
    story=None,
    commentary=None,
    title=None,
    description=None,
    kind="article",
    origin=DistributionPost.Origin.PERSON,
    run=None,
) -> DistributionPost:
    """A draft post — never published, never approved: a person approves it."""
    if story is not None:
        page = story.page or page
        if story.desk.site_id != channel.site_id:
            raise Invalid(
                "the story belongs to another site than the channel's", details=_detail("story", "other site")
            )
    if kind == "article" and page is None:
        raise Invalid(
            "an article shares a page: pick one (or a story with a page)", details=_detail("page", "required")
        )
    if channel.kind == Kind.EMAIL and story is None:
        raise Invalid("an email channel sends newsroom stories: pick a story", details=_detail("story", "required"))
    if kind == "update" and channel.kind != Kind.LINKEDIN:
        raise Invalid("only LinkedIn takes a text update", details=_detail("kind", "linkedin only"))
    if page is not None:
        page = page.specific
        if origin == DistributionPost.Origin.PERSON and not may_compose(page, user):
            raise PermissionDenied("you may not edit this page, so you may not distribute it")
        site = page.get_site()
        if site is not None and site.pk != channel.site_id:
            raise Invalid("the page belongs to another site than the channel's", details=_detail("page", "other site"))
    elif origin == DistributionPost.Origin.PERSON and not may_manage(user):
        raise PermissionDenied("a text update is the channel managers'")
    link = (canonical_url(page) or "") if page is not None else ""
    if page is not None:
        if (taken := find_entry(channel, link)) and taken.urn:
            raise Conflict(f"this page was already distributed to {channel.name} as {taken.urn}")
    if commentary is None or not str(commentary).strip():
        commentary = default_commentary(page) if page is not None else ""
    post = DistributionPost(
        channel=channel,
        page=page,
        story=story,
        kind=kind,
        origin=origin,
        run=run,
        created_by=user if user is not None and not user.username.startswith("agent:") else None,
        title=(title if title is not None else (story.headline if story is not None else page.title if page else ""))[
            :255
        ],
        description=description if description is not None else (getattr(page, "search_description", "") or ""),
        commentary=str(commentary),
        link=link,
    )
    post.guard = guard(post.commentary, channel)
    post.save()
    return post


@transaction.atomic
def edit(post, user, **fields) -> DistributionPost:
    """A change to an approved post's text returns it to draft: approval is of the exact text."""
    post = DistributionPost.objects.select_for_update().get(pk=post.pk)
    if not may_compose(post, user):
        raise PermissionDenied("you may not edit this page, so you may not change its posts")
    if post.status in (DistributionPost.Status.PUBLISHING, *FINAL):
        raise Conflict(f"a {post.status} post does not change")
    changed = [name for name in EDITABLE if name in fields and fields[name] != getattr(post, name)]
    if "kind" in changed and fields["kind"] == "update" and post.channel.kind != Kind.LINKEDIN:
        raise Invalid("only LinkedIn takes a text update", details=_detail("kind", "linkedin only"))
    for name in changed:
        setattr(post, name, fields[name])
    if changed:
        post.guard = guard(post.commentary, post.channel)
        if post.status == DistributionPost.Status.APPROVED:
            post.status, post.approved_by, post.approved_at = DistributionPost.Status.DRAFT, None, None
        post.save()
    return post


@transaction.atomic
def approve(post, user) -> DistributionPost:
    post = DistributionPost.objects.select_for_update().get(pk=post.pk)
    if not may_publish(post, user):
        raise PermissionDenied("approving a post is the right of someone who may publish its page")
    if post.status != DistributionPost.Status.DRAFT:
        raise Conflict(f"the post is already {post.status}")
    post.guard = guard(post.commentary, post.channel)
    if errors := guard_errors(post.guard):
        post.save(update_fields=["guard", "updated_at"])
        raise Conflict(f"brand guard: {'; '.join(errors)}")
    post.status, post.approved_by, post.approved_at = DistributionPost.Status.APPROVED, user, timezone.now()
    post.reason = ""
    post.save()
    return post


@transaction.atomic
def reject(post, user, reason: str = "") -> DistributionPost:
    post = DistributionPost.objects.select_for_update().get(pk=post.pk)
    if not may_publish(post, user):
        raise PermissionDenied("rejecting a post is the right of someone who may publish its page")
    if post.status in (DistributionPost.Status.PUBLISHING, *FINAL):
        raise Conflict(f"a {post.status} post is not rejected")
    post.status, post.reason = DistributionPost.Status.REJECTED, reason
    post.save()
    return post


# ── the gates ───────────────────────────────────────────────────────────────


@dataclass
class Preview:
    post: DistributionPost
    blockers: list
    payload: dict | None = None
    notes: list = field(default_factory=list)

    @property
    def problems(self):
        return gates.problems(self.blockers)


class AbsentLedger:
    """A ledger file a channel names that cannot be reached from here — the site's checkout is not on this machine,
    or the path leaves it. Refused like an unreadable file, never read as "nothing published"."""

    readable = False

    def __init__(self, problem: str):
        self.problem = problem

    def entry(self, key):
        return None

    def record(self, *args, **kwargs):
        raise LedgerError(self.problem)

    mark_unconfirmed = record


def site_ledger(channel) -> Ledger | AbsentLedger | None:
    """The site's own ledger file, where the extension and the site's CI record what they published — None when the
    channel names none."""
    relative = channel.setting("ledger_file")
    if not relative:
        return None
    source_root = getattr(channel.site.root_page.specific, "source_root", "")
    base = (Path(settings.REPO_ROOT) / source_root).resolve() if source_root else None
    if base is None or not base.is_dir():
        return AbsentLedger(f"the site's checkout is not here to read its ledger file {relative}")
    path = (base / relative).resolve()
    if not path.is_relative_to(base):
        return AbsentLedger(f"the ledger file {relative} is outside the site's checkout")
    return Ledger(path)


def find_entry(channel, key) -> LedgerEntry | None:
    """What the ledger knows about `key`: the channel's row, else the site's ledger file's entry (copied in)."""
    if not key:
        return None
    row = LedgerEntry.objects.filter(channel=channel, key=key).first()
    if row is not None:
        return row
    ledger = site_ledger(channel)
    entry = ledger.entry(key) if ledger is not None and ledger.readable else None
    if not entry:
        return None
    return LedgerEntry(
        channel=channel,
        key=key,
        urn=urn_of(entry) or "",
        state="published" if urn_of(entry) else str(entry.get("state") or "unconfirmed"),
        attempted_at=None,
        error=str(entry.get("error") or ""),
    )


def preview(post, *, live: bool = True) -> Preview:
    """Every reason the post may not go now, in the gates' order — no network, no write."""
    channel, blockers, payload = post.channel, [], None
    if not channel.connected:
        blockers.append(Blocker("config_error", f"{channel.name} is not connected"))
    if channel.kind == Kind.WORDPRESS and not (channel.setting("url") and channel.setting("username")):
        blockers.append(Blocker("config_error", "the WordPress channel needs its site address and username"))
    if channel.kind == Kind.GITHUB_PR and not channel.setting("repo"):
        blockers.append(Blocker("config_error", "the GitHub channel needs its repository"))
    if channel.kind == Kind.EMAIL and channel.newsletter is None:
        blockers.append(Blocker("config_error", "the email channel has no newsletter"))
    if channel.kind == Kind.LINKEDIN:
        author = channel.setting("author")
        if plan.author_type(author) is None:
            blockers.append(
                Blocker("no_author", "no LinkedIn author on the channel (urn:li:organization:… or urn:li:person:…)")
            )
        elif post.kind == "update":
            payload = posts.text_payload(author=author, commentary=post.commentary)
        elif post.link and post.title.strip():
            try:
                payload = posts.article_payload(
                    author=author,
                    commentary=post.commentary,
                    source=post.link,
                    title=post.title,
                    description=post.description,
                )
            except ValueError as e:
                blockers.append(Blocker("source_missing", str(e)))
    page = post.page.specific if post.page_id else None
    if post.kind == "article":
        if page is None:
            blockers.append(Blocker("source_missing", "the page is gone"))
        elif not page.live:
            blockers.append(Blocker("source_missing", "the page is not live: publish it first"))
        elif not post.link:
            blockers.append(Blocker("source_missing", "the page has no public URL"))
        elif channel.kind == Kind.LINKEDIN and not (post.title.strip() and post.description.strip()):
            blockers.append(Blocker("source_missing", "the link card needs a title and a description"))
    elif not post.commentary.strip():
        blockers.append(Blocker("source_missing", "an update needs its text"))
    if channel.kind == Kind.EMAIL and (post.story is None or not post.story.is_published):
        blockers.append(Blocker("source_missing", "email sends a published story: the story is not published"))
    if errors := guard_errors(guard(post.commentary, channel)):
        blockers.append(Blocker("guard_error", f"brand guard: {'; '.join(errors)}"))
    ledger = site_ledger(channel)
    entry = find_entry(channel, post.ledger_key) if (ledger is None or ledger.readable) else None
    if ledger is not None and not ledger.readable:
        problem = (
            ledger.problem
            if isinstance(ledger, AbsentLedger)
            else f"{channel.setting('ledger_file')} is not valid JSON — fix it first"
        )
        blockers.append(Blocker("ledger_unreadable", problem))
    elif entry is not None and entry.urn:
        blockers.append(Blocker("already_published", f"already published as {entry.urn}"))
    elif entry is not None:
        blockers.append(
            Blocker(
                "publish_unconfirmed",
                (
                    f"an earlier attempt may have published this ({entry.error or 'no answer'}): check {channel.name}, then "
                    "record the post if it did, or publish again with force if it did not"
                ),
            )
        )
    if post.status not in (DistributionPost.Status.APPROVED, DistributionPost.Status.PUBLISHING):
        blockers.append(Blocker("status_not_accepted", f"the post is {post.status}: a person approves it first"))
    if not channel.armed:
        blockers.append(
            Blocker("publish_disabled", f"publishing to {channel.name} is not armed (the channel's setting)")
        )
    elif not armed_for_kind(channel.kind):
        variable = {
            "linkedin": "ZER0_LINKEDIN_PUBLISH",
            "wordpress": "ZER0_WORDPRESS_PUBLISH",
            "github_pr": "ZER0_GITHUB_PR_PUBLISH",
            "email": "ZER0_EMAIL_PUBLISH",
        }[channel.kind]
        blockers.append(
            Blocker(
                "publish_disabled", f"this deployment does not publish to {channel.get_kind_display()} ({variable}=1)"
            )
        )
    if channel.kind == Kind.LINKEDIN:
        creds = linkedin_credentials(channel)
        if not (creds.access or creds.refreshable):
            blockers.append(Blocker("no_credential", "no LinkedIn token: connect the channel"))
    elif channel.kind in (Kind.WORDPRESS, Kind.GITHUB_PR) and not channel.credentials():
        blockers.append(Blocker("no_credential", f"no credential for {channel.name}: set it on the channel"))
    found = gates.ordered(blockers)
    return Preview(post, found if live else [b for b in found if b.kind not in gates.LIVE_ONLY], payload)


@transaction.atomic
def request_publish(post, user, *, force: bool = False, agent: bool = False) -> DistributionPost:
    """A person asks for the post to go — or an agent, through `distribution.publish`, whose call the registry
    has already held to the `auto` policy and the page's publish permission, and which never forces: every gate now
    (the worker asks again), then the work is queued. Either way only a post a person approved goes."""
    from .tasks import publish_post

    post = DistributionPost.objects.select_for_update().get(pk=post.pk)
    if agent:
        force = False
    elif not may_publish(post, user):
        raise PermissionDenied("publishing a post is the right of someone who may publish its page")
    if post.status == DistributionPost.Status.PUBLISHING and post.attempted_at is not None:
        raise Conflict("it is being sent now: wait for it to finish", code="distribution.sending")
    if post.status == DistributionPost.Status.FAILED:
        post.status = (
            DistributionPost.Status.APPROVED
        )  # a failed post was approved; trying again is not re-approving it
    blockers = gates.lifted(preview(post).blockers, force=force)
    if blockers:
        raise Conflict("; ".join(f"{b.kind}: {b.message}" for b in blockers), code="distribution.blocked")
    post.status, post.published_by, post.force, post.error = DistributionPost.Status.PUBLISHING, user, force, ""
    post.attempted_at = None  # a new attempt: `deliver` claims it before anything is sent
    post.save()
    transaction.on_commit(lambda: publish_post.delay(post.pk))
    return post


def deliver(post_id: int) -> DistributionPost:
    """In the worker: the gates again, then the channel's transport, then the ledger. The attempt is claimed
    (`attempted_at`, committed) before anything is sent, so a second delivery of one request — a task redelivered
    after its worker died (acks are late), or a duplicate — never sends the post twice: within the send's time limit
    it leaves the post to the worker that claimed it; after that, that worker is gone and the post may exist, so it
    is ledgered unconfirmed for a person to check."""
    from .tasks import SEND_TIME_LIMIT

    with transaction.atomic():
        post = DistributionPost.objects.select_for_update().select_related("channel").get(pk=post_id)
        if post.status != DistributionPost.Status.PUBLISHING:
            return post
        if post.attempted_at is not None:
            if (timezone.now() - post.attempted_at).total_seconds() < SEND_TIME_LIMIT:
                return post
            message = (
                "an earlier attempt to send this never finished, so it may have published: check, then record the "
                "post if it did, or publish again with force if it did not"
            )
            _doubt(post, message)
            post.status, post.error = DistributionPost.Status.FAILED, message
            post.save()
            return post
        blockers = gates.lifted(preview(post).blockers, force=post.force)
        if blockers:
            post.status, post.error = DistributionPost.Status.APPROVED, "; ".join(b.message for b in blockers)
            post.save()
            return post
        post.attempted_at = timezone.now()
        post.save(update_fields=["attempted_at", "updated_at"])
    try:
        external_id, url, extra = _send(post)
    except (TransportError, LinkedInError, LedgerError, ValueError) as e:
        message = getattr(e, "message", None) or str(e)
        if LedgerEntry.objects.filter(channel=post.channel, key=post.ledger_key, urn="").exists():
            message += " — it may have published: the ledger marks it unconfirmed until a person checks"
        DistributionPost.objects.filter(pk=post.pk).update(
            status=DistributionPost.Status.FAILED,
            error=message[:2000],
            external_url=getattr(e, "url", "") or "",
            updated_at=timezone.now(),
        )
        post.refresh_from_db()
        return post
    with transaction.atomic():
        entry = record(post, external_id, **extra)
        post.status, post.external_id, post.external_url = DistributionPost.Status.PUBLISHED, external_id, url
        post.published_at, post.error, post.force = timezone.now(), "", False
        post.save()
        log.info("distribution: post %s published to %s as %s", post.public_id, post.channel_id, entry.urn)
    return post


def _send(post) -> tuple[str, str, dict]:
    from .transports import email_publish, github_publish, wordpress_publish

    channel = post.channel
    page = post.page.specific if post.page_id else None
    if channel.kind == Kind.WORDPRESS:
        try:
            external_id, url = wordpress_publish(channel, channel.credentials(), post, page)
        except TransportError as e:
            if e.doubt:
                _doubt(post, e.message)
            raise
        return f"wp:{external_id}", url, {}
    if channel.kind == Kind.GITHUB_PR:
        number, url = github_publish(channel, channel.credentials(), post, page)
        return f"pr:{channel.setting('repo')}#{number}", url, {}
    if channel.kind == Kind.EMAIL:
        issue, _ = email_publish(channel, post, post.published_by)
        return f"issue:{issue}", "", {}
    return _send_linkedin(post, page)


def _send_linkedin(post, page):
    from .linkedin.posts import uploadable

    channel = post.channel
    preview_ = preview(post)
    image = None
    if page is not None and getattr(page, "preview_image", None) is not None:
        file = page.preview_image.file
        ok, reason = uploadable(file.name, page.preview_image.file_size or 0)
        if ok:
            with file.open("rb") as handle:
                image = (file.name, handle.read())
        else:
            post.notes = [*post.notes, f"preview image not uploadable: {reason}"]
    urn, image_urn = send_post(
        session_for(channel),
        author=channel.setting("author"),
        payload=preview_.payload,
        image=image,
        notes=post.notes,
        mark_unconfirmed=lambda m: _doubt(post, m),
    )
    return urn, posts.feed_url(urn), {"image_urn": image_urn or ""}


def _doubt(post, message: str) -> None:
    """The target may have acted: an unconfirmed entry, in the channel's rows and the site's file."""
    key, channel = post.ledger_key, post.channel
    if not LedgerEntry.objects.filter(channel=channel, key=key).exclude(urn="").exists():  # a recorded post stays
        LedgerEntry.objects.update_or_create(
            channel=channel,
            key=key,
            defaults={
                "urn": "",
                "state": "unconfirmed",
                "attempted_at": timezone.now(),
                "error": message[:300],
                "kind": post.kind,
                "post": post,
                "author": channel.setting("author"),
                "source_file": _source_file(post),
            },
        )
    ledger = site_ledger(channel)
    if ledger is not None and ledger.readable:
        from .ledger import unconfirmed_entry

        try:
            ledger.mark_unconfirmed(
                key,
                unconfirmed_entry(
                    error=message,
                    kind=post.kind,
                    target=channel.kind,
                    author=channel.setting("author") or None,
                    source_file=_source_file(post) or None,
                ),
            )
        except (OSError, LedgerError):
            log.warning("distribution: could not mark %s unconfirmed in the site's ledger file", key)


def _source_file(post) -> str:
    return getattr(post.page.specific, "legacy_path", "") if post.page_id else ""


def record(post, urn: str, *, image_urn: str = "", now=None) -> LedgerEntry:
    """What was published, under its key: the channel's row (a re-publish replaces it) and the site's ledger file."""
    from .ledger import entry_for

    channel, now = post.channel, now or timezone.now()
    entry, _ = LedgerEntry.objects.update_or_create(
        channel=channel,
        key=post.ledger_key,
        defaults={
            "urn": urn,
            "state": "published",
            "posted_at": now,
            "attempted_at": None,
            "error": "",
            "kind": post.kind,
            "author": channel.setting("author"),
            "source_file": _source_file(post),
            "image_urn": image_urn,
            "post": post,
        },
    )
    ledger = site_ledger(channel)
    if ledger is not None:
        try:
            ledger.record(
                post.ledger_key,
                entry_for(
                    urn=urn,
                    kind=post.kind,
                    target=channel.kind,
                    author=channel.setting("author") or None,
                    source_file=_source_file(post) or None,
                    image_urn=image_urn or None,
                    now=now,
                ),
            )
        except (OSError, LedgerError) as e:
            # The post exists at the target: the row above must survive a file that cannot take it, or the
            # platform would send the post again. The site's lane keeps its own copy (Download gives this one).
            log.warning("distribution: %s is recorded here but not in the site's ledger file: %s", post.ledger_key, e)
    return entry


@transaction.atomic
def record_by_hand(post, user, urn: str) -> DistributionPost:
    """A person found the post at the target — after an unconfirmed attempt, or one made by hand — and records it."""
    post = DistributionPost.objects.select_for_update().get(pk=post.pk)
    if not may_publish(post, user):
        raise PermissionDenied("recording a post is the right of someone who may publish its page")
    if post.channel.kind == Kind.LINKEDIN and not plan.POST_URN.match(urn or ""):
        raise Invalid("not a LinkedIn post URN (urn:li:share:… or urn:li:ugcPost:…)", details=_detail("urn", "invalid"))
    if not str(urn or "").strip():
        raise Invalid("say what it was published as", details=_detail("urn", "required"))
    record(post, urn)
    post.status, post.external_id, post.published_at, post.error = (
        DistributionPost.Status.PUBLISHED,
        urn,
        timezone.now(),
        "",
    )
    if post.channel.kind == Kind.LINKEDIN:
        post.external_url = posts.feed_url(urn)
    post.save()
    return post


# ── the ledger as a file ────────────────────────────────────────────────────

MODELLED = {
    "linkedin_urn",
    "urn",
    "posted_at",
    "type",
    "target",
    "author",
    "source_file",
    "image_urn",
    "state",
    "attempted_at",
    "error",
}


def _stamp(value):
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ") if value else None


def entry_dict(row: LedgerEntry) -> dict:
    """A row as the file holds it — the shape the extension and every lane write."""
    out = dict(row.extra or {})
    if row.urn:
        out.update(urn=row.urn, posted_at=_stamp(row.posted_at), type=row.kind, target=row.channel.kind)
        if row.channel.kind == Kind.LINKEDIN:
            out["linkedin_urn"] = row.urn
        for key in ("author", "source_file", "image_urn"):
            if getattr(row, key):
                out[key] = getattr(row, key)
    else:
        out.update(
            state="unconfirmed",
            attempted_at=_stamp(row.attempted_at),
            error=row.error,
            type=row.kind,
            target=row.channel.kind,
        )
        for key in ("author", "source_file"):
            if getattr(row, key):
                out[key] = getattr(row, key)
    return {k: v for k, v in out.items() if v is not None}


def ledger_file(channel) -> str:
    return serialize({row.key: entry_dict(row) for row in channel.ledger.select_related("channel")})


def _parse_stamp(value):
    from django.utils.dateparse import parse_datetime

    parsed = parse_datetime(str(value)) if value else None
    return parsed if parsed is None or parsed.tzinfo else parsed.replace(tzinfo=UTC)


@transaction.atomic
def import_ledger(channel, user, text: str) -> dict:
    """Read a ledger file's entries in (the extension's, CI's, the Ruby lane's): what another lane published is
    then never published again from here. A row this channel already has a URN for is kept."""
    if not manages_channels(user):
        raise Forbidden("importing a ledger needs the right to manage channels")
    try:
        data = json.loads(text)
    except ValueError as e:
        raise Invalid(f"the ledger is not valid JSON: {e}") from e
    if not isinstance(data, dict):
        raise Invalid("a ledger is a JSON object keyed by URL")
    added = kept = skipped = 0
    for key, entry in data.items():
        if key.startswith("_") or not isinstance(entry, dict):
            skipped += 1
            continue
        existing = LedgerEntry.objects.filter(channel=channel, key=key).first()
        if existing is not None and existing.urn:
            kept += 1
            continue
        urn = urn_of(entry) or ""
        LedgerEntry.objects.update_or_create(
            channel=channel,
            key=key,
            defaults={
                "urn": urn,
                "state": "published" if urn else "unconfirmed",
                "kind": str(entry.get("type") or "article"),
                "posted_at": _parse_stamp(entry.get("posted_at")),
                "attempted_at": _parse_stamp(entry.get("attempted_at")),
                "error": str(entry.get("error") or ""),
                "author": str(entry.get("author") or ""),
                "source_file": str(entry.get("source_file") or ""),
                "image_urn": str(entry.get("image_urn") or ""),
                "extra": {k: v for k, v in entry.items() if k not in MODELLED},
            },
        )
        added += 1
    return {"added": added, "kept": kept, "skipped": skipped}


# ── statistics ──────────────────────────────────────────────────────────────


def ingest_statistics(channel, *, today=None) -> int:
    """Aggregate counts for the channel's own LinkedIn posts, one row per post a day; nothing about who engaged."""
    if channel.kind != Kind.LINKEDIN:
        return 0
    author = channel.setting("author")
    rows = [
        r
        for r in channel.ledger.filter(state="published")
        if plan.POST_URN.match(r.urn) and (not r.author or r.author == author)
    ]
    if not rows or plan.author_type(author) is None:
        return 0
    urns = [r.urn for r in rows]

    def read(client):
        if plan.author_type(author) == "organization":
            return statistics.for_organization(client, organization=author, urns=urns)
        return {urn: statistics.for_member_post(client, urn=urn) for urn in urns}

    counts = session_for(channel).run(read)
    day = today or timezone.localdate()
    for row in rows:
        if row.urn in counts:
            Statistic.objects.update_or_create(
                entry=row, day=day, defaults={**counts[row.urn], "fetched_at": timezone.now()}
            )
    return len(counts)


def get_visible(model, public_id, user):
    row = model.objects.visible_to(user).filter(public_id=public_id).first()
    if row is None:
        raise NotFound(f"no such {model._meta.verbose_name}")
    return row


def page_or_404(page_id, user):
    page = Page.objects.filter(pk=page_id).first()
    if page is None or not page.specific.permissions_for_user(user).can_edit():
        raise NotFound("no such page")
    return page.specific
