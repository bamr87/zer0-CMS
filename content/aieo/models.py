"""AIEO's tables (TARGET.md § AIEO in the platform; PLAN G7), mapped from
`apps/aieo/backend/app/models/` and its file workspace onto the platform:

| AIEO                                   | here                                         |
|----------------------------------------|----------------------------------------------|
| `prompts/patterns/*.md`, the PATTERNS table | `Pattern` (the editable library the scorer reads) |
| `Audit` (24-hour cache rows), reports/ | `Audit` (history: a text, a page, a URL or a crawled site) |
| `Citation` (never filled)              | `CitationQuery` + `CitationCheck` (asked on a schedule, per engine) |
| GA4 / GSC / DataForSEO settings, `.cache/` | `Connector` (per site, credential encrypted) + `ConnectorData` |
| `context/*.md`, `config/competitors.json` | `BrandContext` (a Wagtail site setting)    |
| `landing-pages/`                       | `LandingPage` (a page type)                  |
| topics, research, drafts, rewrites     | Ideas, Research, briefs and suggestions (no table here) |

Audits and citation queries take the AI layer's `Owned` base — a UUID public
id, owner, site, visibility and `visible_to(user, site)`, the one place they
are scoped. A connector belongs to a site: its editors see it, and people with
`aieo.change_connector` who edit the site configure it; its credential is
encrypted with the AI layer's keys (`ai.crypto`) and never leaves through the
API. Patterns are the platform's: everyone signed in reads them, and people
with `aieo.change_pattern` change them.
"""

import uuid

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from wagtail.contrib.settings.models import BaseSiteSetting

from ai import crypto
from ai.models import Owned, is_staff, sites_for
from cms.models import BasePage

from . import scoring

CONTEXT_TEMPLATES = {
    "brand_voice": "# Brand Voice\n\n## Voice pillars\n\n- \n\n## Tone guidance\n\n- \n\n## Core messages\n\n- \n",
    "style_guide": "# Style Guide\n\n## Grammar and mechanics\n\n- \n\n## Formatting conventions\n\n- \n",
    "writing_examples": (
        "# Writing Examples\n\n## Example 1\n\n- URL:\n- Why it works:\n\n## Example 2\n\n- URL:\n- Why it works:\n"
    ),
    "target_keywords": (
        "# Target Keywords\n\n## Topic clusters\n\n### Cluster\n\n- Pillar keyword:\n- Long-tail variations:\n- Intent:\n"
    ),
    "internal_links_map": "# Internal Links Map\n\n## Key pages\n\n- URL:\n- Recommended anchors:\n",
    "competitor_analysis": "# Competitor Analysis\n\n## Primary competitors\n\n- \n\n## Content gaps\n\n- \n",
    "seo_guidelines": (
        "# SEO Guidelines\n\n## Required checks\n\n- Word count:\n- Keyword usage:\n- Link strategy:\n- Meta constraints:\n"
    ),
    "cro_best_practices": "# CRO Best Practices\n\n## Above-the-fold\n\n- \n\n## CTA\n\n- \n",
    "features": "# Product Features\n\n## Core features\n\n- Feature:\n- Benefit:\n",
}


# ── the pattern library ────────────────────────────────────────────────────


class Pattern(models.Model):
    """One citability pattern: what the evaluator is told to look for (`body`), its weight in the score and the most
    it can earn. Seeded from the bundled pattern files; a person's change is kept (aieo/prompts.py)."""

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.SlugField(max_length=64, unique=True, help_text="The key the evaluator answers under.")
    display_name = models.CharField(max_length=120)
    category = models.CharField(max_length=32, blank=True, help_text="structure, content, metadata or format.")
    description = models.TextField(blank=True, help_text="One line on what the pattern is.")
    weight = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    max_score = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(100)])
    boost_min = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Citation boost, % (low).")
    boost_max = models.PositiveSmallIntegerField(null=True, blank=True, help_text="Citation boost, % (high).")
    body = models.TextField(help_text="The criteria the evaluator reads, in Markdown.")
    enabled = models.BooleanField(default=True, help_text="Scored, and offered to apply.")
    bundled = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.display_name or self.name

    def as_spec(self) -> dict:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "weight": self.weight,
            "max_score": self.max_score,
            "body": self.body,
        }


def library() -> list[dict]:
    """The enabled patterns as the scorer takes them; the bundled files when the library is empty."""
    rows = [p.as_spec() for p in Pattern.objects.filter(enabled=True)]
    return rows or list(scoring.bundled_patterns())


# ── audits ─────────────────────────────────────────────────────────────────


class Audit(Owned):
    """One audit and what it found. A text is kept with its audit; a page, a URL or a site is read when the audit
    runs (a run of the `assistant` agent, aieo/handlers.py)."""

    TEXT, PAGE, URL, SITE = "text", "page", "url", "site"
    KINDS = [(TEXT, "Text"), (PAGE, "Page"), (URL, "Web page"), (SITE, "Crawled site")]
    PENDING, RUNNING, READY, FAILED = "pending", "running", "ready", "failed"
    STATUSES = [(s, s) for s in (PENDING, RUNNING, READY, FAILED)]
    HEURISTIC, AI = "heuristic", "ai"
    METHODS = [(HEURISTIC, "Heuristics only"), (AI, "A model's evaluation, the heuristics as its fallback")]
    MARKDOWN, HTML = "markdown", "html"

    kind = models.CharField(max_length=8, choices=KINDS, db_index=True)
    method = models.CharField(max_length=10, choices=METHODS, default=AI, help_text="What was asked for.")
    provider = models.CharField(max_length=40, blank=True, help_text="The provider to evaluate with ('' = default).")
    title = models.CharField(max_length=500, blank=True)
    url = models.URLField(max_length=2000, blank=True)
    page = models.ForeignKey("wagtailcore.Page", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    content = models.TextField(blank=True, help_text="The text audited (a text audit).")
    format = models.CharField(max_length=10, default=MARKDOWN, choices=[(MARKDOWN, MARKDOWN), (HTML, HTML)])
    max_pages = models.PositiveSmallIntegerField(default=25, validators=[MinValueValidator(1), MaxValueValidator(200)])
    visual = models.BooleanField(default=False, help_text="Screenshot the page and evaluate what it looks like.")
    status = models.CharField(max_length=8, choices=STATUSES, default=PENDING, db_index=True)
    score = models.FloatField(null=True, blank=True)
    grade = models.CharField(max_length=2, blank=True)
    scoring_method = models.CharField(max_length=10, blank=True, help_text="What scored it: heuristic or ai.")
    content_hash = models.CharField(max_length=64, blank=True)
    result = models.JSONField(default=dict, blank=True, help_text="Patterns, gaps, penalties, dimensions, analyses.")
    pages = models.JSONField(default=list, blank=True, help_text="A site audit's pages: url, title, score, grade …")
    benchmark = models.JSONField(default=dict, blank=True)
    screenshot = models.CharField(max_length=255, blank=True, help_text="The screenshot's path in media storage.")
    batch = models.CharField(max_length=64, blank=True, db_index=True, help_text="Audits made together.")
    origin = models.CharField(max_length=16, blank=True, help_text="studio, api, mcp, cli, import, schedule.")
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    error = models.TextField(blank=True)
    audited_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["page", "created_at"]), models.Index(fields=["url", "created_at"])]

    def __str__(self):
        return f"{self.kind} audit {self.title or self.url or self.public_id}"

    @property
    def target(self) -> str:
        return self.url or (self.page.title if self.page_id else "") or self.title or "the text"


# ── citations ──────────────────────────────────────────────────────────────


class CitationQuery(Owned):
    """A question people ask AI engines, and the domain whose citation is looked for in each engine's answer."""

    prompt = models.TextField(help_text="What a person asks an AI engine.")
    domain = models.CharField(max_length=255, help_text="The site whose citation is looked for: example.com.")
    engines = models.JSONField(default=list, blank=True, help_text="Provider slugs to ask ([] = the default).")
    interval_days = models.PositiveSmallIntegerField(
        default=7, validators=[MaxValueValidator(365)], help_text="How often it is asked again (0 = on request)."
    )
    active = models.BooleanField(default=True)
    next_check_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.prompt[:80]


class CheckQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(query__in=CitationQuery.objects.visible_to(user, site))


class CitationCheck(models.Model):
    """One engine's answer to a query at one time, and whether it cited the domain."""

    QUEUED, READY, FAILED = "queued", "ready", "failed"
    STATUSES = [(s, s) for s in (QUEUED, READY, FAILED)]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    query = models.ForeignKey(CitationQuery, on_delete=models.CASCADE, related_name="checks")
    engine = models.CharField(max_length=40, help_text="The provider asked.")
    model = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=8, default=QUEUED, choices=STATUSES)
    cited = models.BooleanField(null=True)
    position = models.PositiveSmallIntegerField(null=True, blank=True, help_text="1 = the first source it gave.")
    cited_urls = models.JSONField(default=list, blank=True)
    sources = models.JSONField(default=list, blank=True, help_text="[{url, title}] the sources the engine gave.")
    answer = models.TextField(blank=True)
    error = models.TextField(blank=True)
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    checked_at = models.DateTimeField(auto_now_add=True, db_index=True)

    objects = CheckQuerySet.as_manager()

    class Meta:
        ordering = ["-checked_at", "-id"]
        indexes = [models.Index(fields=["query", "engine", "checked_at"])]

    def __str__(self):
        return f"{self.engine} on {self.query_id}: {self.cited}"


# ── connectors ─────────────────────────────────────────────────────────────


class ConnectorQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        if user is None or not user.is_authenticated:
            return self.none()
        rows = self if site is None else self.filter(site=site)
        return rows if is_staff(user) else rows.filter(site__in=sites_for(user))


class Connector(models.Model):
    """A site's connection to GA4, Search Console or DataForSEO (aieo/connectors.py)."""

    GA4, GSC, DATAFORSEO = "ga4", "gsc", "dataforseo"
    KINDS = [(GA4, "Google Analytics 4"), (GSC, "Google Search Console"), (DATAFORSEO, "DataForSEO")]
    IDLE, SYNCING, OK, FAILED = "idle", "syncing", "ok", "failed"
    STATUSES = [(s, s) for s in (IDLE, SYNCING, OK, FAILED)]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    site = models.ForeignKey("wagtailcore.Site", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=12, choices=KINDS)
    enabled = models.BooleanField(default=True)
    options = models.JSONField(
        default=dict, blank=True, help_text="property_id (GA4), site_url (GSC), keywords and location (DataForSEO)."
    )
    credential_encrypted = models.TextField(blank=True, editable=False)
    status = models.CharField(max_length=8, default=IDLE, choices=STATUSES)
    error = models.TextField(blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = ConnectorQuerySet.as_manager()

    class Meta:
        ordering = ["site", "kind"]
        constraints = [models.UniqueConstraint(fields=["site", "kind"], name="aieo_one_connector_per_kind")]

    def __str__(self):
        return f"{self.get_kind_display()} for {self.site}"

    @property
    def has_credential(self) -> bool:
        return bool(self.credential_encrypted)

    def set_credential(self, raw: str) -> None:
        self.credential_encrypted = crypto.encrypt(raw or "")

    def get_credential(self) -> str:
        return crypto.decrypt(self.credential_encrypted)

    def can_edit(self, user) -> bool:
        if user is None or not user.is_authenticated or not user.has_perm("aieo.change_connector"):
            return False
        return is_staff(user) or self.site_id in sites_for(user)


class ConnectorData(models.Model):
    """What one sync fetched: GA4's top pages, Search Console's queries, or DataForSEO's results."""

    connector = models.ForeignKey(Connector, on_delete=models.CASCADE, related_name="snapshots")
    report = models.CharField(max_length=16, help_text="top_pages, queries or serp.")
    rows = models.JSONField(default=list, blank=True)
    fetched_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-fetched_at", "-id"]

    def __str__(self):
        return f"{self.connector} {self.report} at {self.fetched_at:%Y-%m-%d %H:%M}"


# ── brand context ──────────────────────────────────────────────────────────


def _competitors():
    return {"competitors": [], "keywords": [], "topics": []}


class BrandContext(BaseSiteSetting):
    """What every AIEO agent reads about a site — the workspace's `context/*.md` and `config/competitors.json` as a
    Wagtail site setting (a row per site, made from the templates the first time it is read)."""

    brand_voice = models.TextField(blank=True, default=CONTEXT_TEMPLATES["brand_voice"])
    style_guide = models.TextField(blank=True, default=CONTEXT_TEMPLATES["style_guide"])
    writing_examples = models.TextField(blank=True, default=CONTEXT_TEMPLATES["writing_examples"])
    target_keywords = models.TextField(blank=True, default=CONTEXT_TEMPLATES["target_keywords"])
    internal_links_map = models.TextField(blank=True, default=CONTEXT_TEMPLATES["internal_links_map"])
    competitor_analysis = models.TextField(blank=True, default=CONTEXT_TEMPLATES["competitor_analysis"])
    seo_guidelines = models.TextField(blank=True, default=CONTEXT_TEMPLATES["seo_guidelines"])
    cro_best_practices = models.TextField(blank=True, default=CONTEXT_TEMPLATES["cro_best_practices"])
    features = models.TextField(blank=True, default=CONTEXT_TEMPLATES["features"])
    competitors = models.JSONField(
        default=_competitors, blank=True, help_text="{competitors: [urls], keywords: [...], topics: [...]}."
    )
    updated_at = models.DateTimeField(auto_now=True)

    FIELDS = tuple(CONTEXT_TEMPLATES)

    class Meta:
        verbose_name = "AIEO brand context"

    def keywords(self) -> list[str]:
        """The target keywords: `competitors.keywords`, then the target keywords document's bullets — a bare one, or
        the comma-separated values of a `… keyword:` or `… variations:` line (headings and intents skipped)."""
        found = [str(k).strip() for k in (self.competitors or {}).get("keywords", []) if str(k).strip()]
        for line in self.target_keywords.splitlines():
            line = line.strip().lstrip("-*").strip()
            if not line or line.startswith("#"):
                continue
            label, _, value = line.rpartition(":") if ":" in line else ("keyword", "", line)
            if "keyword" in label.lower() or "variation" in label.lower():
                found += [v.strip() for v in value.split(",") if v.strip()]
        return list(dict.fromkeys(found))

    def topics(self) -> list[str]:
        return [str(t).strip() for t in (self.competitors or {}).get("topics", []) if str(t).strip()]

    def as_prompt(self) -> str:
        """The context, as an agent reads it: every document that says more than its template."""
        written = [(getattr(self, name) or "").strip() for name in self.FIELDS]
        kept = [
            text
            for text, name in zip(written, self.FIELDS, strict=True)
            if text and text != CONTEXT_TEMPLATES[name].strip()
        ]
        return "\n\n".join(kept)


# ── landing pages ──────────────────────────────────────────────────────────


class LandingPage(BasePage):
    """A conversion page: the copy AIEO's landing-page workflow drafts, researches and CRO-audits, with the one
    action it asks a reader to take."""

    cta_text = models.CharField(max_length=120, blank=True, help_text="The call to action, as the button says it.")
    cta_url = models.CharField(max_length=500, blank=True, help_text="Where the call to action goes.")

    parent_page_types = ["cms.SiteRootPage", "cms.CollectionPage"]
    subpage_types: list[str] = []
    editor_fields = ("cta_text", "cta_url")

    class Meta:
        verbose_name = "landing page"
