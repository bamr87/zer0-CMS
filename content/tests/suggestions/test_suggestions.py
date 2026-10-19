"""Suggestions (M10): validated at propose, re-checked at accept, one revision
per accepted outcome authored by the agent with provenance, rejections and the
accept rate recorded, and the brand guard ported rule for rule."""

import pytest
from django.contrib.auth import get_user_model
from wagtail.models import Revision

from agents.models import AgentRun, AgentStep
from suggestions.guard import BANNED_PATTERNS, FILLER, guard_text, page_findings
from suggestions.models import BlockProvenance, Suggestion
from suggestions.services import SuggestionError, accept, accept_rate, propose, reject


def agent_user(slug="seo"):
    return get_user_model().objects.get(username=f"agent:{slug}")


def proposal(article, run, **kwargs):
    return propose(target=article, user=agent_user(run.agent.slug), run=run, rationale="because", **kwargs)


@pytest.fixture
def run(agent):
    return AgentRun.objects.create(agent=agent("seo"), trigger="manual", prompt_version="abc123")


@pytest.mark.django_db
def test_an_invalid_block_is_refused_with_the_blocks_own_message(article, run):
    with pytest.raises(SuggestionError, match="letter"):
        proposal(
            article,
            run,
            op="insert",
            payload={"type": "letter", "value": {"letter": "aa", "word": "x", "tagline": "y"}},
        )
    with pytest.raises(SuggestionError, match="unknown block type"):
        proposal(article, run, op="insert", payload={"type": "carousel", "value": {}})
    with pytest.raises(SuggestionError, match="not in page"):
        proposal(article, run, op="replace", block_id="nope", payload={"type": "markdown", "value": "x"})


@pytest.mark.django_db
def test_accepting_a_runs_suggestions_creates_exactly_one_revision(article, run, editor):
    before = Revision.objects.filter(object_id=str(article.pk)).count()
    first_block = article.body[0].id
    a = proposal(article, run, op="insert", block_id=first_block, payload={"type": "markdown", "value": "Inserted."})
    b = proposal(article, run, op="meta", field="seo_title", payload={"value": "Nightly backups, explained"})
    c = proposal(
        article, run, op="replace", block_id=article.body[1].id, payload={"type": "markdown", "value": "Replaced."}
    )
    revision = accept([a, b, c], editor)
    assert Revision.objects.filter(object_id=str(article.pk)).count() == before + 1
    assert revision.user.username == "agent:seo"
    page = revision.as_object()
    assert [blk.block_type for blk in page.body] == ["heading", "markdown", "markdown"]
    assert page.body[1].value == "Inserted." and page.body[2].value == "Replaced." and page.body[2].id == c.block_id
    assert page.seo_title == "Nightly backups, explained"
    provenance = BlockProvenance.objects.filter(page_revision=revision)
    assert set(provenance.values_list("block_id", flat=True)) == {page.body[1].id, c.block_id}
    assert {p.accepted_by for p in provenance} == {editor} and {p.prompt_version for p in provenance} == {"abc123"}
    for s in (a, b, c):
        s.refresh_from_db()
        assert (s.status, s.decided_by, s.applied_revision) == ("accepted", editor, revision)
    human = AgentStep.objects.get(run=run, kind="human")
    assert human.name == "accept" and human.user == editor


@pytest.mark.django_db
def test_rejecting_records_the_decision_and_feeds_the_accept_rate(article, run, editor, agent):
    a = proposal(article, run, op="meta", field="seo_title", payload={"value": "One"})
    b = proposal(article, run, op="meta", field="search_description", payload={"value": "Two"})
    reject(a, editor, reason="off-brand")
    a.refresh_from_db()
    assert (a.status, a.error, a.decided_by) == ("rejected", "off-brand", editor)
    accept([b], editor)
    assert accept_rate(agent("seo")) == 0.5
    assert AgentStep.objects.filter(run=run, kind="human").count() == 2


@pytest.mark.django_db
def test_an_agent_never_decides_and_a_stale_suggestion_is_refused(article, run, editor):
    s = proposal(article, run, op="delete", block_id=article.body[1].id)
    with pytest.raises(SuggestionError, match="may not"):
        accept([s], agent_user("drafter"))
    other = proposal(
        article, run, op="replace", block_id=article.body[1].id, payload={"type": "markdown", "value": "x"}
    )
    accept([s], editor)
    with pytest.raises(SuggestionError, match="not in the page"):
        accept([other], editor)
    other.refresh_from_db()
    assert other.status == "pending"


@pytest.mark.django_db
def test_one_outcome_has_one_author(article, run, editor, agent):
    a = proposal(article, run, op="meta", field="seo_title", payload={"value": "A"})
    b = propose(
        target=article,
        user=agent_user("drafter"),
        run=None,
        agent=agent("drafter"),
        op="meta",
        field="ai_summary",
        payload={"value": "B"},
        rationale="r",
    )
    with pytest.raises(SuggestionError, match="one author"):
        accept([a, b], editor)


@pytest.mark.django_db
def test_the_brand_guard_refuses_a_banned_phrase_at_propose_time(article, run):
    with pytest.raises(SuggestionError, match="cutting-edge"):
        proposal(article, run, op="meta", field="seo_title", payload={"value": "Our cutting-edge backups"})


def test_the_guard_matches_the_extensions_rule_counts_and_dedupes():
    assert len(BANNED_PATTERNS) == 13 and len(FILLER) == 9
    clean = guard_text("A plain sentence that says what it means and then keeps going for a while.")
    assert [f["level"] for f in clean] == ["info"]
    findings = guard_text("We leverage synergies with cutting-edge tools!")
    messages = [f["message"] for f in findings]
    assert 'banned phrase "cutting-edge" (cutting-edge)' in messages
    assert "reads as filler: cutting-edge" not in messages  # deduped against its error
    assert "reads as filler: synergy" in messages  # deliberately not deduped (guard.ts)
    assert "exclamation mark in commentary (house style: none)" in messages
    assert all(f["level"] != "info" for f in page_findings("cutting-edge", extra=[]))


@pytest.mark.django_db
def test_brand_rules_add_patterns_and_a_broken_one_is_skipped(article):
    from cms.models import BrandRules

    BrandRules.objects.create(
        name="house",
        banned_patterns=[{"name": "synergize", "pattern": r"\bsynergize\b"}, {"name": "broken", "pattern": "("}],
    )
    assert [f["message"] for f in page_findings("We synergize.") if f["level"] == "error"] == [
        'banned phrase "synergize" (synergize)'
    ]


@pytest.mark.django_db
def test_editor_admin_view_lists_and_accepts(client, article, run, editor):
    s = proposal(article, run, op="meta", field="seo_title", payload={"value": "Admin accepted"})
    client.force_login(editor)
    listing = client.get(f"/admin/suggestions/page/{article.pk}/")
    assert listing.status_code == 200 and b"Admin accepted" in listing.content
    response = client.post(f"/admin/suggestions/{s.pk}/accept/")
    assert response.status_code == 302
    s.refresh_from_db()
    assert s.status == Suggestion.ACCEPTED
