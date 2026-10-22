"""The book assistant (books/handlers.py, agents/definitions/books.yaml): every
bookshelf task as a run of the `books` agent through the AI layer, on the
scripted fake provider — draft, continue and revise arrive as suggestions on
the chapter that a person accepts; the continuity check (structured findings),
the critique and the outline are the run's output; a book from a premise is an
outline brief a person turns into a draft book and its chapter stubs. What a run
is given is the book's own material; who may ask is checked when it is asked
and again when it runs. Nothing reaches a model."""

import json

import pytest

from agents.models import AgentRun, Memory
from ai.models import Assistant, Brief
from books import files, services
from books.handlers import plan, prose_blocks
from cms.models import BookPage, ChapterPage
from ops.errors import Forbidden, Invalid
from suggestions.models import Suggestion
from suggestions.services import accept

FINDINGS = {
    "findings": [
        {
            "severity": "high",
            "kind": "continuity",
            "quote": "the door",
            "problem": "The ledger settles the door is green; the chapter does not say.",
            "suggestion": "Name its colour once.",
        }
    ],
    "summary": "One drift from the ledger.",
}
OUTLINE = {
    "title": "The Quiet Part",
    "alt_titles": ["Remarks"],
    "logline": "A speechwriter starts telling the truth.",
    "genre": "Political satire",
    "pov": "Third person limited",
    "tense": "Past",
    "era": "Now",
    "protagonist": "Nell Ames",
    "synopsis": "Nell writes what the minister says. One morning she writes what he means.",
    "themes": [{"name": "Candour", "argument": "The truth costs the teller first."}],
    "acts": [
        {"title": "The draft", "beats": [{"title": "The slip", "points": ["Nell leaves one true line in."]}]},
        {"title": "The fallout", "beats": [{"title": "The leak", "points": ["The line trends."]}]},
        {"title": "The speech", "beats": [{"title": "The choice", "points": ["Nell writes the whole truth."]}]},
    ],
    "arc": [{"phase": "Ghost", "description": "Nell writes in other voices."}],
    "cast": ["Nell Ames", "The Minister"],
    "chapters": [
        {"number": 1, "act": 1, "title": "Opening Remarks", "beat": "The slip."},
        {"number": 2, "act": 2, "title": "The Leak", "beat": "The line trends."},
        {"number": 3, "act": 3, "title": "Closing Remarks", "beat": "The whole truth."},
    ],
}
DETAIL = {
    "Header": {"author": {"name": ""}, "publication_date": "2026-10-22", "title": "The Quiet Part", "subtitle": ""},
    "Metadata": {
        "description": "A book outline.",
        "slug": "the-quiet-part",
        "excerpt": "",
        "prompt": "",
        "categories": [],
        "keywords": "",
        "tags": [],
    },
}


def chapter(book, number):
    return ChapterPage.objects.child_of(book).get(number=number)


def fresh(page):
    return type(page).objects.get(pk=page.pk).get_latest_revision_as_object()


def run_of(worker, book, user, **kwargs):
    run = worker(services.run_task, book, user, **kwargs)
    run.refresh_from_db()
    return run


# ── what a task does ───────────────────────────────────────────────────────


@pytest.mark.django_db
def test_draft_replaces_the_chapters_prose_with_a_suggestion_a_person_accepts(sample, alice, fake, worker):
    fake.script.append(
        {"text": "Ana counted nothing. She sat.", "tokens_in": 900, "tokens_out": 12, "cost_usd": "0.02"}
    )
    first = chapter(sample, 1)
    run = run_of(worker, sample, alice, task="draft", chapter=first)
    assert run.status == AgentRun.SUCCEEDED, run.error
    assert (run.agent.slug, run.target.pk, run.started_by) == ("books", first.pk, alice)
    assert run.output["task"] == "draft" and run.output["provider"] == "fake"
    [suggestion] = Suggestion.objects.filter(run=run)
    assert (suggestion.op, suggestion.agent.slug, suggestion.target_id) == ("replace", "books", first.pk)
    assert suggestion.payload == {"type": "markdown", "value": "Ana counted nothing. She sat.\n\n---"}
    assert fresh(first).body.raw_data[4]["value"].startswith("Ana opened the door")  # nothing written yet
    accept([suggestion], alice)
    assert fresh(first).body.raw_data[4]["value"] == "Ana counted nothing. She sat.\n\n---"
    assert "## Chapter Body\n\nAna counted nothing. She sat.\n\n---\n" in files.chapter_text(fresh(first))


@pytest.mark.django_db
def test_the_run_is_given_the_books_own_material(sample, alice, fake, worker):
    fake.script.append({"text": "More."})
    run_of(worker, sample, alice, task="continue", chapter=chapter(sample, 2), instruction="Keep it short.")
    call = fake.calls[0]
    assert call["system"].startswith("You are an editorial assistant working inside a book project.")
    assert "You continue chapters." in call["system"] and call["tools"] == []
    request = call["messages"][0]["content"]
    for text in (
        "# Book brief: A Sample Book",
        "Cast (the only names you may use): Ana, Boris",
        "The door is always green.",  # the continuity ledger
        "Ana is the protagonist.",  # the character bible
        "# Act I guide",  # the act guide covering chapter 2
        "## Previous chapter: Chapter 1",
        "# The chapter you are working on\n\nNumber: 2",
        "Continue this chapter from exactly where it stops.",
        "# Additional instruction\n\nKeep it short.",
    ):
        assert text in request, text


@pytest.mark.django_db
def test_continue_adds_after_the_prose_and_keeps_the_closing_rule(sample, alice, fake, worker):
    fake.script.append({"text": "Then she left."})
    run = run_of(worker, sample, alice, task="continue", chapter=chapter(sample, 1))
    [suggestion] = Suggestion.objects.filter(run=run)
    value = suggestion.payload["value"]
    assert suggestion.op == "replace" and value.endswith("one final time.\n\nThen she left.\n\n---")


@pytest.mark.django_db
def test_revise_replaces_the_selected_passage_and_refuses_one_not_in_the_chapter(sample, alice, fake, worker):
    fake.script += [{"text": "counted every chair"}, {"text": "unused"}]
    first = chapter(sample, 1)
    run = run_of(worker, sample, alice, task="revise", chapter=first, selection="counted the empty chairs")
    [suggestion] = Suggestion.objects.filter(run=run)
    assert "Ana opened the door and counted every chair one final time." in suggestion.payload["value"]
    assert "SELECTION:\n\ncounted the empty chairs" in fake.calls[0]["messages"][0]["content"]
    missing = run_of(worker, sample, alice, task="revise", chapter=first, selection="a passage that is not there")
    assert missing.status == AgentRun.FAILED and "not in the chapter" in missing.error
    with pytest.raises(Invalid):
        services.run_task(sample, alice, task="revise", chapter=first)


@pytest.mark.django_db
def test_the_continuity_check_returns_validated_findings_and_proposes_nothing(sample, alice, fake, worker):
    fake.script += [{"text": json.dumps(FINDINGS)}, {"text": json.dumps({"findings": [{"severity": "dire"}]})}]
    run = run_of(worker, sample, alice, task="check", chapter=chapter(sample, 2))
    assert run.status == AgentRun.SUCCEEDED and run.output["json"] == FINDINGS
    assert run.output["markdown"].startswith("One drift from the ledger.")
    assert "**high · continuity**" in run.output["markdown"] and not Suggestion.objects.filter(run=run).exists()
    assert fake.calls[0]["schema"]["required"] == ["findings", "summary"]
    bad = run_of(worker, sample, alice, task="check", chapter=chapter(sample, 2))
    assert bad.status == AgentRun.FAILED and "schema" in bad.error


@pytest.mark.django_db
def test_critique_and_outline_are_the_runs_output(sample, alice, fake, worker):
    fake.script += [{"text": "What works: the chairs."}, {"text": json.dumps(OUTLINE)}]
    critique = run_of(worker, sample, alice, task="critique", chapter=chapter(sample, 1))
    assert critique.output["markdown"] == "What works: the chairs." and not Suggestion.objects.exists()
    outline = run_of(worker, sample, alice, task="outline")
    assert outline.target.pk == sample.pk and outline.output["json"]["title"] == "The Quiet Part"
    rendered = outline.output["markdown"]
    assert rendered.startswith("# The Quiet Part\n\nWorking titles: Remarks")
    assert "### Act 1 — The draft" in rendered and "| 3 | 3 | Closing Remarks | The whole truth. |" in rendered


@pytest.mark.django_db
def test_a_person_may_bring_their_own_assistant(sample, alice, fake, worker):
    mine = Assistant.objects.create(owner=alice, name="Noir", instructions="Write it noir.")
    fake.script.append({"text": "Rain."})
    run = run_of(worker, sample, alice, task="draft", chapter=chapter(sample, 1), assistant=mine)
    assert run.status == AgentRun.SUCCEEDED and fake.calls[0]["system"] == "Write it noir."
    assert "Write the narrative prose for this chapter." in fake.calls[0]["messages"][0]["content"]


# ── who may ask, and when it is asked again ────────────────────────────────


@pytest.mark.django_db
def test_only_someone_who_may_edit_the_chapter_asks_and_the_worker_asks_again(sample, alice, bob, fake, worker):
    with pytest.raises(Forbidden):
        services.run_task(sample, bob, task="draft", chapter=chapter(sample, 1))
    theirs = Assistant.objects.create(owner=bob, name="Bob's")
    with pytest.raises(Forbidden):
        services.run_task(sample, alice, task="draft", chapter=chapter(sample, 1), assistant=theirs)
    with pytest.raises(Invalid):
        services.run_task(sample, alice, task="draft")  # a chapter task needs a chapter
    with pytest.raises(Invalid):
        services.run_task(sample, alice, task="polish", chapter=chapter(sample, 1))
    run = services.run_task(sample, alice, task="draft", chapter=chapter(sample, 1))  # queued, not run yet
    alice.groups.clear()  # alice loses her page rights before the worker picks the run up
    from agents.runner import execute

    run = execute(AgentRun.objects.get(pk=run.pk))  # as the worker loads it: alice read afresh
    run.refresh_from_db()
    assert run.status == AgentRun.FAILED and "may edit" in run.error and not fake.calls


@pytest.mark.django_db
def test_a_chapter_from_another_book_is_refused(sample, impairment, alice):
    with pytest.raises(Invalid):
        services.run_task(sample, alice, task="draft", chapter=chapter(impairment, 1))


# ── a book from a premise ──────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_premise_becomes_an_outline_a_person_turns_into_a_draft_book(sample, alice, bob, fake, worker):
    fake.script += [{"text": json.dumps(OUTLINE)}, {"text": json.dumps(DETAIL)}]
    brief, run = worker(services.outline_from_premise, alice, premise="A speechwriter starts telling the truth.")
    brief.refresh_from_db()
    assert brief.status == Brief.READY, brief.error
    assert brief.result["title"] == "The Quiet Part" and brief.markdown.startswith("# The Quiet Part")
    assert BookPage.objects.filter(title="The Quiet Part").count() == 0  # nothing is made until a person says so
    with pytest.raises(Forbidden):
        services.create_from_brief(brief, bob)
    book = services.create_from_brief(brief, alice)
    latest = fresh(book)
    assert (latest.book_status, latest.logline, latest.protagonist) == (
        "outlining",
        "A speechwriter starts telling the truth.",
        "Nell Ames",
    )
    assert (latest.acts, latest.planned_chapters, latest.themes, latest.cast) == (
        3,
        3,
        ["Candour"],
        ["Nell Ames", "The Minister"],
    )
    assert latest.outline == brief.markdown and not book.live
    stubs = [fresh(c) for c in ChapterPage.objects.child_of(book).order_by("path")]
    assert [(c.number, c.act, c.title, c.chapter_status) for c in stubs] == [
        (1, 1, "Opening Remarks", "stub"),
        (2, 2, "The Leak", "stub"),
        (3, 3, "Closing Remarks", "stub"),
    ]
    assert "- The slip." in files.chapter_text(stubs[0]) and not any(c.live for c in stubs)
    brief.refresh_from_db()
    assert (brief.status, brief.page_id) == (Brief.APPLIED, book.pk)
    with pytest.raises(Exception, match="ready outline"):
        services.create_from_brief(brief, alice)


# ── the pieces ─────────────────────────────────────────────────────────────


def test_prose_blocks_follow_the_chapter_body_or_skip_the_scaffolding():
    heading = lambda level, text: {"id": text, "type": "heading", "value": {"level": str(level), "text": text}}  # noqa: E731
    md = lambda i, text: {"id": i, "type": "markdown", "value": text}  # noqa: E731
    skeleton = [heading(2, "Outline and Contextual Alignment"), md("a", "plan"), heading(2, "Chapter Body")]
    skeleton += [md("b", "one"), heading(3, "A scene"), md("c", "two\n\n---"), heading(2, "Links and References")]
    assert prose_blocks(skeleton) == (2, [3, 4, 5])
    assert plan("draft", skeleton, "New.") == [
        ("replace", "b", {"type": "markdown", "value": "New.\n\n---"}),
        ("delete", "A scene", None),
        ("delete", "c", None),
    ]
    plain = [heading(2, "Outline and Contextual Alignment"), md("a", "plan"), heading(2, "Chapter 1: Arrival")]
    plain += [md("b", "prose"), heading(2, "Links and References"), md("c", "- [x](y)")]
    assert prose_blocks(plain) == (None, [3])
    assert plan("continue", plain, "More.") == [("replace", "b", {"type": "markdown", "value": "prose\n\nMore."})]
    assert plan("draft", [heading(2, "Chapter Body")], "First.") == [
        ("insert", "Chapter Body", {"type": "markdown", "value": "First."})
    ]


@pytest.mark.django_db
def test_the_continuity_ledger_is_the_agents_memory_of_the_book(sample):
    memory = Memory.objects.get(scope="page", scope_id=str(sample.pk), key="book.continuity")
    assert memory.value == {
        "book": "sample",
        "title": "A Sample Book",
        "text": "# Ledger\n\nThe door is always green.\n",
    }
    draft = sample.get_latest_revision_as_object()
    draft.continuity_notes = "# Ledger\n\nThe door is red now.\n"
    from cms.services import save_draft

    save_draft(draft, user=None)
    memory.refresh_from_db()
    assert memory.value["text"] == "# Ledger\n\nThe door is red now.\n"
    assert Memory.objects.filter(scope="page", scope_id=str(sample.pk), key="book.characters").exists()


@pytest.mark.django_db
def test_the_bundled_book_assistants_schemas_and_pipeline_are_seeded():
    seeded = services.import_bundled()
    keys = {a.name for a in seeded["assistants"]}
    assert keys == {
        "Book outliner",
        "Chapter drafter",
        "Chapter continuer",
        "Passage reviser",
        "Book editor",
        "Continuity checker",
    }
    assert all(
        a.visibility == "shared" and a.instructions.startswith("You are an editorial") for a in seeded["assistants"]
    )
    assert services.bundled("book-continuity-checker").output_schema.name == "Continuity findings"
    [pipeline] = seeded["pipelines"]
    assert [s.assistant.name for s in pipeline.steps.order_by("position")] == ["Book outliner", "Book editor"]
    assert services.import_bundled()["assistants"][0].pk == seeded["assistants"][0].pk  # idempotent
