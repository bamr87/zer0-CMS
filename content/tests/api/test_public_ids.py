"""P-D6 (ADR 0009): a model the platform owns has a UUID `public_id`, the only id a surface gives or takes, or it is
named below with the reason it has none. Wagtail's and Django's own rows — pages and every page type, images,
documents and renditions, workflow tasks, users and groups — are the recorded exception and keep their integer ids.
A new model fails this test until it has a public id from its first migration, or a reason here the owner accepts;
an entry here that has gained one fails too, so the list stays the audit's."""

from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.db import models
from wagtail.images.models import AbstractImage, AbstractRendition
from wagtail.models import Page, Task

# Rows with no public id, and how each is reached instead. "Exposed" ones show their integer key on a surface today:
# the owner's open questions in ADR 0009, recorded under P-D6 in PLAN § 7 with the rest.
WITHOUT = {
    "agents.AgentDefinition": "by its slug",
    "agents.AgentStep": "by its run and its index",
    "agents.AgentToken": "by its secret, never listed",
    "agents.EvalCase": "by its agent and name, on no surface",
    "agents.EvalResult": "on no surface",
    "agents.Memory": "by scope, scope id and key",
    "ai.IdempotencyKey": "by the Idempotency-Key header, its person and the request",
    "ai.PipelineStep": "by its position in its pipeline",
    "aieo.BrandContext": "one per site, by the site's id",
    "aieo.ConnectorData": "the latest of its connector, by the connector's id",
    "books.LibraryFile": "on no surface: what the platform last read or wrote in a book's directory",
    "cms.ArticlePageTag": "exposed: Grapple's `ArticlePageTag.id` in GraphQL's search union",
    "cms.BrandRules": "exposed: Grapple's `BrandRules.id` in GraphQL",
    "cms.Category": "exposed: the studio's category field and Grapple's `Category.id` in GraphQL",
    "distribution.Statistic": "by its ledger entry and day",
    "graph.CoViewCount": "on no surface",
    "graph.Edge": "by what it joins: page, relation and destination",
    "graph.Embedding": "on no surface",
    "graph.Entity": "exposed: `entity:<id>` graph nodes and GraphQL's `EntityType.id`",
    "graph.InteractionCount": "on no surface",
    "ideas.Vote": "by its idea and voter",
    "importers.ImportedRecord": "on no surface: by source and key",
    "importers.ImportedSource": "on no surface: by site and path",
    "jobs.JobArtifact": "by its job and name",
    "jobs.JobLine": "by its job and index",
    "newsroom.Byline": "by its story and author",
    "newsroom.FrontSlot": "by its position on its front",
    "newsroom.IssueDelivery": "on no surface",
    "newsroom.IssueStory": "by its place in its issue",
    "newsroom.StoryEvent": "inside its story",
    "outbox.ProcessedEvent": "on no surface: by event id and consumer",
    "sites.SiteSettings": "one per site, by the site's id",
    "suggestions.BlockProvenance": "on no surface",
}

WAGTAIL_OWNED = (Page, AbstractImage, AbstractRendition, Task)


def platform_models():
    root = Path(settings.BASE_DIR).resolve()
    for model in apps.get_models():
        config = apps.get_app_config(model._meta.app_label)
        if root in Path(config.path).resolve().parents and not issubclass(model, WAGTAIL_OWNED):
            yield model


def has_public_id(model) -> bool:
    field = next((f for f in model._meta.concrete_fields if f.name == "public_id"), None)
    by_field = isinstance(field, models.UUIDField) and field.unique and not field.null
    return by_field or isinstance(model._meta.pk, models.UUIDField)  # the outbox's events are keyed by a UUID


def test_every_platform_model_has_a_public_id_or_a_reason():
    missing = sorted(m._meta.label for m in platform_models() if not has_public_id(m) and m._meta.label not in WITHOUT)
    assert not missing, f"give these a UUID public_id (ADR 0009), or a reason in WITHOUT: {missing}"


def test_the_list_of_rows_without_one_is_current():
    labels = {m._meta.label: m for m in platform_models()}
    stale = sorted(label for label in WITHOUT if label not in labels or has_public_id(labels[label]))
    assert not stale, f"no longer without a public id, or gone: remove from WITHOUT {stale}"


def test_runs_and_suggestions_have_one():
    assert has_public_id(apps.get_model("agents", "AgentRun"))
    assert has_public_id(apps.get_model("suggestions", "Suggestion"))
