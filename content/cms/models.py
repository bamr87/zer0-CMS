"""Page types, the agent-managed mixin, the image model and two snippets.

Every page type descends from `BasePage`, which carries what the agent harness
and the Jekyll bridge need on every page:

- `AgentManagedMixin` (note §2.2): the per-page agent policy (`off`,
  `suggest`, `draft`, `auto`; new pages start at `suggest`), the
  agent-maintained but editor-editable `ai_summary` and `ai_keywords`, and
  `content_hash`, which drives re-embedding and tells the exporter whether a
  page changed since it was imported.
- `legacy_path`: where the page lived in its Jekyll site, kept for redirects
  and for the exporter — and, for a page that is a file of its own
  (`file_editor_fields`), the path a person gives it (`file_path`, cms/files.py).
- `front_matter`: the source file's whole front matter, in source order. The
  typed fields win over it on export (`front_matter_fields`), so an editor's
  change lands and every key no field holds survives; a person edits those
  other keys as the page's raw front matter (cms/files.py).
- The SEO and social fields beyond Wagtail's own — `canonical_url`, the Open
  Graph title, description and image, `noindex` (cms/seo.py) — each null while
  the page says what its file says, so a page read before they existed, or
  imported since, keeps its file's values and hash.

`ai_keywords` is a JSON list rather than the note's `ArrayField`, so SQLite
(development and the fast test tier) and Postgres share one schema. Vectors
are not stored on the page row at all: a revision serialises every field, and
a 1,536-float column would be copied into each one. They live in
`graph.Embedding`, keyed by `content_hash`.
"""

import hashlib
import json

from django.core.exceptions import ValidationError
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

from . import seo
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
# The page's file, as a person edits it beside the typed fields (cms/files.py):
# `file_path` is `legacy_path` under the name a person reads.
FILE_FIELDS = ("file_path", "front_matter")


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
    # The SEO and social fields beyond Wagtail's own (cms/seo.py): null means "what the file says".
    og_title = models.CharField(
        "Open Graph title",
        max_length=255,
        null=True,
        blank=True,
        help_text="The title social sites show (front matter `og_title`); empty: the title tag, else the title.",
    )
    og_description = models.TextField(
        "Open Graph description",
        null=True,
        blank=True,
        help_text="The description social sites show (front matter `og_description`); empty: the meta description.",
    )
    og_image = models.CharField(
        "Open Graph image",
        max_length=500,
        null=True,
        blank=True,
        help_text="The image social sites show, a path in the site such as /assets/images/x.png or a full URL "
        "(front matter `image`, jekyll-seo-tag's og:image); empty: the preview image.",
    )
    canonical_url = models.URLField(
        "canonical URL",
        max_length=500,
        null=True,
        blank=True,
        help_text="The address search engines should treat as this page's, when it is published elsewhere first "
        "(front matter `canonical_url`); empty: the page's own.",
    )
    noindex = models.BooleanField(
        "hide from search engines",
        null=True,
        blank=True,
        help_text="Ask search engines not to index this page (front matter `noindex`).",
    )

    # The typed fields a subclass adds to the hash, beyond the shared ones.
    hashed_fields: tuple[str, ...] = ()
    # Of those, the ones that joined the hash after pages were imported with it:
    # left out while at their default, so such a page keeps the hash it was
    # imported with (importers.ImportedSource.import_hash) and is still unchanged.
    sparse_hashed_fields: tuple[str, ...] = ()
    # What a person edits in the studio and the extension (api/pages.py): the
    # shared fields, then the typed fields each subclass adds. The body is
    # edited block by block, not as a field.
    shared_editor_fields: tuple[str, ...] = (
        "title",
        "slug",
        "seo_title",
        "search_description",
        *seo.FIELDS,
        "ai_summary",
        "ai_keywords",
        "agent_policy",
    )
    editor_fields: tuple[str, ...] = ()
    # A page the Jekyll exporter writes as a file of its own also lets a person
    # edit that file: its path in the site and its raw front matter (FILE_FIELDS,
    # cms/files.py). Books are left out: their files are the library's (books/).
    file_editor_fields: tuple[str, ...] = ()
    # The front-matter keys the exporter writes from a typed field
    # (exporters/jekyll.py's `front_matter_for`), each with the editor field that
    # holds it: raw front matter never sets one (cms/files.py).
    front_matter_fields: dict[str, str] = {
        "title": "title",
        "description": "search_description",
        "seo_title": "seo_title",
        **seo.KEYS,
    }
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
        APIField("bylines"),
        APIField("corrections"),
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

    # What a site shows beside the content: who wrote the page and its corrections
    # and updates log. The newsroom keeps both, outside the page's revisions.
    @property
    def bylines(self) -> list[dict]:
        from newsroom.services import page_bylines

        return page_bylines(self)

    @property
    def corrections(self) -> list[dict]:
        from newsroom.services import page_corrections

        return page_corrections(self)

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
            value = self.hashed_value(name)
            if name not in self.sparse_hashed_fields or value != self._meta.get_field(name).get_default():
                data[name] = value
        data.update(seo.changed(self))  # only where the page says other than its file
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
    subpage_types = ["cms.CollectionPage", "cms.ArticlePage", "cms.StandardPage", "cms.BookPage", "aieo.LandingPage"]
    hashed_fields = ("site_key", "jekyll_config")
    editor_fields = ("source_root",)
    content_panels = BasePage.content_panels + [FieldPanel("site_key"), FieldPanel("source_root")]
    graphql_fields = BasePage.graphql_fields + [GraphQLString("site_key")]


class CollectionPage(BasePage):
    """A Jekyll collection (`_posts`, `_docs`, `_books`, …) as an index page."""

    collection = models.CharField(max_length=80, help_text="The collection's name, e.g. posts.")
    output_dir = models.CharField(max_length=255, blank=True, help_text="Its directory in the site, e.g. pages/_posts.")

    subpage_types = ["cms.ArticlePage", "cms.StandardPage", "cms.BookPage", "cms.CollectionPage", "aieo.LandingPage"]
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
    file_editor_fields = FILE_FIELDS
    front_matter_fields = {
        **BasePage.front_matter_fields,
        "date": "date",
        "author": "author",
        "tags": "tags",
        "categories": "categories",
    }

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
    file_editor_fields = FILE_FIELDS


BOOK_PROFILES = [("book", "Book"), ("abc", "ABC board book"), ("story", "Picture-book story")]
# A book's and a chapter's lifecycle (the books package's library format, books/README.md).
BOOK_STATUSES = ("idea", "outlining", "drafting", "revising", "complete", "archived")
CHAPTER_STATUSES = ("stub", "outline", "draft", "revised", "final")


def string_list(value):
    """A list of non-empty strings: a cast, themes, a chapter's characters."""
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise ValidationError("a list of non-empty strings")


def document_list(value):
    """A book's other files: [{"path": "guides/act-1.md", "text": "…"}], each path relative and inside the book."""
    paths = [d.get("path") for d in value if isinstance(d, dict)] if isinstance(value, list) else None
    if paths is None or len(paths) != len(value) or len(set(paths)) != len(paths):
        raise ValidationError("a list of {path, text}, each path once")
    for doc in value:
        path = doc["path"]
        if not isinstance(path, str) or not isinstance(doc.get("text"), str) or set(doc) != {"path", "text"}:
            raise ValidationError("a document is {path, text}, both strings")
        if not path or path.startswith("/") or "\\" in path or ".." in path.split("/") or "" in path.split("/"):
            raise ValidationError(f"{path!r} is not a relative path inside the book")


class BookPage(BasePage):
    """A book: a manuscript with chapters (books), an ABC board book (its
    letters are `letter` blocks in the body) or a picture-book story (drsai).

    A manuscript book carries what its `library/<slug>/` files hold (books/):
    the manifest (book.yml: status, logline, genre, point of view, tense, era,
    acts, targets, cast, themes; every other key stays in `front_matter`), the
    outline, the character bible, the continuity ledger, a style guide, and
    every other file — the act guides, the README — as `documents`."""

    subtitle = models.CharField(max_length=250, blank=True)
    author = models.CharField(max_length=200, blank=True)
    series = models.CharField(max_length=200, blank=True)
    profile = models.CharField(max_length=16, choices=BOOK_PROFILES, default="book")
    audience = models.CharField(max_length=80, blank=True)
    art_style = models.CharField(max_length=80, blank=True)
    book_status = models.CharField(
        "status",
        max_length=16,
        choices=[(s, s.capitalize()) for s in BOOK_STATUSES],
        default="idea",
        help_text="Where the book stands, from an idea to a finished draft.",
    )
    logline = models.TextField(blank=True, help_text="One sentence: who wants what, and what stands in the way.")
    genre = models.CharField(max_length=255, blank=True)
    pov = models.CharField("point of view", max_length=255, blank=True, help_text="New chapters start with it.")
    tense = models.CharField(max_length=80, blank=True)
    era = models.CharField(max_length=255, blank=True, help_text="When it happens; new chapters start with it.")
    protagonist = models.CharField(max_length=255, blank=True)
    acts = models.PositiveSmallIntegerField(default=3, help_text="The act a chapter declares is one of these.")
    planned_chapters = models.PositiveIntegerField(
        null=True, blank=True, help_text="Progress counts chapters against it when there is no word target."
    )
    target_word_count = models.PositiveIntegerField(
        null=True, blank=True, help_text="Progress counts the prose's words against it."
    )
    themes = models.JSONField(default=list, blank=True, validators=[string_list])
    cast = models.JSONField(
        default=list,
        blank=True,
        validators=[string_list],
        help_text="Every name a chapter may list; empty switches the check off.",
    )
    outline = models.TextField(
        blank=True, help_text="Synopsis, themes, the acts' beats, the arc and the chapter plan, in Markdown."
    )
    character_notes = models.TextField("character bible", blank=True, help_text="Who everyone is, in Markdown.")
    continuity_notes = models.TextField(
        "continuity ledger", blank=True, help_text="Settled facts and open questions; every book task reads it."
    )
    style_guide = models.TextField(blank=True, help_text="The book's voice, register and house rules, in Markdown.")
    documents = models.JSONField(
        default=list,
        blank=True,
        validators=[document_list],
        help_text="The book's other files — act guides, README — as [{path, text}].",
    )

    parent_page_types = ["cms.SiteRootPage", "cms.CollectionPage"]
    subpage_types = ["cms.ChapterPage"]
    manuscript_fields = (
        "book_status",
        "logline",
        "genre",
        "pov",
        "tense",
        "era",
        "protagonist",
        "acts",
        "planned_chapters",
        "target_word_count",
        "themes",
        "cast",
        "outline",
        "character_notes",
        "continuity_notes",
        "style_guide",
    )
    hashed_fields = (
        "subtitle",
        "author",
        "series",
        "profile",
        "audience",
        "art_style",
        *manuscript_fields,
        "documents",
    )
    sparse_hashed_fields = (*manuscript_fields, "documents")  # new in cms/0002
    # `documents` is edited file by file in the Books workspace (/api/v2/books/<id>/documents/).
    editor_fields = ("subtitle", "author", "series", "profile", "audience", "art_style", *manuscript_fields)

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

    @classmethod
    def from_brief(cls, brief, *, user):
        """A brief whose result is a book outline becomes a book of the library
        with a stub per planned chapter (books/services.py), however it is
        applied; any other brief is made the generic way (None)."""
        from books.services import create_from_brief, is_outline

        return create_from_brief(brief, user) if is_outline(brief) else None


class ChapterPage(BasePage):
    """A chapter of a book: its body is the chapter's Markdown as blocks — the
    outline scaffolding, and the prose under "Chapter Body".

    Its fields are the chapter file's front matter (number, subtitle, act,
    status, point of view, era, characters, setting, tone, style); every other
    key stays in `front_matter` (books/)."""

    number = models.PositiveIntegerField(null=True, blank=True)
    subtitle = models.CharField(max_length=250, blank=True)
    act = models.PositiveSmallIntegerField(null=True, blank=True, help_text="One of the book's acts.")
    chapter_status = models.CharField(
        "status", max_length=16, choices=[(s, s.capitalize()) for s in CHAPTER_STATUSES], default="draft"
    )
    pov = models.CharField("point of view", max_length=255, blank=True)
    era = models.CharField(max_length=255, blank=True)
    characters = models.JSONField(
        default=list, blank=True, validators=[string_list], help_text="Names from the book's cast."
    )
    setting = models.JSONField(default=list, blank=True, validators=[string_list])
    tone = models.JSONField(default=list, blank=True, validators=[string_list])
    style = models.CharField(max_length=255, blank=True)

    parent_page_types = ["cms.BookPage"]
    subpage_types: list[str] = []
    hashed_fields = (
        "number",
        "subtitle",
        "act",
        "chapter_status",
        "pov",
        "era",
        "characters",
        "setting",
        "tone",
        "style",
    )
    sparse_hashed_fields = hashed_fields[1:]  # all but the number are new in cms/0002
    editor_fields = hashed_fields
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
