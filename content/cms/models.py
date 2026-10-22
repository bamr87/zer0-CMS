"""Page types, the agent-managed mixin, the image model and two snippets.

Every page type descends from `BasePage`, which carries what the agent harness
and the Jekyll bridge need on every page:

- `AgentManagedMixin` (note §2.2): the per-page agent policy (`off`,
  `suggest`, `draft`, `auto`; new pages start at `suggest`), the
  agent-maintained but editor-editable `ai_summary` and `ai_keywords`, and
  `content_hash`, which drives re-embedding and tells the exporter whether a
  page changed since it was imported.
- `legacy_path`: where the page lived in its Jekyll site, kept for redirects
  and for the exporter.
- `front_matter`: the source file's whole front matter, in source order. The
  typed fields win over it on export, so an editor's change lands and every
  key no field holds survives.

`ai_keywords` is a JSON list rather than the note's `ArrayField`, so SQLite
(development and the fast test tier) and Postgres share one schema. Vectors
are not stored on the page row at all: a revision serialises every field, and
a 1,536-float column would be copied into each one. They live in
`graph.Embedding`, keyed by `content_hash`.
"""

import hashlib
import json

from django.db import models
from graphene.types.generic import GenericScalar
from grapple.models import (
    GraphQLBoolean,
    GraphQLField,
    GraphQLImage,
    GraphQLInt,
    GraphQLStreamfield,
    GraphQLString,
    GraphQLTag,
)
from modelcluster.contrib.taggit import ClusterTaggableManager
from modelcluster.fields import ParentalKey, ParentalManyToManyField
from taggit.models import TaggedItemBase
from wagtail.admin.panels import FieldPanel, MultiFieldPanel
from wagtail.api import APIField
from wagtail.fields import StreamField
from wagtail.images.models import AbstractImage, AbstractRendition, Image
from wagtail.models import Page
from wagtail.search import index
from wagtail.snippets.models import register_snippet

from suggestions.panels import SuggestionsPanel

from .blocks import BodyBlock
from .fields import OrderedJSONField

POLICY_OFF = "off"
POLICY_SUGGEST = "suggest"
POLICY_DRAFT = "draft"
POLICY_AUTO = "auto"
POLICY_CHOICES = [
    (POLICY_OFF, "Off — no agent touches this page"),
    (POLICY_SUGGEST, "Suggest — agents propose, editors accept"),
    (POLICY_DRAFT, "Draft — agents may write draft revisions"),
    (POLICY_AUTO, "Auto — agents may publish low-risk changes"),
]
POLICY_ORDER = [POLICY_OFF, POLICY_SUGGEST, POLICY_DRAFT, POLICY_AUTO]


def _strip_ids(value):
    """Block ids are random per block; a hash must not depend on them."""
    if isinstance(value, dict):
        return {k: _strip_ids(v) for k, v in value.items() if k != "id"}
    if isinstance(value, list):
        return [_strip_ids(v) for v in value]
    return value


def stable_hash(payload) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


class AgentManagedMixin(models.Model):
    agent_policy = models.CharField(
        max_length=16,
        choices=POLICY_CHOICES,
        default=POLICY_SUGGEST,
        help_text="The most an agent may do to this page. An agent's own policy can only narrow it.",
    )
    ai_summary = models.TextField(blank=True, help_text="Agent-maintained summary; editors may change it.")
    ai_keywords = models.JSONField(default=list, blank=True, help_text="Agent-maintained keywords.")
    content_hash = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        abstract = True


class BasePage(AgentManagedMixin, Page):
    body = StreamField(BodyBlock(), blank=True)
    legacy_path = models.CharField(
        max_length=512, blank=True, db_index=True, help_text="The file this page came from, relative to its site root."
    )
    front_matter = OrderedJSONField(
        blank=True, help_text="The source file's front matter, in source order, kept for the exporter."
    )
    preview_image = models.ForeignKey(
        "cms.ContentImage",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
        help_text="The page's preview image (front matter `preview`).",
    )

    # The typed fields a subclass adds to the hash, beyond the shared ones.
    hashed_fields: tuple[str, ...] = ()
    # What a person edits in the studio and the extension (api/pages.py): the
    # shared fields, then the typed fields each subclass adds. The body is
    # edited block by block, not as a field.
    shared_editor_fields: tuple[str, ...] = (
        "title",
        "slug",
        "seo_title",
        "search_description",
        "ai_summary",
        "ai_keywords",
        "agent_policy",
    )
    editor_fields: tuple[str, ...] = ()
    # Headless first: this template exists for the editor's preview only.
    template = "cms/page.html"

    content_panels = Page.content_panels + [FieldPanel("body"), SuggestionsPanel(heading="Agent suggestions")]
    promote_panels = Page.promote_panels + [
        FieldPanel("preview_image"),
        MultiFieldPanel([FieldPanel("ai_summary"), FieldPanel("ai_keywords")], heading="Agent-maintained"),
    ]
    settings_panels = Page.settings_panels + [FieldPanel("agent_policy"), FieldPanel("legacy_path", read_only=True)]

    search_fields = Page.search_fields + [
        index.SearchField("body"),
        index.SearchField("ai_summary"),
        index.FilterField("agent_policy"),
    ]

    api_fields = [
        APIField("body"),
        APIField("ai_summary"),
        APIField("ai_keywords"),
        APIField("agent_policy"),
        APIField("legacy_path"),
        APIField("content_hash"),
    ]
    graphql_fields = [
        GraphQLStreamfield("body"),
        GraphQLField("body_json", GenericScalar, description="The body as StreamField JSON: [{type, value, id}]."),
        GraphQLImage("preview_image"),
        GraphQLString("ai_summary"),
        GraphQLString("agent_policy"),
        GraphQLString("legacy_path"),
        GraphQLString("content_hash"),
    ]

    class Meta:
        abstract = True

    @property
    def body_json(self) -> list:
        return list(self.body.get_prep_value())

    def hashed_content(self) -> dict:
        """Everything that makes this page's content what it is, without ids,
        timestamps or tree position — two imports of the same file agree."""
        data = {
            "type": self._meta.label,
            "title": self.title,
            "slug": self.slug,
            "seo_title": self.seo_title,
            "search_description": self.search_description,
            "body": _strip_ids(self.body.get_prep_value()),
            "front_matter": self.front_matter,
        }
        for name in self.hashed_fields:
            data[name] = self.hashed_value(name)
        return data

    def hashed_value(self, name):
        return getattr(self, name)

    def compute_content_hash(self) -> str:
        return stable_hash(self.hashed_content())

    def save(self, *args, **kwargs):
        self.content_hash = self.compute_content_hash()
        return super().save(*args, **kwargs)

    def effective_policy(self, agent_policy: str) -> str:
        """The narrower of this page's policy and an agent's."""
        return min(self.agent_policy, agent_policy, key=POLICY_ORDER.index)


class SiteRootPage(BasePage):
    """The root of one imported Jekyll site: one Wagtail `Site` per Jekyll site."""

    site_key = models.SlugField(max_length=80, unique=True, help_text="The site's name, e.g. drsai.")
    source_root = models.CharField(
        max_length=512, blank=True, help_text="The Jekyll root this site imports from, relative to the repository."
    )
    jekyll_config = models.JSONField(default=dict, blank=True, help_text="The parts of _config.yml the bridge reads.")

    parent_page_types = ["wagtailcore.Page"]
    subpage_types = ["cms.CollectionPage", "cms.ArticlePage", "cms.StandardPage", "cms.BookPage"]
    hashed_fields = ("site_key", "jekyll_config")
    editor_fields = ("source_root",)
    content_panels = BasePage.content_panels + [FieldPanel("site_key"), FieldPanel("source_root")]
    graphql_fields = BasePage.graphql_fields + [GraphQLString("site_key")]


class CollectionPage(BasePage):
    """A Jekyll collection (`_posts`, `_docs`, `_books`, …) as an index page."""

    collection = models.CharField(max_length=80, help_text="The collection's name, e.g. posts.")
    output_dir = models.CharField(max_length=255, blank=True, help_text="Its directory in the site, e.g. pages/_posts.")

    subpage_types = ["cms.ArticlePage", "cms.StandardPage", "cms.BookPage", "cms.CollectionPage"]
    hashed_fields = ("collection", "output_dir")
    editor_fields = ("collection", "output_dir")
    content_panels = BasePage.content_panels + [FieldPanel("collection"), FieldPanel("output_dir")]
    graphql_fields = BasePage.graphql_fields + [GraphQLString("collection")]


@register_snippet
class Category(models.Model):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=120, unique=True)

    panels = [FieldPanel("name"), FieldPanel("slug")]
    graphql_fields = [GraphQLString("name"), GraphQLString("slug")]

    class Meta:
        verbose_name_plural = "categories"
        ordering = ["name"]

    def __str__(self):
        return self.name


class ArticlePageTag(TaggedItemBase):
    content_object = ParentalKey("cms.ArticlePage", on_delete=models.CASCADE, related_name="tagged_items")


class ArticlePage(BasePage):
    """A post or a document: dated, authored, tagged and categorised."""

    date = models.DateTimeField(null=True, blank=True, help_text="Publication date (front matter `date`).")
    author = models.CharField(max_length=200, blank=True)
    tags = ClusterTaggableManager(through=ArticlePageTag, blank=True)
    categories = ParentalManyToManyField("cms.Category", blank=True)

    parent_page_types = ["cms.SiteRootPage", "cms.CollectionPage"]
    subpage_types: list[str] = []
    hashed_fields = ("date", "author", "tags", "categories")
    editor_fields = ("date", "author", "tags", "categories")

    content_panels = Page.content_panels + [
        MultiFieldPanel([FieldPanel("date"), FieldPanel("author"), FieldPanel("tags"), FieldPanel("categories")]),
        FieldPanel("body"),
        SuggestionsPanel(heading="Agent suggestions"),
    ]
    search_fields = BasePage.search_fields + [index.SearchField("author")]
    api_fields = BasePage.api_fields + [APIField("date"), APIField("author"), APIField("tags")]
    graphql_fields = BasePage.graphql_fields + [
        GraphQLString("date"),
        GraphQLString("author"),
        GraphQLTag("tags"),
    ]

    def hashed_value(self, name):
        if name == "date":
            return self.date.isoformat() if self.date else None
        if name == "tags":
            return sorted(t.name for t in self.tags.all())
        if name == "categories":
            return sorted(c.slug for c in self.categories.all())
        return super().hashed_value(name)


class StandardPage(BasePage):
    """Any other page: about, index, a docs page that is not dated."""

    parent_page_types = ["cms.SiteRootPage", "cms.CollectionPage", "cms.StandardPage"]
    subpage_types = ["cms.StandardPage"]


BOOK_PROFILES = [("book", "Book"), ("abc", "ABC board book"), ("story", "Picture-book story")]


class BookPage(BasePage):
    """A book: a manuscript with chapters (books), an ABC board book (its
    letters are `letter` blocks in the body) or a picture-book story (drsai)."""

    subtitle = models.CharField(max_length=250, blank=True)
    author = models.CharField(max_length=200, blank=True)
    series = models.CharField(max_length=200, blank=True)
    profile = models.CharField(max_length=16, choices=BOOK_PROFILES, default="book")
    audience = models.CharField(max_length=80, blank=True)
    art_style = models.CharField(max_length=80, blank=True)

    parent_page_types = ["cms.SiteRootPage", "cms.CollectionPage"]
    subpage_types = ["cms.ChapterPage"]
    hashed_fields = ("subtitle", "author", "series", "profile", "audience", "art_style")
    editor_fields = ("subtitle", "author", "series", "profile", "audience", "art_style")

    content_panels = Page.content_panels + [
        MultiFieldPanel(
            [
                FieldPanel("subtitle"),
                FieldPanel("author"),
                FieldPanel("series"),
                FieldPanel("profile"),
                FieldPanel("audience"),
                FieldPanel("art_style"),
            ]
        ),
        FieldPanel("body"),
        SuggestionsPanel(heading="Agent suggestions"),
    ]
    api_fields = BasePage.api_fields + [APIField(n) for n in ("subtitle", "author", "series", "profile", "audience")]
    graphql_fields = BasePage.graphql_fields + [
        GraphQLString("subtitle"),
        GraphQLString("author"),
        GraphQLString("series"),
        GraphQLString("profile"),
    ]


class ChapterPage(BasePage):
    number = models.PositiveIntegerField(null=True, blank=True)

    parent_page_types = ["cms.BookPage"]
    subpage_types: list[str] = []
    hashed_fields = ("number",)
    editor_fields = ("number",)
    content_panels = Page.content_panels + [
        FieldPanel("number"),
        FieldPanel("body"),
        SuggestionsPanel(heading="Agent suggestions"),
    ]
    graphql_fields = BasePage.graphql_fields + [GraphQLInt("number")]


@register_snippet
class BrandRules(models.Model):
    """The house style an agent reads and the brand guard enforces. The
    built-in bans (suggestions/guard.py) always run; these patterns add to
    them, like the extension's `governance.bannedPatternsFile`."""

    name = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    banned_patterns = models.JSONField(
        default=list,
        blank=True,
        help_text='Extra bans: [{"name": "…", "pattern": "regex", "flags": "i"}]. A bad pattern is skipped, never fatal.',
    )
    style_guide = models.TextField(blank=True, help_text="Prose an agent reads before it writes.")

    panels = [FieldPanel("name"), FieldPanel("is_active"), FieldPanel("banned_patterns"), FieldPanel("style_guide")]
    graphql_fields = [GraphQLString("name"), GraphQLBoolean("is_active"), GraphQLString("style_guide")]

    class Meta:
        verbose_name_plural = "brand rules"

    def __str__(self):
        return self.name


class ContentImage(AbstractImage):
    """Wagtail's image plus what the media pipeline fills in (note §2.4). The
    vector is in `graph.Embedding`, like every other vector."""

    ai_alt = models.TextField(blank=True, help_text="Agent-proposed alternative text.")
    ai_caption = models.TextField(blank=True)
    ai_tags = models.JSONField(default=list, blank=True)
    content_hash = models.CharField(max_length=64, blank=True, editable=False, db_index=True)

    admin_form_fields = Image.admin_form_fields + ("ai_alt", "ai_caption", "ai_tags")
    graphql_fields = [GraphQLString("ai_alt"), GraphQLString("ai_caption")]


class ContentRendition(AbstractRendition):
    image = models.ForeignKey(ContentImage, on_delete=models.CASCADE, related_name="renditions")

    class Meta:
        unique_together = (("image", "filter_spec", "focal_point_key"),)
