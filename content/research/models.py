"""The research library's tables (TARGET.md § Ideas and research; PLAN G14).

| Model              | What |
|--------------------|------|
| `Collection`       | A named set of sources: one project's research |
| `Source`           | One thing gathered — a web page (`url`), a feed item (`feed`), a document (`document`), a note (`note`) — with its extracted text, metadata, summary, entities and the passages an assistant suggests quoting, and where its fetch stands |
| `Quote`            | A passage a person kept from a source |
| `Citation`         | A page or a brief citing a source (or one of its quotes) |
| `FeedSubscription` | An RSS or Atom feed refreshed on a schedule; its new items become sources |
| `Question`         | A question asked of a collection: the answer and the sources it cites |
| `FactCheck`        | A draft checked against its sources: the findings, and the suggestions they became |

Owned rows take the AI layer's `Owned` base (ai/models.py) — a UUID public id,
owner, site, visibility and `visible_to(user, site)`, the one place they are
scoped — and research in a site is teamwork: a row visible to its site is
changed by anyone who edits that site (`Collaborative`). A quote is seen with
its source, a citation with its source and what cites it. The text a run
works on is read here; vectors live in `graph.Embedding` (kind `source`).
"""

import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from ai.models import Owned, Visibility, is_staff, sites_for

USER = settings.AUTH_USER_MODEL


class Collaborative(Owned):
    """An owned row people work on together: one visible to a site is changed by anyone who edits that site."""

    class Meta:
        abstract = True

    def can_edit(self, user) -> bool:
        if super().can_edit(user):
            return True
        signed_in = getattr(user, "is_authenticated", False)
        return signed_in and self.visibility == Visibility.SITE and self.site_id in sites_for(user)


def placement(user, container) -> dict:
    """The site and visibility of a row made inside `container` (a collection, a board, a feed): the container's,
    as far as its owner may hold them — a row belongs only to a site its owner edits."""
    if container is None:
        return {}
    site = container.site if container.site_id and (is_staff(user) or container.site_id in sites_for(user)) else None
    shared = container.visibility == Visibility.SHARED or (site is not None and container.visibility == Visibility.SITE)
    return {"site": site, "visibility": container.visibility if shared else Visibility.PRIVATE}


class Collection(Collaborative):
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class Source(Collaborative):
    URL, FEED, DOCUMENT, NOTE = "url", "feed", "document", "note"
    KINDS = [(URL, "Web page"), (FEED, "Feed item"), (DOCUMENT, "Document"), (NOTE, "Note")]
    PENDING, FETCHING, READY, FAILED = "pending", "fetching", "ready", "failed"
    STATUSES = [(s, s) for s in (PENDING, FETCHING, READY, FAILED)]

    kind = models.CharField(max_length=10, choices=KINDS, default=NOTE, db_index=True)
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.SET_NULL, related_name="sources")
    url = models.URLField(max_length=2000, blank=True)
    title = models.CharField(max_length=500, blank=True)
    author = models.CharField(max_length=255, blank=True)
    site_name = models.CharField(max_length=255, blank=True)
    published = models.CharField(max_length=40, blank=True, help_text="As the source dates itself.")
    language = models.CharField(max_length=16, blank=True)
    text = models.TextField(blank=True, help_text="The extracted text.")
    metadata = models.JSONField(default=dict, blank=True, help_text="Content type, size, pages, file, feed entry …")
    summary = models.TextField(blank=True)
    entities = models.JSONField(default=list, blank=True, help_text="[{name, kind}] the source names.")
    highlights = models.JSONField(default=list, blank=True, help_text="Passages an assistant suggests quoting.")
    summary_run = models.ForeignKey(
        "agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    status = models.CharField(max_length=10, choices=STATUSES, default=READY, db_index=True)
    error = models.TextField(blank=True)
    robots = models.CharField(
        max_length=12, blank=True, help_text="What robots.txt said: allowed, disallowed, unknown."
    )
    fetched_at = models.DateTimeField(null=True, blank=True)
    feed = models.ForeignKey("FeedSubscription", null=True, blank=True, on_delete=models.SET_NULL, related_name="items")
    guid = models.CharField(max_length=1000, blank=True, help_text="The feed's id for the item.")

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["feed", "guid"], condition=~Q(guid=""), name="research_one_item_per_guid")
        ]
        indexes = [models.Index(fields=["collection", "created_at"])]

    def __str__(self):
        return self.title or self.url or str(self.public_id)


class QuoteQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        return self.filter(source__in=Source.objects.visible_to(user, site))


class Quote(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="quotes")
    text = models.TextField()
    note = models.TextField(blank=True)
    location = models.CharField(max_length=120, blank=True, help_text="Where in the source: a page, a paragraph.")
    owner = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = QuoteQuerySet.as_manager()

    class Meta:
        ordering = ["source", "created_at", "id"]

    def __str__(self):
        return self.text[:60]

    def can_edit(self, user) -> bool:
        mine = self.owner_id is not None and self.owner_id == getattr(user, "pk", None)
        return mine or self.source.can_edit(user)


class CitationQuerySet(models.QuerySet):
    def visible_to(self, user, site=None):
        """Citations of the sources `user` sees, on pages they may edit and briefs they see."""
        from wagtail.models import Page
        from wagtail.permission_policies.pages import PagePermissionPolicy

        from ai.models import Brief

        if user is None or not user.is_authenticated:
            return self.none()
        pages = (
            Page.objects.all()
            if user.is_superuser
            else PagePermissionPolicy().instances_user_has_permission_for(user, "change")
        )
        return self.filter(
            Q(source__in=Source.objects.visible_to(user, site)),
            Q(page__isnull=True) | Q(page__in=pages),
            Q(brief__isnull=True) | Q(brief__in=Brief.objects.visible_to(user)),
        )


class Citation(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    source = models.ForeignKey(Source, on_delete=models.CASCADE, related_name="citations")
    quote = models.ForeignKey(Quote, null=True, blank=True, on_delete=models.CASCADE, related_name="citations")
    page = models.ForeignKey("wagtailcore.Page", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    brief = models.ForeignKey("ai.Brief", null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    note = models.TextField(blank=True)
    created_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    objects = CitationQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(page__isnull=False) | Q(brief__isnull=False), name="research_a_citation_cites_from"
            )
        ]

    def __str__(self):
        return f"{self.source} cited by {'page ' + str(self.page_id) if self.page_id else self.brief}"

    def can_edit(self, user) -> bool:
        return is_staff(user) or (self.created_by_id is not None and self.created_by_id == getattr(user, "pk", None))


class FeedSubscription(Collaborative):
    url = models.URLField(max_length=2000)
    title = models.CharField(max_length=500, blank=True)
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.SET_NULL, related_name="feeds")
    active = models.BooleanField(default=True)
    interval_minutes = models.PositiveIntegerField(
        default=60, validators=[MinValueValidator(15), MaxValueValidator(10080)], help_text="How often to look."
    )
    etag = models.CharField(max_length=255, blank=True)
    modified = models.CharField(max_length=64, blank=True)
    last_checked_at = models.DateTimeField(null=True, blank=True)
    next_check_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["title", "id"]
        indexes = [models.Index(fields=["active", "next_check_at"])]

    def __str__(self):
        return self.title or self.url


class Question(Collaborative):
    collection = models.ForeignKey(
        Collection, null=True, blank=True, on_delete=models.SET_NULL, related_name="questions"
    )
    text = models.TextField()
    answer = models.TextField(blank=True)
    citations = models.JSONField(default=list, blank=True, help_text="[{label, source, title, quote, verified}]")
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return self.text[:80]


class FactCheck(Collaborative):
    page = models.ForeignKey("wagtailcore.Page", on_delete=models.CASCADE, related_name="+")
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    summary = models.TextField(blank=True)
    findings = models.JSONField(default=list, blank=True)
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]

    def __str__(self):
        return f"Fact-check of page {self.page_id}"
