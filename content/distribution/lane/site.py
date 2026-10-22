"""A site's checkout, as the LinkedIn lane reads it: its settings (`zer0.json`
`distribution.linkedin`, then `_config.yml`, under the environment's
overrides), its pages (`catalog`), and a deterministic first draft of a share's
commentary (`default_commentary`).

The file layers describe; they never arm. Nothing a repository ships can make a
live publish happen: that takes `ZER0_LINKEDIN_PUBLISH=1` in the environment of
the process doing it, the rule the extension applies to `publishAllow` — a
cloned repository must not be able to switch on its own publishing. Paths in the
settings must stay inside the repository.

The pages are the Jekyll importer's reader (`importers.jekyll.documents`) with
what sharing needs on top — kind, date, liveness, the canonical URL through
`distribution.permalink`. When PLAN G4's `sites` catalog lands, this reader
becomes it.
"""

import os
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

import json5

from importers import frontmatter
from importers.jekyll import documents, read_config

from .. import permalink
from ..linkedin import plan
from ..linkedin.session import Credentials

DEFAULT_QUEUE = ".zer0/drafts/linkedin"
DEFAULT_LEDGER = ".zer0/ledger.json"
ACCEPTABLE = ("pending", "approved")
ARM_VARIABLE = "ZER0_LINKEDIN_PUBLISH"
# Set by the reusable workflow for a run on the default branch: the drafts it reads were merged, so a `pending` one
# counts as approved.
MERGED_VARIABLE = "ZER0_LINKEDIN_MERGED"
TRUTHY = ("1", "true", "yes", "on")
KEYS = (
    "author",
    "siteUrl",
    "apiVersion",
    "queue",
    "ledger",
    "acceptStatuses",
    "sources",
    "fallbackImage",
    "hashtagLimit",
    "bannedPatternsFile",
    "scopes",
)
ACRONYMS = {"ai", "mcp", "erp", "crm", "bi", "saas", "iaas", "smb", "it", "api", "ci", "cd", "kpi", "roi", "sql", "hr"}
HOOK_KEYS = ("sub-title", "subtitle", "excerpt")
DATED = re.compile(r"\A\d{2,4}-\d{1,2}-\d{1,2}-")


class ConfigError(Exception):
    """The site's settings cannot be used; the message says which and why."""


def truthy(value) -> bool:
    return str(value or "").strip().lower() in TRUTHY


def read_jsonc(path: Path):
    """zer0.json is JSONC (comments, trailing commas) — read by json5, a superset."""
    return json5.loads(path.read_text(encoding="utf-8").removeprefix("﻿"))


class Config:
    def __init__(self, root, env=None):
        try:
            self.root = Path(os.path.realpath(root))
        except OSError as e:
            raise ConfigError(f"{root} is not a directory") from e
        if not self.root.is_dir():
            raise ConfigError(f"{root} is not a directory")
        self.env = os.environ if env is None else env
        self.problems: list[tuple[str, str]] = []
        zer0 = self._read_zer0()
        block = (zer0.get("distribution") or {}).get("linkedin") if isinstance(zer0.get("distribution"), dict) else None
        self.block = block if isinstance(block, dict) else {}
        cms = zer0.get("cms") if isinstance(zer0.get("cms"), dict) else {}
        self.site_config = self._read_site_config()
        self._resolve(cms.get("root"))
        self._validate()

    # ── what a run asks ──────────────────────────────────────────────────────
    @property
    def configured(self) -> bool:
        return bool(self.block)

    @property
    def author_type(self):
        return plan.author_type(self.author)

    @property
    def credentials(self) -> Credentials:
        return Credentials.from_env(self.env)

    @property
    def publish_armed(self) -> bool:
        return truthy(self.env.get(ARM_VARIABLE))

    @property
    def merged(self) -> bool:
        return truthy(self.env.get(MERGED_VARIABLE))

    @property
    def publishable_statuses(self) -> list[str]:
        """`pending` in acceptStatuses means "a merge to the default branch is the approval", so it counts only
        where the environment says the run is on that branch; anywhere else a draft must be `approved`."""
        return list(self.accept_statuses) if self.merged else [s for s in self.accept_statuses if s != "pending"]

    def path(self, relative: str) -> Path:
        return self.root / relative

    @property
    def errors(self) -> list[str]:
        return [m for level, m in self.problems if level == "error"]

    @property
    def warnings(self) -> list[str]:
        return [m for level, m in self.problems if level == "warning"]

    # ── reading ──────────────────────────────────────────────────────────────
    def _read_zer0(self) -> dict:
        path = self.root / "zer0.json"
        if not path.is_file():
            return {}
        try:
            data = read_jsonc(path)
        except ValueError as e:
            self.problems.append(("error", f"zer0.json does not parse: {str(e).splitlines()[0]}"))
            return {}
        return data if isinstance(data, dict) else {}

    def _read_site_config(self) -> dict:
        if not (self.root / "_config.yml").is_file():
            return {}
        try:
            return read_config(self.root)
        except ValueError as e:
            self.problems.append(("error", f"_config.yml does not parse: {str(e).splitlines()[0]}"))
            return {}

    def _first(self, *values) -> str:
        return next((str(v).strip() for v in values if v is not None and str(v).strip()), "")

    def _resolve(self, cms_root):
        env, block, jekyll = self.env, self.block, self.site_config
        jekyll_linkedin = jekyll.get("linkedin") if isinstance(jekyll.get("linkedin"), dict) else {}
        url = str(jekyll.get("url") or "").strip()
        jekyll_url = f"{url.rstrip('/')}{str(jekyll.get('baseurl') or '').strip().rstrip('/')}" if url else None
        self.author = self._first(
            env.get("LINKEDIN_AUTHOR_URN"),
            env.get("LINKEDIN_ORG_URN"),
            block.get("author"),
            jekyll_linkedin.get("org_urn"),
        )
        self.site_url = self._first(env.get("LINKEDIN_BASE_URL"), block.get("siteUrl"), jekyll_url).rstrip("/")
        self.api_version = self._first(
            env.get("LINKEDIN_API_VERSION"), block.get("apiVersion"), plan.DEFAULT_API_VERSION
        )
        self.queue = self._confined(block.get("queue") or DEFAULT_QUEUE, "queue")
        self.ledger = self._confined(block.get("ledger") or DEFAULT_LEDGER, "ledger")
        accept = block.get("acceptStatuses")
        self.accept_statuses = [str(s).strip().lower() for s in (accept if isinstance(accept, list) else ["approved"])]
        self.sources = [str(s) for s in block.get("sources") or []]
        fallback = block.get("fallbackImage")
        self.fallback_image = self._confined(fallback, "fallbackImage") if fallback else None
        try:
            self.hashtag_limit = max(0, min(int(block.get("hashtagLimit", 3)), 10))
        except (TypeError, ValueError):
            self.hashtag_limit = 3
        bans = block.get("bannedPatternsFile")
        self.banned_patterns_file = self._confined(bans, "bannedPatternsFile") if bans else None
        self.scopes = [str(s) for s in block.get("scopes") or []]
        self.cms_root = self._confined(cms_root or ".cms", "cms.root")

    def _validate(self):
        def error(message):
            self.problems.append(("error", message))

        def warn(message):
            self.problems.append(("warning", message))

        for key in self.block:
            if key not in KEYS:
                warn(f"distribution.linkedin.{key} is not a setting (known: {', '.join(KEYS)})")
        if not self.author:
            warn("no LinkedIn author: set distribution.linkedin.author in zer0.json")
        elif self.author_type is None:
            error(f'author must be urn:li:organization:{{id}} or urn:li:person:{{id}}, got "{self.author}"')
        status = plan.version_status(self.api_version)
        messages = {
            "invalid": f'apiVersion must be YYYYMM, got "{self.api_version}"',
            "sunset": f"LinkedIn-Version {self.api_version} is past LinkedIn's twelve-month support window; LinkedIn rejects it",
            "future": f"LinkedIn-Version {self.api_version} is in the future",
        }
        if status in messages:
            error(messages[status])
        elif status == "aging":
            warn(
                f"LinkedIn-Version {self.api_version} leaves LinkedIn's support window within two months; bump apiVersion"
            )
        if not self.site_url:
            warn("no site URL: set url in _config.yml or distribution.linkedin.siteUrl — article shares need one")
        elif not re.match(r"https?://[^\s/]+", self.site_url):
            error(f'siteUrl must be an absolute http(s) URL, got "{self.site_url}"')
        for status in self.accept_statuses:
            if status not in ACCEPTABLE:
                error(f'acceptStatuses may hold pending and approved, not "{status}"')
        if not self.accept_statuses:
            error("acceptStatuses is empty — nothing could ever publish")
        elif "approved" not in self.accept_statuses:
            warn("acceptStatuses has no approved: nothing can publish outside a merged run on the default branch")

    def _confined(self, value, key) -> str:
        """A repository-relative path that stays inside the repository."""
        text = str(value or "").strip().replace("\\", "/")
        parts = text.split("/")
        if not text or text.startswith("/") or ".." in parts or re.match(r"[A-Za-z]:", text):
            raise ConfigError(f"distribution.linkedin.{key} must be a path inside the repository, got {value!r}")
        return os.path.normpath(text).replace(os.sep, "/")


# ── the pages ───────────────────────────────────────────────────────────────


@dataclass
class Entry(permalink.Entry):
    """A page of the site as the lane sees it."""

    relative: str = ""  # from the site root
    path: Path | None = None
    future: bool = False

    @property
    def title(self) -> str:
        title = self.data.get("title")
        if title not in (None, ""):
            return str(title)
        slug = permalink.filename_slug(PurePosixPath(self.source_relative).stem, self.kind)
        return " ".join(w.capitalize() for w in re.split(r"[-_]", slug)) if self.kind == "post" else slug

    @property
    def description(self) -> str:
        return str(self.data.get("description") or "")

    @property
    def preview(self) -> str:
        return str(self.data.get("preview") or self.data.get("image") or "")

    @property
    def tags(self) -> list[str]:
        value = self.data.get("tags")
        return [str(t) for t in value] if isinstance(value, list) else [] if value is None else [str(value)]

    @property
    def live(self) -> bool:
        draft = self.data.get("draft") in (True, "true", "1", 1)
        published = self.data.get("published") is not False
        return not draft and published and not self.future and str(self.data.get("status") or "") != "draft"


@dataclass
class Catalog:
    config: dict
    source: Path
    entries: list = field(default_factory=list)


def catalog(root: Path, *, now: datetime | None = None) -> Catalog:
    config = read_config(root) if (root / "_config.yml").is_file() else {}
    source = (root / str(config.get("source", "."))).resolve()
    now = now or datetime.now(UTC)
    entries = []
    for doc in documents(root, config):
        rel_source = doc.path.relative_to(source).as_posix()
        kind = "page" if doc.collection is None else "post" if doc.collection == "posts" else "document"
        match = DATED.match(PurePosixPath(rel_source).name) if kind == "post" else None
        raw = doc.front_matter.get("date")
        date_raw = str(raw) if raw is not None else (match.group(0).rstrip("-") if match else "")
        date = frontmatter.parse_date(date_raw) if date_raw else None
        entries.append(
            Entry(
                source_relative=rel_source,
                kind=kind,
                collection=doc.collection or "pages",
                data=doc.front_matter,
                date_raw=date_raw,
                date=date,
                relative=doc.rel,
                path=doc.path,
                future=bool(date and date > now),
            )
        )
    return Catalog(config=config, source=source, entries=entries)


# ── a first draft ───────────────────────────────────────────────────────────


def hashtags(tags, limit: int = 3) -> str:
    """`["mcp", "back-office", "ai"]` → `#MCP #BackOffice #AI`"""
    out = []
    for tag in list(tags or [])[:limit]:
        parts = [
            t.upper() if t.lower() in ACRONYMS else t.capitalize() for t in re.split(r"[\s_-]+", str(tag).strip()) if t
        ]
        if parts:
            out.append("#" + "".join(parts))
    return " ".join(out)


def default_commentary(entry, limit: int = 3) -> str:
    """The page's sub-title (or excerpt, or description) as the hook — never the title, which the card already
    shows — then up to three hashtags from its tags: byte for byte the Python publisher's and the Ruby lane's seed."""
    data = entry.data if isinstance(entry.data, dict) else {}
    hook = next((data[k] for k in HOOK_KEYS if isinstance(data.get(k), str) and data[k]), None)
    hook = (hook or entry.description or "").strip()
    parts = [hook] if hook else []
    tags = hashtags(entry.tags, limit)
    if tags:
        parts.append(tags)
    return "\n\n".join(parts)[: plan.COMMENTARY_MAX]


def slug(source_relative: str) -> str:
    """A draft filename stem for a page: its slug without a date prefix."""
    stem = DATED.sub("", PurePosixPath(source_relative).stem, count=1)
    text = re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-")[:80].rstrip("-")
    return text or "post"
