"""The content model (M4): the mixin's defaults, the content hash, policy
narrowing, the portable embedding column, and the Wagtail admin loading."""

import pytest
from django.db import connection

from cms.fields import EmbeddingField
from cms.models import POLICY_DRAFT, POLICY_SUGGEST, ArticlePage, BookPage

from ..conftest import make_article


@pytest.mark.django_db
def test_new_pages_start_at_suggest_and_carry_a_hash(article):
    assert article.agent_policy == POLICY_SUGGEST
    assert len(article.content_hash) == 64
    assert article.content_hash == article.compute_content_hash()


@pytest.mark.django_db
def test_the_hash_ignores_block_ids_and_follows_content(site_root):
    a = make_article(site_root, "Same", body=[{"type": "markdown", "value": "same words"}], slug="a")
    b = make_article(site_root, "Same", body=[{"type": "markdown", "value": "same words"}], slug="b")
    assert a.body[0].id != b.body[0].id
    a_content, b_content = a.hashed_content(), b.hashed_content()
    a_content.pop("slug"), b_content.pop("slug")
    assert a_content == b_content
    before = a.compute_content_hash()
    a.body = [{"type": "markdown", "value": "other words"}]
    assert a.compute_content_hash() != before


@pytest.mark.django_db
def test_a_page_policy_can_only_narrow_an_agents(article):
    article.agent_policy = POLICY_SUGGEST
    assert article.effective_policy("auto") == POLICY_SUGGEST
    article.agent_policy = "auto"
    assert article.effective_policy(POLICY_DRAFT) == POLICY_DRAFT
    article.agent_policy = "off"
    assert article.effective_policy("auto") == "off"


def test_embedding_field_is_pgvector_on_postgres_and_text_elsewhere():
    field = EmbeddingField(dimensions=3)
    expected = "vector(3)" if connection.vendor == "postgresql" else "text"
    assert field.db_type(connection) == expected
    assert field.get_prep_value([0.5, 1, -2]) == "[0.5,1.0,-2.0]"
    assert field.to_python("[0.5,1.0,-2.0]") == [0.5, 1.0, -2.0]
    assert field.to_python(None) is None


@pytest.mark.django_db
def test_book_pages_take_chapters_and_letter_blocks(site_root):
    book = BookPage(
        title="ABC",
        slug="abc",
        profile="abc",
        body=[{"type": "letter", "value": {"letter": "A", "word": "Automation", "tagline": "A is for Automation"}}],
    )
    site_root.add_child(instance=book)
    book.full_clean()
    assert book.body[0].value["word"] == "Automation"
    assert "cms.ChapterPage" in [f"{m._meta.label}" for m in BookPage.allowed_subpage_models()]


@pytest.mark.django_db
def test_the_wagtail_admin_loads_for_an_editor(client, editor, article):
    client.force_login(editor)
    assert client.get("/admin/").status_code == 200
    edit = client.get(f"/admin/pages/{article.pk}/edit/")
    assert edit.status_code == 200
    assert b"Agent suggestions" in edit.content


@pytest.mark.django_db
def test_article_dates_round_trip_through_a_revision(site_root):
    from datetime import UTC, datetime

    page = make_article(site_root, "Dated", date=datetime(2026, 7, 31, 10, 0, tzinfo=UTC))
    again = ArticlePage.objects.get(pk=page.pk).get_latest_revision_as_object()
    assert again.date == datetime(2026, 7, 31, 10, 0, tzinfo=UTC)
