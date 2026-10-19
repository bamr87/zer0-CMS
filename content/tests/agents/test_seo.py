"""The SEO agent (M12): meta suggestions within their limits, from a recorded
model; accepting them sets the fields on a draft revision."""

import pytest

from agents.models import AgentRun
from agents.runner import execute, start_run
from suggestions.models import Suggestion
from suggestions.services import accept

from ..conftest import make_article


@pytest.mark.django_db
def test_seo_proposes_title_description_and_keywords(agent, site_root, editor):
    page = make_article(
        site_root,
        "How we back up the drsai site",
        body=[
            {
                "type": "markdown",
                "value": "We copy the whole site to a second disk every night, and keep thirty days of copies.",
            }
        ],
    )
    run = execute(
        start_run(agent("seo"), trigger="rest", target=page, input={"scenario": "meta-for-article"}, enqueue=False)
    )
    assert run.status == AgentRun.SUCCEEDED, run.error
    by_field = {s.field: s for s in Suggestion.objects.filter(run=run)}
    assert set(by_field) == {"seo_title", "search_description", "ai_keywords"}
    assert len(by_field["seo_title"].payload["value"]) <= 60
    revision = accept(list(by_field.values()), editor)
    draft = revision.as_object()
    assert draft.seo_title.startswith("Nightly site backups")
    assert draft.ai_keywords == ["backup", "restore", "site", "nightly"]
