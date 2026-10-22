"""The ideas services (ideas/services.py): capture from a line or a template,
one vote per person, brainstorming through the AI layer's conversations (the
reply is a run of the `assistant` agent; a person keeps the ideas they want),
clusters and duplicates read from stored vectors (the deterministic hashing
embedder here), merging, and promotion to a brief, an article draft or a book
draft — never a published page. The provider is the scripted fake."""

import json

import pytest

from agents.models import AgentRun
from ai.models import Brief, Message
from cms.models import ArticlePage, BookPage
from graph.models import Embedding
from ideas import services
from ideas.models import Board, Idea, Vote
from ops.errors import Conflict, Forbidden, Invalid
from research import services as research
from research.models import Citation

from ..ai.test_services import DETAIL
from .conftest import IDEAS


def fresh(row):
    row.refresh_from_db()
    return row


@pytest.mark.django_db
def test_an_idea_is_captured_from_a_line_or_a_template_and_voted_once_per_person(alice, bob):
    board = Board.objects.create(owner=alice, name="Spring", visibility="shared")
    idea = services.capture(alice, "Nightly backups\nfor small sites", board=board, tags=["ops", "backups"])
    assert (idea.title, idea.notes, idea.origin, idea.status) == (
        "Nightly backups",
        "for small sites",
        "captured",
        "new",
    )
    assert (idea.visibility, sorted(idea.tags.names())) == ("shared", ["backups", "ops"])
    topic = services.capture(alice, "Citability for small sites", template="topic", url="https://example.com/x")
    assert topic.notes.startswith("## Why this topic matters") and "## Key questions to answer" in topic.notes
    assert topic.board is None and topic.url == "https://example.com/x"
    with pytest.raises(Invalid):
        services.capture(alice, "  \n ")
    with pytest.raises(Invalid, match="no template"):
        services.capture(alice, "x", template="nope")
    for _ in range(2):
        services.vote(idea, bob)
    services.vote(idea, alice)
    assert Vote.objects.filter(idea=idea).count() == 2
    services.vote(idea, bob, up=False)
    assert list(Vote.objects.filter(idea=idea).values_list("user__username", flat=True)) == ["alice"]


@pytest.mark.django_db
def test_a_brainstorm_is_a_conversation_whose_reply_lists_ideas_a_person_keeps(alice, fake, worker, brainstormed):
    board = Board.objects.create(owner=alice, name="Backups", description="Posts about backups")
    services.capture(alice, "Backups, a plan", board=board)
    source = research.add_note(alice, "Most small sites lose data once a year.", title="Survey")
    fake.script.append(brainstormed)
    conversation, message, reply, run = worker(
        services.brainstorm, alice, "nightly backups", kind="headlines", count=3, board=board, sources=[source]
    )
    run, reply = fresh(run), fresh(reply)
    assert run.status == "succeeded" and run.input == {"kind": "message", "message": str(reply.public_id)}
    assert reply.status == Message.COMPLETED and reply.result == IDEAS and "**Backups, a plan** (outline)" in reply.text
    sent = fake.calls[0]
    assert sent["system"].startswith("You brainstorm ideas") and sent["schema"]["required"] == ["ideas"]
    asked = sent["messages"][-1]["content"]
    assert asked.startswith("Brainstorm 3 headlines for: nightly backups") and "- Backups, a plan" in asked
    assert "Most small sites lose data once a year." in asked and conversation.title == "Brainstorm: nightly backups"
    kept = services.keep(reply, user=alice, picks=[0, 2, 0], board=board)
    assert [(i.title, i.origin, i.source_message_id) for i in kept] == [
        ("Backups in five minutes a night", "brainstormed", reply.pk)
    ]  # the outline's title is on the board already, and a pick counts once
    assert list(kept[0].tags.names()) == ["angle"] and kept[0].notes == "For people who never set one up."
    with pytest.raises(Invalid, match="pick ideas 0 to 2"):
        services.keep(reply, user=alice, picks=[3])
    with pytest.raises(Conflict):
        services.keep(message, user=alice)
    fake.script.append(brainstormed)
    _, _, again, _ = worker(services.brainstorm, alice, "more like the first", conversation=conversation)
    assert len(services.keep(fresh(again), user=alice)) == 3  # into the inbox, which has none of them yet


@pytest.mark.django_db
def test_ideas_alike_in_meaning_cluster_and_near_copies_are_offered_to_merge(
    alice, bob, django_capture_on_commit_callbacks
):
    board = Board.objects.create(owner=alice, name="Backups")
    with django_capture_on_commit_callbacks(execute=True):
        first = services.capture(alice, "Nightly backups for small sites", board=board, tags=["ops"])
        copy = services.capture(alice, "Nightly backups for small sites, explained", board=board, tags=["guide"])
        cousin = services.capture(alice, "Why small sites need nightly backups", board=board)
        services.capture(alice, "Sourdough starter tips", board=board)
    late = Idea.objects.create(owner=alice, board=board, title="Not embedded yet")
    assert Embedding.objects.filter(kind="idea").count() == 4
    found = services.clusters(Idea.objects.filter(board=board).order_by("pk"))
    assert [sorted(i.title for i in group) for group in found["clusters"]] == [
        sorted([first.title, copy.title, cousin.title])
    ]
    assert [(a.pk, b.pk) for a, b, _ in found["duplicates"]] == [(first.pk, copy.pk)]
    assert found["duplicates"][0][2] >= 0.85 and found["pending"] == [late]
    Vote.objects.create(idea=copy, user=bob)
    Vote.objects.create(idea=copy, user=alice)
    Vote.objects.create(idea=first, user=alice)
    Idea.objects.filter(pk=copy.pk).update(notes="With a checklist.")
    kept = services.merge(first, fresh(copy), user=alice)
    assert sorted(kept.tags.names()) == ["guide", "ops"]
    assert kept.notes == "Merged from “Nightly backups for small sites, explained”:\n\nWith a checklist."
    assert not Idea.objects.filter(pk=copy.pk).exists()
    assert sorted(Vote.objects.filter(idea=kept).values_list("user__username", flat=True)) == ["alice", "bob"]
    with pytest.raises(Invalid):
        services.merge(first, first, user=alice)
    with pytest.raises(Forbidden):
        services.merge(first, cousin, user=bob)


@pytest.mark.django_db
def test_an_idea_is_promoted_to_a_brief_that_reads_its_sources(alice, fake, worker):
    idea = services.capture(alice, "Restore drills\nRun one every quarter.", tags=["ops"])
    source = research.add_note(alice, "Teams that rehearse restores recover twice as fast.", title="Drill study")
    idea.sources.add(source)
    fake.script += [{"text": "# Restore drills\n\nRun them."}, {"text": json.dumps(DETAIL)}]
    idea, brief, page, run = worker(services.promote, idea, user=alice, to="brief", generate=True)
    assert page is None and fresh(idea).status == "promoted" and idea.brief == brief
    brief, run = fresh(brief), fresh(run)
    assert run.status == "succeeded" and brief.status == Brief.READY and brief.assistant.name == "Article writer"
    assert Citation.objects.filter(brief=brief, source=source).exists()
    request = fake.calls[0]["messages"][0]["content"]
    assert request.startswith("Write a piece from this idea.\n\nIdea: Restore drills\n\nRun one every quarter.")
    assert "Tags: ops" in request and "Teams that rehearse restores recover twice as fast." in request
    assert AgentRun.objects.filter(pk=run.pk, agent__slug="assistant").exists()


@pytest.mark.django_db
def test_an_idea_is_promoted_to_an_article_or_a_book_draft_never_a_live_page(alice, bob, site_root):
    idea = services.capture(alice, "Restore drills\nRun one every quarter.")
    with pytest.raises(Invalid, match="parent page"):
        services.promote(idea, user=alice, to="article")
    with pytest.raises(Forbidden):
        services.promote(idea, user=bob, to="article", parent=site_root)
    idea, _, page, _ = services.promote(idea, user=alice, to="article", parent=site_root)
    page = ArticlePage.objects.get(pk=page.pk)
    assert not page.live and page.title == "Restore drills" and idea.page_id == page.pk
    assert [(b.block_type, b.value) for b in page.get_latest_revision_as_object().body] == [
        ("markdown", "Run one every quarter.")
    ]
    book = services.capture(alice, "The restore handbook")
    _, _, made, _ = services.promote(book, user=alice, to="book", parent=site_root)
    assert BookPage.objects.filter(pk=made.pk, live=False).exists()
    with pytest.raises(Invalid):
        services.promote(book, user=alice, to="poem")
