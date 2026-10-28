"""The content schema agents read (M11): the committed export is current, it
is versioned, every run records the version, and the block tools validate
block JSON with the blocks themselves."""

from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command

from agents.registry import ToolContext, ToolError, registry
from agents.schema import BlockInvalid, dumps, export, validate_block

COMMITTED = Path(settings.REPO_ROOT) / "schemas" / "content" / "ai-schema.json"


@pytest.mark.django_db
def test_the_committed_schema_snapshot_is_current():
    assert COMMITTED.read_text(encoding="utf-8") == dumps(export()), (
        "schemas/content/ai-schema.json is stale: python manage.py wagtail_ai_schema --out ../schemas/content/ai-schema.json"
    )


@pytest.mark.django_db
def test_the_check_command_agrees(capsys):
    call_command("wagtail_ai_schema", "--check", str(COMMITTED))
    assert "is current" in capsys.readouterr().out


@pytest.mark.django_db
def test_the_schema_covers_every_page_type_and_block():
    document = export()
    assert set(document["pages"]) == {
        "aieo.LandingPage",
        "cms.ArticlePage",
        "cms.BookPage",
        "cms.ChapterPage",
        "cms.CollectionPage",
        "cms.SiteRootPage",
        "cms.StandardPage",
    }
    assert set(document["$defs"]["blocks"]) == {
        "markdown",
        "heading",
        "paragraph",
        "image",
        "code",
        "quote",
        "page_link",
        "brief",
        "letter",
    }
    heading = document["$defs"]["blocks"]["heading"]
    assert heading["properties"]["level"]["enum"] == ["2", "3", "4", "5", "6"]
    assert "description" in document["$defs"]["blocks"]["markdown"]
    assert len(document["version"]) == 12


def test_validate_block_uses_the_blocks_own_rules():
    assert validate_block("heading", {"level": "3", "text": "Fine"})["text"] == "Fine"
    with pytest.raises(BlockInvalid, match="level"):
        validate_block("heading", {"level": "9", "text": "x"})
    with pytest.raises(BlockInvalid, match="text"):
        validate_block("heading", {"level": "2", "text": ""})


@pytest.mark.django_db
def test_invalid_block_json_is_rejected_with_the_error(agent, article):
    from django.contrib.auth import get_user_model

    seo = agent("drafter")
    ctx = ToolContext(user=get_user_model().objects.get(username="agent:drafter"), agent=seo)
    with pytest.raises(ToolError) as e:
        registry.call(
            "content.propose_edit",
            {
                "page_id": article.pk,
                "op": "insert",
                "rationale": "r",
                "block": {"type": "heading", "value": {"level": "9", "text": "x"}},
            },
            ctx,
        )
    assert e.value.code == "invalid_args" and "level" in e.value.message
    schema = registry.call("content.get_schema", {"page_type": "cms.ArticlePage"}, ctx)
    assert schema["version"] == export()["version"] and "body" in schema["page"]
