"""The drafter (M12): "Draft with agent" on a brief yields suggestions that,
accepted together, are one draft revision with provenance; the abc profile
writes an alphabet offline from the bundled lexicon; the story profile uses
its own prompt; and at policy draft the drafter writes the revision itself.
The model is the recorded one throughout (agents/recordings/)."""

import pytest
from django.test import override_settings

from agents.models import AgentRun
from agents.runner import execute, start_run
from cms.models import BookPage
from suggestions.models import BlockProvenance, Suggestion
from suggestions.services import accept

from ..conftest import make_article


def run(definition, target, **input_):
    r = start_run(definition, trigger="graphql", target=target, input=input_, enqueue=False)
    return execute(r)


@pytest.fixture
def briefed(site_root):
    return make_article(
        site_root,
        "Backups in plain words",
        body=[
            {
                "type": "brief",
                "value": {
                    "topic": "Why every site needs a backup",
                    "audience": "people who run a small website",
                    "notes": "Keep it short. One rule of thumb.",
                },
            }
        ],
    )


@pytest.mark.django_db
def test_draft_with_agent_yields_a_draft_revision_with_provenance(agent, briefed, editor):
    done = run(agent("drafter"), briefed, scenario="brief-to-draft")
    assert done.status == AgentRun.SUCCEEDED, done.error
    assert done.llm_backend == "recorded" and done.tokens > 0
    suggestions = list(Suggestion.objects.filter(run=done).order_by("id"))
    assert [s.op for s in suggestions] == ["insert", "insert", "insert"]
    revision = accept(suggestions, editor)
    page = revision.as_object()
    assert [b.block_type for b in page.body] == ["brief", "heading", "markdown", "markdown"]
    assert revision.user.username == "agent:drafter"
    assert not page.live or page.has_unpublished_changes  # a draft: the editor publishes
    assert BlockProvenance.objects.filter(page_revision=revision, run=done).count() == 3


@pytest.mark.django_db
def test_the_abc_profile_writes_every_missing_letter_from_the_lexicon(agent, site_root, editor):
    book = BookPage(
        title="The IT Alphabet",
        slug="it-alphabet",
        profile="abc",
        body=[{"type": "letter", "value": {"letter": "A", "word": "Automation", "tagline": "A is for Automation"}}],
    )
    site_root.add_child(instance=book)
    book.save_revision().publish()
    done = run(agent("drafter"), book, theme="IT systems")
    assert done.status == AgentRun.SUCCEEDED, done.error
    assert done.output["provider"] == "lexicon" and done.output["letters_added"] == 25
    assert done.llm_backend == ""  # no model was asked
    revision = accept(list(Suggestion.objects.filter(run=done)), editor)
    letters = [b.value["letter"] for b in revision.as_object().body if b.block_type == "letter"]
    assert letters == [chr(c) for c in range(ord("A"), ord("Z") + 1)]


@pytest.mark.django_db
def test_an_unknown_abc_theme_falls_back_to_the_model(agent, site_root):
    book = BookPage(title="Garden ABC", slug="garden-abc", profile="abc")
    site_root.add_child(instance=book)
    book.save_revision().publish()
    done = run(agent("drafter"), book, theme="garden birds", scenario="no-such-recording")
    assert done.status == AgentRun.FAILED and "no recording" in done.error


@pytest.mark.django_db
def test_the_story_profile_uses_its_own_prompt(agent, site_root):
    book = BookPage(
        title="Dodge and the Lost Kite",
        slug="lost-kite",
        profile="story",
        body=[
            {
                "type": "brief",
                "value": {"topic": "A dog finds a lost kite", "audience": "preschool", "notes": "Three scenes."},
            }
        ],
    )
    site_root.add_child(instance=book)
    book.save_revision().publish()
    done = run(agent("drafter"), book, scenario="story-picture-book")
    assert done.status == AgentRun.SUCCEEDED, done.error
    assert Suggestion.objects.filter(run=done, op="insert").count() == 3
    assert done.prompt_version != agent("drafter").prompt_version


@pytest.mark.django_db
@override_settings(AGENT_PROMOTION_MIN_DECISIONS=1, AGENT_PROMOTION_ACCEPT_RATE=0.5)
def test_at_policy_draft_the_abc_drafter_writes_the_revision_itself(agent, site_root, editor):
    drafter = agent("drafter")
    book = BookPage(title="Promoted", slug="promoted", profile="abc", agent_policy="draft")
    site_root.add_child(instance=book)
    book.save_revision().publish()
    # Promotion is earned: one accepted suggestion, then a revision that asks for draft.
    first = run(drafter, book, theme="IT systems")
    accept(list(Suggestion.objects.filter(run=first)[:1]), editor)
    Suggestion.objects.filter(run=first, status="pending").update(status="superseded")
    latest = drafter.get_latest_revision_as_object()
    latest.policy = "draft"
    revision = latest.save_revision()
    from agents.evals import gate, run_suite

    run_suite(drafter, revision)
    assert gate(drafter, revision).passed, gate(drafter, revision).reasons
    revision.publish()
    drafter.refresh_from_db()
    assert drafter.policy == "draft"
    second = run(drafter, book, theme="IT systems")
    assert second.status == AgentRun.SUCCEEDED, second.error
    assert "revision_id" in second.output and not Suggestion.objects.filter(run=second).exists()
