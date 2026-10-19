"""Entities, edges, vectors and behavioural aggregates.

- `Entity` — a person, organisation, product, topic, place or concept, with
  aliases and `same_as` links (Wikidata, URLs). Tags and categories become
  topic entities, so "pages about X" is one edge type, not three.
- `Edge` — `(src, rel, dst)` between any two objects, with a weight, a
  confidence, where it came from (`structural`, `agent`, `editor`, `rails`)
  and, for an agent's edge, the run that proposed it. Unique per triple.
- `Embedding` — every vector in the plane, for pages, images, entities and
  memories alike, keyed by `(object, model)` and stamped with the
  `content_hash` it was computed from: re-embedding is skipped when the hash
  is unchanged, and a model upgrade is a second row per object until the old
  model is dropped (note §9, "embedding upgrades").
- `InteractionCount` / `CoViewCount` — what the Rails plane's
  `app.user.interaction` events add up to, per page and day. No reader
  identifier is stored: the event's `anon_id` is dropped on arrival.
"""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from wagtail.admin.panels import FieldPanel
from wagtail.snippets.models import register_snippet

from cms.fields import EmbeddingField

ENTITY_KINDS = ["person", "org", "product", "topic", "place", "concept"]
STRUCTURAL_RELS = ["child_of", "references", "links_to", "tagged", "in_category", "translation_of"]
AGENT_RELS = ["mentions", "about", "similar_to", "contradicts", "supersedes"]
BEHAVIOURAL_RELS = ["viewed_together"]
SOURCES = ["structural", "agent", "editor", "rails"]


@register_snippet
class Entity(models.Model):
    kind = models.CharField(max_length=16, choices=[(k, k) for k in ENTITY_KINDS])
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    aliases = models.JSONField(default=list, blank=True)
    description = models.TextField(blank=True)
    same_as = models.JSONField(default=list, blank=True, help_text="Wikidata ids or URLs naming the same thing.")

    panels = [
        FieldPanel("kind"),
        FieldPanel("name"),
        FieldPanel("slug"),
        FieldPanel("aliases"),
        FieldPanel("description"),
        FieldPanel("same_as"),
    ]

    class Meta:
        verbose_name_plural = "entities"
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} ({self.kind})"


class Edge(models.Model):
    src_ct = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    src_id = models.PositiveBigIntegerField()
    src = GenericForeignKey("src_ct", "src_id")
    rel = models.CharField(max_length=32, db_index=True)
    dst_ct = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    dst_id = models.PositiveBigIntegerField()
    dst = GenericForeignKey("dst_ct", "dst_id")
    weight = models.FloatField(default=1.0)
    confidence = models.FloatField(default=1.0)
    source = models.CharField(max_length=16, choices=[(s, s) for s in SOURCES])
    run = models.ForeignKey("agents.AgentRun", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    valid_from = models.DateTimeField(auto_now_add=True)
    valid_to = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["src_ct", "src_id", "rel", "dst_ct", "dst_id"], name="one_edge_per_triple")
        ]
        indexes = [models.Index(fields=["src_ct", "src_id"]), models.Index(fields=["dst_ct", "dst_id"])]

    def __str__(self):
        return f"{self.src_ct.model}:{self.src_id} -{self.rel}-> {self.dst_ct.model}:{self.dst_id}"


class Embedding(models.Model):
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.PositiveBigIntegerField()
    kind = models.CharField(max_length=16, db_index=True, help_text="page, image, entity or memory.")
    model = models.CharField(max_length=120)
    dimensions = models.PositiveIntegerField()
    content_hash = models.CharField(max_length=64)
    vector = EmbeddingField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["content_type", "object_id", "model"], name="one_vector_per_object_model")
        ]
        indexes = [models.Index(fields=["kind", "model"])]


class InteractionCount(models.Model):
    page = models.ForeignKey("wagtailcore.Page", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16)
    day = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["page", "kind", "day"], name="one_count_per_page_kind_day")]


class CoViewCount(models.Model):
    """Pages read in the same session, ordered (low id, high id)."""

    page_a = models.ForeignKey("wagtailcore.Page", on_delete=models.CASCADE, related_name="+")
    page_b = models.ForeignKey("wagtailcore.Page", on_delete=models.CASCADE, related_name="+")
    day = models.DateField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["page_a", "page_b", "day"], name="one_coview_per_pair_day")]
