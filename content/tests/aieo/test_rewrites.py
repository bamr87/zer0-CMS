"""Optimize, scrub, rewrite and apply a pattern: runs of the bundled assistants whose rewrite of a page arrives as
suggestions on it — each changed block replaced, inserted or deleted, through the tool registry as the assistant
agent acting for the person who asked — and never as a revision; a rewrite of a pasted text is the run's output, a
draft to read. The optimizer reads AIEO's own prompt with the gaps an audit finds."""

import pytest

from agents.models import AgentRun
from aieo import services
from aieo.models import Pattern
from ops.errors import Forbidden, Invalid
from suggestions.models import Suggestion

REWRITE = """Backups are copies of a site. A backup is defined as a restorable copy, kept off the server.

## How often?

Daily backups suit a busy site. Weekly backups suit a brochure site.

| Site | Frequency |
|------|-----------|
| Busy | Daily |

## Frequently asked questions

Is a host's backup enough? No: keep a copy you control."""


def test_optimizing_a_page_lands_its_rewrite_as_suggestions_not_a_revision(alice, fake, worker, page):
    revision = page.get_latest_revision().pk
    fake.script = [{"text": f"# Nightly backups\n\n{REWRITE}"}]
    run = worker(services.rewrite, alice, mode="optimize", page=page)
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED, run.error
    page.refresh_from_db()
    assert page.get_latest_revision().pk == revision  # nothing written
    made = Suggestion.objects.filter(run=run).order_by("pk")
    assert [s.op for s in made] == ["replace", "replace", "replace", "replace"]  # the heading "How often?" kept
    assert all(s.status == Suggestion.PENDING for s in made) and made[0].rationale.startswith("AIEO optimized")
    assert run.output["score_after"] > run.output["score_before"] and run.output["uplift"] > 0
    request = fake.calls[0]["messages"][0]["content"]
    assert (
        "Gaps to fix:" in request and "Apply these AIEO patterns:" in request and "titled 'Nightly backups'" in request
    )


def test_the_rewrite_is_aligned_block_by_block():
    two, four = ({"level": "2", "text": text} for text in ("Two", "Four"))
    blocks = [
        {"id": "a", "type": "markdown", "value": "One."},
        {"id": "b", "type": "heading", "value": two},
        {"id": "c", "type": "markdown", "value": "Three."},
        {"id": "d", "type": "heading", "value": four},
        {"id": "e", "type": "markdown", "value": "Five."},
    ]
    same = "One.\n\n## Two\n\nThree.\n\n## Four\n\nFive."
    assert services.proposals(blocks, same) == []
    assert services.proposals(blocks, "New first.\n\nOne.\n\n## Two\n\nThree, better.") == [
        ("replace", "a", {"type": "markdown", "value": "New first.\n\nOne."}),
        ("replace", "c", {"type": "markdown", "value": "Three, better."}),
        ("delete", "d", None),
        ("delete", "e", None),
    ]
    assert services.proposals(blocks, same.replace("## Four", "## Middle\n\nNew.\n\n## Four")) == [
        ("insert", "c", {"type": "markdown", "value": "## Middle\n\nNew."})
    ]
    assert services.proposals(blocks, f"## Zero\n\n{same}") == [
        ("replace", "a", {"type": "markdown", "value": "## Zero\n\nOne."})
    ]
    assert services.proposals(blocks, same.replace("Three.", "Three.\n\n| A | B |\n|---|---|\n| 1 | 2 |")) == [
        ("replace", "c", {"type": "markdown", "value": "Three.\n\n| A | B |\n|---|---|\n| 1 | 2 |"})
    ]
    assert services.proposals([], "Brand new.") == [("insert", "", {"type": "markdown", "value": "Brand new."})]


def test_scrubbing_a_text_is_a_draft_in_the_runs_output(alice, fake, worker):
    fake.script = [{"text": "Clean prose, with no filler."}]
    run = worker(services.rewrite, alice, mode="scrub", content="Moreover — in today's world — prose.")
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED and run.output["markdown"] == "Clean prose, with no filler."
    assert run.output["suggestions"] == [] and not Suggestion.objects.filter(run=run).exists()
    assert "repetitive sentence openings" in fake.calls[0]["system"]  # AIEO's scrub prompt


def test_expand_reads_aieos_expand_instructions(alice, fake, worker):
    fake.script = [{"text": "Expanded."}]
    run = worker(services.rewrite, alice, mode="expand", content="A short text about backups.")
    run.refresh_from_db()
    assert run.status == AgentRun.SUCCEEDED and "Expand mode" in fake.calls[0]["messages"][0]["content"]


def test_applying_a_pattern_over_the_api_rewrites_with_that_pattern(
    alice, api, fake, worker, page, django_capture_on_commit_callbacks
):
    fake.script = [{"text": REWRITE}]
    with django_capture_on_commit_callbacks(execute=True):
        got = api(alice).post(
            "/api/v2/aieo/patterns/faq_injection/apply/", {"page_id": page.pk}, format="json", HTTP_IDEMPOTENCY_KEY="k1"
        )
    assert got.status_code == 202, got.content
    run = AgentRun.objects.get(pk=got.json()["run"]["id"])
    assert run.status == AgentRun.SUCCEEDED and run.input["pattern"] == "faq_injection"
    assert "FAQ Injection" in fake.calls[0]["messages"][0]["content"]
    assert Suggestion.objects.filter(run=run).exists()
    again = api(alice).post(
        "/api/v2/aieo/patterns/faq_injection/apply/", {"page_id": page.pk}, format="json", HTTP_IDEMPOTENCY_KEY="k1"
    )
    assert again.json() == got.json() and again["Idempotent-Replayed"] == "true"


def test_a_rewrite_needs_the_edit_right_an_enabled_pattern_and_something_to_rewrite(alice, bob, fake, page):
    with pytest.raises(Forbidden):
        services.rewrite(bob, mode="optimize", page=page)
    Pattern.objects.filter(name="faq_injection").update(enabled=False)
    with pytest.raises(Invalid):
        services.rewrite(alice, mode="pattern", page=page, pattern=Pattern.objects.get(name="faq_injection"))
    with pytest.raises(Invalid):
        services.rewrite(alice, mode="optimize")
