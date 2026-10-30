"""Distribution's tables (TARGET.md § Distribution; PLAN G5).

| Model | What it is |
|---|---|
| `Channel` | where a site's content goes: a LinkedIn page or profile, a WordPress site, a GitHub repository (as pull requests), or one of the site's newsletters. Its credential is encrypted at rest (`ai.crypto`, the AI layer's MultiFernet keys) and write-only over the API; `armed` is the per-channel switch a publish needs, beside the deployment's own for the kind |
| `DistributionPost` | a page or a story going to a channel: composed (by a person, an agent or the published-page consumer) → brand guard → approved by a person → published or failed, with a readable error |
| `LedgerEntry` | what a channel has published, keyed by canonical URL (or `draft:<post>` for a text update) — the platform's half of the ledger file every lane writes (`ledger.py`); an attempt the target did not confirm is an entry with no URN |
| `Statistic` | a published post's aggregate counts on a day |

Every row has a UUID `public_id`; `visible_to(user, site)` is the one scope:
the channels of the sites a person edits (people who manage channels — the
`distribution.change_channel` permission — see every site's).
"""

import json
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from ai import crypto
from ai.models import sites_for

USER = settings.AUTH_USER_MODEL


class Kind(models.TextChoices):
    LINKEDIN = "linkedin", "LinkedIn"
    WORDPRESS = "wordpress", "WordPress"
    GITHUB_PR = "github_pr", "GitHub pull request"
    EMAIL = "email", "Email newsletter"


POST_KINDS = [("article", "Article"), ("update", "Text update")]
LEDGER_STATES = [("published", "Published"), ("unconfirmed", "Unconfirmed")]

# What each kind keeps in `settings` (never a secret) and in its encrypted credential.
SETTINGS = {
    Kind.LINKEDIN: ("author", "api_version", "scopes", "ledger_file"),
    Kind.WORDPRESS: ("url", "username", "status"),
    Kind.GITHUB_PR: ("repo", "branch", "directory"),
    Kind.EMAIL: (),
}
SECRETS = {
    Kind.LINKEDIN: ("access_token", "refresh_token"),
    Kind.WORDPRESS: ("application_password",),
    Kind.GITHUB_PR: ("token",),
    Kind.EMAIL: (),
}
# A change to one of these points the channel somewhere else, so its credential is forgotten.
IDENTITY = {Kind.LINKEDIN: ("author",), Kind.WORDPRESS: ("url", "username"), Kind.GITHUB_PR: ("repo",), Kind.EMAIL: ()}


def manages_channels(user) -> bool:
    """Setting up, connecting and arming channels is a Django permission (`distribution.change_channel`), as
    configuring an AI provider is — not `is_staff`. A superuser holds it."""
    return bool(
        user is not None
        and user.is_authenticated
        and not user.username.startswith("agent:")
        and user.has_perm("distribution.change_channel")
    )


class ChannelQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        if user is None or not user.is_authenticated:
            return self.none()
        rows = self if site is None else self.filter(site=site)
        return rows if manages_channels(user) else rows.filter(site_id__in=sites_for(user))


class Channel(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    name = models.CharField(max_length=120)
    settings = models.JSONField(default=dict, blank=True, help_text="What the kind needs to know; never a secret.")
    newsletter = models.ForeignKey(
        "newsroom.Newsletter", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    credential_encrypted = models.TextField(blank=True, editable=False)
    pending_encrypted = models.TextField(blank=True, editable=False, help_text="An OAuth code waiting to be exchanged.")
    account = models.CharField(max_length=255, blank=True, help_text="Who it publishes as, as the target reports it.")
    scopes = models.JSONField(default=list, blank=True)
    connected_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    refresh_expires_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    last_check = models.JSONField(default=dict, blank=True)
    last_error = models.TextField(blank=True)
    auto_draft = models.BooleanField(
        default=False, help_text="Draft a post (never publish one) for each page of the site that goes live."
    )
    armed = models.BooleanField(default=False, help_text="Publishing to this channel is armed (a person's setting).")
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ChannelQuerySet.as_manager()

    class Meta:
        ordering = ["site_id", "name"]

    def __str__(self):
        return f"{self.name} ({self.get_kind_display()})"

    # ── the credential: encrypted at rest, never returned ───────────────────
    def credentials(self) -> dict:
        try:
            return json.loads(crypto.decrypt(self.credential_encrypted)) if self.credential_encrypted else {}
        except crypto.InvalidToken:
            return {}

    def set_credentials(self, values: dict, *, now=None) -> None:
        kept = {k: str(v) for k, v in values.items() if k in SECRETS[self.kind] and v}
        self.credential_encrypted = crypto.encrypt(json.dumps(kept)) if kept else ""
        self.connected_at = (now or timezone.now()) if kept else None

    def forget_credentials(self) -> None:
        self.credential_encrypted = self.pending_encrypted = ""
        self.connected_at = self.expires_at = self.refresh_expires_at = None
        self.account, self.scopes = "", []

    @property
    def connected(self) -> bool:
        return self.kind == Kind.EMAIL or bool(self.credential_encrypted)

    def pending(self) -> dict:
        try:
            return json.loads(crypto.decrypt(self.pending_encrypted)) if self.pending_encrypted else {}
        except crypto.InvalidToken:
            return {}

    def set_pending(self, values: dict | None) -> None:
        self.pending_encrypted = crypto.encrypt(json.dumps(values)) if values else ""

    def setting(self, key: str, default=""):
        value = (self.settings or {}).get(key)
        return default if value in (None, "") else value


class PostQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(channel__in=Channel.objects.visible_to(user, site))


class DistributionPost(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft — waiting for a person's approval"
        APPROVED = "approved", "Approved"
        PUBLISHING = "publishing", "Publishing"
        PUBLISHED = "published", "Published"
        FAILED = "failed", "Failed"
        REJECTED = "rejected", "Rejected"

    class Origin(models.TextChoices):
        PERSON = "person", "A person"
        AGENT = "agent", "An agent"
        AUTO = "auto", "Drafted when the page went live"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="posts")
    page = models.ForeignKey("wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    story = models.ForeignKey("newsroom.Story", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    kind = models.CharField(max_length=8, choices=POST_KINDS, default="article")
    title = models.CharField(max_length=255, blank=True)
    description = models.TextField(blank=True)
    commentary = models.TextField(blank=True, help_text="The text that goes out with it.")
    link = models.CharField(max_length=2048, blank=True, help_text="The canonical URL — the ledger's key.")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT, db_index=True)
    guard = models.JSONField(default=list, blank=True, help_text="The brand guard's findings on the text.")
    origin = models.CharField(max_length=8, choices=Origin.choices, default=Origin.PERSON)
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    force = models.BooleanField(default=False, editable=False, help_text="This publish was forced past a lifted gate.")
    external_id = models.CharField(max_length=255, blank=True)
    external_url = models.CharField(max_length=2048, blank=True)
    error = models.TextField(blank=True)
    notes = models.JSONField(default=list, blank=True)
    reason = models.TextField(blank=True, help_text="Why it was rejected.")
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    approved_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    attempted_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = PostQuerySet.as_manager()

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["channel", "status"])]

    def __str__(self):
        return f"{self.title or self.kind} → {self.channel}"

    @property
    def ledger_key(self) -> str:
        return self.link if self.kind == "article" else f"draft:{self.public_id}"


class LedgerEntry(models.Model):
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="ledger")
    key = models.CharField(max_length=2048)
    urn = models.CharField(max_length=512, blank=True, help_text="Empty for an attempt the target did not confirm.")
    state = models.CharField(max_length=12, choices=LEDGER_STATES, default="published")
    kind = models.CharField(max_length=8, default="article")
    posted_at = models.DateTimeField(null=True, blank=True)
    attempted_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)
    author = models.CharField(max_length=255, blank=True)
    source_file = models.CharField(max_length=512, blank=True)
    image_urn = models.CharField(max_length=255, blank=True)
    extra = models.JSONField(default=dict, blank=True, help_text="Keys another lane wrote, kept for the file.")
    post = models.ForeignKey(
        DistributionPost, null=True, blank=True, on_delete=models.SET_NULL, related_name="ledger_entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-posted_at", "-id"]
        constraints = [models.UniqueConstraint(fields=["channel", "key"], name="distribution_one_entry_per_key")]

    def __str__(self):
        return f"{self.key} → {self.urn or 'unconfirmed'}"


class Statistic(models.Model):
    entry = models.ForeignKey(LedgerEntry, on_delete=models.CASCADE, related_name="statistics")
    day = models.DateField()
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    reactions = models.PositiveIntegerField(default=0)
    comments = models.PositiveIntegerField(default=0)
    shares = models.PositiveIntegerField(default=0)
    engagements = models.PositiveIntegerField(default=0)
    fetched_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-day"]
        constraints = [models.UniqueConstraint(fields=["entry", "day"], name="distribution_one_statistic_a_day")]
