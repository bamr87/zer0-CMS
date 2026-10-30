"""The content graph (M13, M17's retrieval and behavioural edges): structural
edges on publish, embeddings keyed by content hash, related pages, semantic
search, neighbours, paths, GraphRAG, and aggregates from Rails events."""

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from wagtail.models import Page

from graph import services
from graph.behavioural import build_viewed_together
from graph.models import CoViewCount, Edge, Embedding, InteractionCount
from outbox.consumers import handle_envelope

from ..conftest import make_article

PAGE_CT = None


def edges_from(page, rel=None):
    ct = ContentType.objects.get_for_model(Page)
    qs = Edge.objects.filter(src_ct=ct, src_id=page.pk)
    return qs.filter(rel=rel) if rel else qs


@pytest.fixture
def linked(site_root):
    target = make_article(
        site_root,
        "Restore guide",
        body=[{"type": "markdown", "value": "How to restore a page from the nightly backup."}],
        front_matter={"permalink": "/guides/restore/"},
    )
    source = make_article(
        site_root,
        "Backup routine",
        body=[
            {"type": "markdown", "value": "We back up every night. See [the guide](/guides/restore/) for restoring."},
            {"type": "page_link", "value": {"page": target.pk, "text": "Restore"}},
        ],
    )
    source.tags.add("backups")
    source.save_revision().publish()
    return source.specific, target


@pytest.mark.django_db
def test_publishing_builds_structural_edges(linked, site_root):
    source, target = linked
    assert edges_from(source, "child_of").get().dst_id == site_root.pk
    assert edges_from(source, "references").filter(dst_id=target.pk).exists()  # PageChooserBlock via ReferenceIndex
    assert edges_from(source, "links_to").filter(dst_id=target.pk).exists()  # Markdown link via the permalink
    assert edges_from(source, "tagged").count() == 1
    assert set(edges_from(source).values_list("source", flat=True)) == {"structural"}


@pytest.mark.django_db
def test_re_embedding_is_skipped_when_the_hash_is_unchanged(article):
    row = Embedding.objects.get(object_id=article.pk, kind="page")
    assert row.model == settings.EMBEDDING_MODEL and row.dimensions == settings.EMBEDDING_DIMENSIONS
    assert row.content_hash == article.compute_content_hash()
    assert services.index_page(article)["embedded"] is False
    article.body = [{"type": "markdown", "value": "Entirely different words now."}]
    article.save_revision().publish()
    assert (
        Embedding.objects.get(pk=row.pk).content_hash == Page.objects.get(pk=article.pk).specific.compute_content_hash()
    )


@pytest.mark.django_db
def test_related_merges_knn_and_one_hop(linked, site_root):
    source, target = linked
    unrelated = make_article(
        site_root, "Gardening", body=[{"type": "markdown", "value": "Tomatoes like sun and water."}]
    )
    hits = services.related(source, first=5)
    assert hits[0].page.pk == target.pk
    assert {"similar", "references", "links_to"} <= set(hits[0].reasons)
    assert unrelated.pk not in [h.page.pk for h in hits[:1]]


@pytest.mark.django_db
def test_semantic_search_and_graph_rag(linked, site_root):
    make_article(site_root, "Gardening", body=[{"type": "markdown", "value": "Tomatoes like sun and water."}])
    hits = services.semantic_search("restore from backup", first=2)
    assert hits[0].page.title in {"Restore guide", "Backup routine"}
    rag = services.graph_rag("tomatoes", first=3)
    assert rag[0].page.title == "Gardening"
    assert all(h.page.live for h in rag)


@pytest.mark.django_db
def test_neighbours_and_paths(linked, site_root):
    source, target = linked
    found = services.neighbors(f"page:{source.pk}", depth=1)
    assert {n["node"] for n in found} >= {f"page:{target.pk}", f"page:{site_root.pk}"}
    assert services.path(f"page:{target.pk}", f"page:{source.pk}")[0] == f"page:{target.pk}"
    with pytest.raises(services.GraphError):
        services.neighbors("page:1", depth=3)


@pytest.mark.django_db
def test_an_agent_edge_below_the_threshold_becomes_a_suggestion(agent, linked):
    from django.contrib.auth import get_user_model

    from agents.registry import ToolContext, registry

    source, target = linked
    enrich = agent("enrich")
    ctx = ToolContext(user=get_user_model().objects.get(username="agent:enrich"), agent=enrich)
    args = {"page_id": source.pk, "rel": "about", "dst": f"page:{target.pk}", "rationale": "r"}
    assert registry.call("graph.upsert_edge", {**args, "confidence": 0.95}, ctx)["written"] is False  # policy suggest
    enrich.policy = "draft"
    source.agent_policy = "draft"
    source.save_revision().publish()
    assert registry.call("graph.upsert_edge", {**args, "confidence": 0.5}, ctx)["written"] is False
    out = registry.call("graph.upsert_edge", {**args, "confidence": 0.95}, ctx)
    assert out == {"written": True}  # no integer key: the edge is named by what it joins (P-D6)
    assert Edge.objects.get(src_id=source.pk, rel="about", dst_id=target.pk).source == "agent"


@pytest.mark.django_db
def test_rails_interactions_become_aggregates_and_viewed_together_edges(linked):
    source, target = linked
    example = json.loads((Path(settings.EVENTS_SCHEMA_DIR) / "examples" / "app.user.interaction.json").read_text())
    for i in range(3):
        handle_envelope(
            {
                **example,
                "id": f"e1f2a3b4-c5d6-4e7f-8091-a2b3c4d5e6f{i}",
                "data": {
                    "anon_id": f"reader-{i:04d}",
                    "page_id": source.pk,
                    "kind": "view",
                    "session_page_ids": [target.pk],
                },
            }
        )
    assert InteractionCount.objects.get(page_id=source.pk, kind="view").count == 3
    assert CoViewCount.objects.get().count == 3
    assert build_viewed_together(min_count=2) == 2
    assert edges_from(source, "viewed_together").get().source == "rails"
    # Only aggregates crossed the boundary: no reader id is stored anywhere.
    for model in (InteractionCount, CoViewCount, Edge):
        assert "reader-0000" not in json.dumps(list(model.objects.values()), default=str)
    assert services.related(source, kind="behavioral")[0].page.pk == target.pk


@pytest.mark.django_db
def test_graph_rest_and_graphql(client, linked):
    source, target = linked
    neighbors = client.get(f"/api/v2/graph/neighbors/?node=page:{source.pk}").json()["neighbors"]
    assert f"page:{target.pk}" in {n["node"] for n in neighbors}
    assert client.get(f"/api/v2/graph/related/{source.pk}/").json()["results"][0]["page_id"] == target.pk
    assert client.get("/api/v2/graph/search/?q=restore").json()["results"]
    data = client.post(
        "/graphql/",
        data=json.dumps(
            {
                "query": "query($id: Int!) { related(pageId: $id) { score reasons page { id } } "
                "entities(pageId: $id) { name rel } }",
                "variables": {"id": source.pk},
            }
        ),
        content_type="application/json",
    ).json()
    assert data["data"]["related"][0]["page"]["id"] == str(target.pk)
    assert data["data"]["entities"] == [{"name": "backups", "rel": "tagged"}]
