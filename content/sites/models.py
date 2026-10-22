"""`ManagedSite` and `SiteSettings`: the platform's registry of the sites it
manages (PLAN G4, TARGET.md § Sites — Manage).

A managed site is a Wagtail `Site` (its page tree, under a `SiteRootPage`)
plus what the platform needs to keep it in step with its generated file tree:
where the checkout is, whether people still edit its files (`content_source`),
how it renders (the React renderer, or the Jekyll-theme option with the
theme's tag and the Jekyll server that builds it — the `render:` setting P2
added to workspace.yml), its domains and deploy target, when it was last
synced, written back and checked, the digest of every content file as the
platform last read or wrote it (the write-back's stale-write guard), and the
last doctor run's findings.

`SiteSettings` holds what a site's people set for it, through Wagtail's site
settings (`SiteSettings.for_site(site)`): SEO defaults, analytics ids,
navigation, brand voice, design and skin, and a monthly budget. Who may see a
site and who may manage it is sites/access.py.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from wagtail.contrib.settings.models import BaseSiteSetting, register_setting


class ManagedSite(models.Model):
    class ContentSource(models.TextChoices):
        FILES = "files", "files — people still edit the site's files; sync brings them in"
        PLATFORM = "platform", "platform — the platform is the source; the files are generated"

    class Render(models.TextChoices):
        REACT = "react", "the React renderer"
        JEKYLL_THEME = "jekyll-theme", "the Jekyll-theme option"

    class Server(models.TextChoices):
        GITHUB_PAGES = "github-pages", "GitHub Pages' builder"
        JEKYLL_4 = "jekyll-4", "the pinned Jekyll 4 image"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    site = models.OneToOneField("wagtailcore.Site", on_delete=models.CASCADE, related_name="managed")
    key = models.SlugField(
        max_length=80, unique=True, help_text="The site key its pages were imported under (SiteRootPage.site_key)."
    )
    checkout = models.CharField(
        max_length=512,
        help_text="The site's file tree (its Jekyll root): relative to the repository when inside it, else absolute.",
    )
    content_source = models.CharField(max_length=10, choices=ContentSource.choices, default=ContentSource.FILES)
    render = models.CharField(max_length=20, choices=Render.choices, default=Render.REACT)
    theme_tag = models.CharField(max_length=40, blank=True, help_text="The Jekyll-theme option: the theme's tag.")
    server = models.CharField(
        max_length=20, choices=Server.choices, blank=True, help_text="The Jekyll-theme option: what builds it."
    )
    domains = models.JSONField(default=list, blank=True, help_text="The host names it is published at.")
    deploy_target = models.CharField(
        max_length=200, blank=True, help_text="Where its build goes: a Pages route (`/drsai/`), a repository, a host."
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_exported_at = models.DateTimeField(null=True, blank=True)
    last_doctor_at = models.DateTimeField(null=True, blank=True)
    digests = models.JSONField(
        default=dict, blank=True, help_text="sha256 of each content file as the platform last read or wrote it."
    )
    findings = models.JSONField(default=list, blank=True, help_text="The last doctor run's findings.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["key"]
        permissions = [("manage_site", "Can sync, write back and check a site, and change its settings")]

    def __str__(self):
        return self.key

    @property
    def root(self):
        """The checkout's absolute path."""
        path = Path(self.checkout)
        return path if path.is_absolute() else Path(settings.REPO_ROOT) / path


@register_setting(icon="site")
class SiteSettings(BaseSiteSetting):
    """What a site's people set for it, per Wagtail site."""

    seo_title_suffix = models.CharField(max_length=80, blank=True, help_text="Appended to every page title.")
    seo_description = models.TextField(blank=True, help_text="The description a page without its own gets.")
    seo_image = models.CharField(max_length=500, blank=True, help_text="The social image a page without its own gets.")
    noindex = models.BooleanField(default=False, help_text="Ask search engines not to index the site.")
    ga4_measurement_id = models.CharField(max_length=40, blank=True, help_text="Google Analytics 4, e.g. G-XXXXXXX.")
    search_console_property = models.CharField(max_length=200, blank=True, help_text="Search Console's property.")
    navigation = models.JSONField(default=list, blank=True, help_text="The main menu: [{label, url}].")
    brand_voice = models.TextField(blank=True, help_text="How the site writes; AI help reads it.")
    skin = models.CharField(max_length=40, blank=True, help_text="The design's skin.")
    design_tokens = models.JSONField(
        default=dict, blank=True, help_text="Design tokens over the skin's: {name: value}."
    )
    monthly_budget_usd = models.DecimalField(
        max_digits=9, decimal_places=2, null=True, blank=True, help_text="What AI work for the site may spend a month."
    )

    class Meta:
        verbose_name = "site settings"
        verbose_name_plural = "site settings"
