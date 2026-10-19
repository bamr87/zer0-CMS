"""barodybroject → the content plane (M6, PLAN §4.4): posts become article
pages, their version history becomes revisions in order, assistants become
legacy definitions that cannot run, and a re-run changes nothing."""

import json
from pathlib import Path

import pytest
from wagtail.models import Revision

from agents.models import AgentDefinition
from cms.models import ArticlePage
from importers.barodybroject import import_dump
from importers.models import ImportedSource

DUMP = Path(__file__).resolve().parent.parent / "fixtures" / "barodybroject" / "dumpdata.json"


@pytest.mark.django_db
def test_posts_versions_and_assistants_are_imported():
    report = import_dump(str(DUMP))
    assert len(report.pages_created) == 2 and report.revisions == 2 and report.agents == ["legacy-news-writer"]
    source = ImportedSource.objects.get(site_key="barodybroject", legacy_path="parodynews.post:1")
    page = source.page.specific
    assert isinstance(page, ArticlePage) and page.live
    assert page.title == "Local Cat Declares Independence" and page.author == "The Desk"
    assert page.get_parent().specific.collection == "posts"
    history = list(Revision.page_revisions.filter(object_id=str(page.pk)).order_by("created_at", "id"))
    assert [r.user.username for r in history] == ["legacy:import"] * 3
    assert history[0].created_at.year == 2025 and "first draft" in json.dumps(history[0].content)
    assert "Breaking" in page.body[0].value
    draft = ImportedSource.objects.get(legacy_path="parodynews.post:2").page.specific
    assert not draft.live
    legacy = AgentDefinition.objects.get(slug="legacy-news-writer")
    assert legacy.policy == "off" and not legacy.live and legacy.model == "anthropic/claude-sonnet-5-5"
    assert legacy.profile["legacy_ref"] == "parodynews.assistant:asst_1"


@pytest.mark.django_db
def test_a_second_import_changes_nothing():
    import_dump(str(DUMP))
    revisions = Revision.objects.count()
    again = import_dump(str(DUMP))
    assert again.pages_created == [] and len(again.pages_unchanged) == 2 and Revision.objects.count() == revisions
