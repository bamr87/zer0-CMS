"""parodynews → the platform (M6, G8, PLAN §4.4): posts become article pages
and their version history revisions in order; every AI table maps onto the AI
content layer (ADR 0006 decision 7) — providers without their credentials,
models, schemas, assistants, groups as pipelines, content details as briefs,
threads and messages as conversations — owned as parodynews owned them; a
re-run changes nothing, and a re-run on a fresh dump leaves alone what people
changed here (`--force` aside; an applied brief keeps its draft even then)."""

import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from wagtail.models import Revision

from agents.models import AgentDefinition
from ai import services
from ai.models import (
    Assistant,
    Brief,
    Conversation,
    Message,
    ModelEntry,
    OutputSchema,
    Pipeline,
    ProviderConfig,
    Visibility,
)
from ai.services import stable_id
from cms.models import ArticlePage
from cms.services import save_draft
from importers.models import ImportedSource
from importers.parodynews import import_dump

DUMP = Path(__file__).resolve().parent.parent / "fixtures" / "parodynews" / "dumpdata.json"


@pytest.mark.django_db
def test_posts_and_their_versions_are_imported():
    report = import_dump(str(DUMP))
    assert len(report.pages_created) == 2 and report.revisions == 2
    source = ImportedSource.objects.get(site_key="parodynews", legacy_path="parodynews.post:1")
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
    assert not AgentDefinition.objects.filter(slug__startswith="legacy-").exists()  # assistants are ai.Assistant now


@pytest.mark.django_db
def test_providers_models_schemas_and_assistants_map_without_credentials():
    report = import_dump(str(DUMP))
    anthropic = ProviderConfig.objects.get(slug="anthropic")
    assert (
        anthropic.is_default
        and anthropic.default_model == "claude-sonnet-5-5"
        and anthropic.extra == {"effort": "high"}
    )
    assert not anthropic.has_credential and report.providers == ["anthropic", "fake"]
    assert any("grok" in s for s in report.skipped) and any("Broken" in s for s in report.skipped)
    assert "NEVER-IMPORTED" not in json.dumps(list(ProviderConfig.objects.values()), default=str)
    sonnet = ModelEntry.objects.get(provider__slug="anthropic", model_id="claude-sonnet-5-5")
    mock = ModelEntry.objects.get(provider__slug="fake", model_id="mock-1")
    assert sonnet.display_name == "Sonnet" and not mock.active
    headline = OutputSchema.objects.get(public_id=stable_id("parodynews.jsonschema", 1))
    assert headline.visibility == Visibility.SHARED and headline.schema["required"] == ["headline"]
    writer = Assistant.objects.get(public_id=stable_id("parodynews.assistant", "asst_1"))
    assert writer.instructions == "You write gentle parody news.\n\nWrite a short article."
    assert (writer.model, writer.provider, writer.params) == (sonnet, anthropic, {"temperature": 0.7})
    headliner = Assistant.objects.get(public_id=stable_id("parodynews.assistant", "asst_2"))
    assert headliner.instructions == "You write headlines." and headliner.output_schema == headline
    assert headliner.params == {"top_p": 0.9} and headliner.tools == [] and headliner.visibility == Visibility.SHARED
    assert sorted(report.assistants) == ["Headliner", "News Writer"]


@pytest.mark.django_db
def test_groups_briefs_and_threads_map_onto_pipelines_briefs_and_conversations():
    alice = get_user_model().objects.create_user("alice")
    import_dump(str(DUMP))
    pipeline = Pipeline.objects.get(public_id=stable_id("parodynews.assistantgroup", 1))
    assert [(s.position, s.assistant.name, s.source) for s in pipeline.steps.order_by("position")] == [
        (1, "News Writer", "conversation"),
        (2, "Headliner", "conversation"),
    ]
    posted = Brief.objects.get(public_id=stable_id("parodynews.contentdetail", 1))
    page = ImportedSource.objects.get(legacy_path="parodynews.post:1").page
    assert posted.status == Brief.APPLIED and posted.page_id == page.pk and posted.visibility == Visibility.SHARED
    assert posted.prompt == "Write about a cat and a sofa." and posted.metadata["keywords"] == ["cats", "politics"]
    dogs = Brief.objects.get(public_id=stable_id("parodynews.contentdetail", 2))
    assert dogs.status == Brief.READY and dogs.markdown == "Dogs are fine.\n\nStill fine." and dogs.owner == alice
    assert dogs.visibility == Visibility.PRIVATE and dogs.assistant.name == "News Writer"
    assert not Brief.objects.filter(public_id=stable_id("parodynews.contentdetail", 3)).exists()  # a thread's container
    chat = Conversation.objects.get(public_id=stable_id("parodynews.thread", "thread_1"))
    assert (chat.title, chat.owner, chat.pipeline, chat.created_at.month) == ("Cat chat", alice, pipeline, 7)
    assert list(chat.messages.values_list("seq", "role", "text", "status")) == [
        (1, "user", "Tell me about the cat.", "completed"),
        (2, "assistant", "It declared independence.", "completed"),
        (3, "assistant", "", "failed"),
        (4, "assistant", "", "failed"),
    ]
    second, third, fourth = chat.messages.filter(seq__gte=2).order_by("seq")
    assert (second.provider, second.model, second.usage) == (
        "anthropic",
        "claude-sonnet-5-5",
        {"input_tokens": 20, "output_tokens": 6},
    )
    assert (third.provider, third.error) == ("fake", "rate limited") and fourth.error == "interrupted before the import"
    orphan = Conversation.objects.get(public_id=stable_id("parodynews.thread", "thread_2"))
    assert orphan.owner is None and orphan.visibility == Visibility.PRIVATE
    assert not Conversation.objects.visible_to(alice).filter(pk=orphan.pk).exists()


@pytest.mark.django_db
def test_a_second_import_changes_nothing():
    import_dump(str(DUMP))
    revisions = Revision.objects.count()

    def snapshot():
        return [
            sorted(map(str, model.objects.values_list("public_id", flat=True)))
            for model in (Assistant, Brief, Conversation, Message, OutputSchema, Pipeline, ModelEntry)
        ] + [list(Message.objects.order_by("public_id").values("seq", "text", "status"))]

    before = snapshot()
    again = import_dump(str(DUMP))
    assert again.pages_created == [] and len(again.pages_unchanged) == 2 and Revision.objects.count() == revisions
    assert snapshot() == before
    assert Brief.objects.get(public_id=stable_id("parodynews.contentdetail", 1)).status == Brief.APPLIED


def fresh(row):
    row.refresh_from_db()
    return row


@pytest.mark.django_db
def test_a_re_import_leaves_what_people_changed_here_and_force_overwrites_all_but_an_applied_brief(editor):
    import_dump(str(DUMP))
    writer = Assistant.objects.get(public_id=stable_id("parodynews.assistant", "asst_1"))
    Assistant.objects.filter(pk=writer.pk).update(instructions="Edited here.")
    ProviderConfig.objects.filter(slug="anthropic").update(default_model="claude-opus-5-5")
    dogs = Brief.objects.get(public_id=stable_id("parodynews.contentdetail", 2))
    posts = ImportedSource.objects.get(legacy_path="parodynews.post:1").page.get_parent()
    page, _ = services.apply_brief(dogs, user=editor, parent=posts)
    again = import_dump(str(DUMP))
    assert sorted(c.split(":")[0] for c in again.conflicts) == ["assistant", "contentdetail", "provider"]
    assert fresh(writer).instructions == "Edited here."
    assert ProviderConfig.objects.get(slug="anthropic").default_model == "claude-opus-5-5"
    assert (fresh(dogs).status, fresh(dogs).page_id) == (Brief.APPLIED, page.pk)  # not to be applied twice
    forced = import_dump(str(DUMP), force=True)
    assert (
        forced.conflicts == []
        and fresh(writer).instructions == "You write gentle parody news.\n\nWrite a short article."
    )
    assert ProviderConfig.objects.get(slug="anthropic").default_model == "claude-sonnet-5-5"
    assert (fresh(dogs).status, fresh(dogs).page_id) == (Brief.APPLIED, page.pk)
    assert import_dump(str(DUMP)).conflicts == []


@pytest.mark.django_db
def test_a_message_new_in_the_dump_goes_after_what_people_added_here():
    get_user_model().objects.create_user("alice")
    rows = json.loads(DUMP.read_text())
    import_dump(rows)
    chat = Conversation.objects.get(public_id=stable_id("parodynews.thread", "thread_1"))
    services.append(chat, role=Message.USER, text="Added here.")
    item = {"line_number": 3, "content_type": "message", "content_text": "A new reply.", "assistant": "asst_1"}
    message = {"role": "assistant", "created_at": "2025-07-01T12:04:00Z", "contentitem": 6, "thread": "thread_1"}
    rows += [
        {"model": "parodynews.contentitem", "pk": 6, "fields": {**item, "prompt": "", "detail": 3}},
        {
            "model": "parodynews.message",
            "pk": "msg_5",
            "fields": {**message, "assistant": "asst_1", "status": "completed"},
        },
    ]
    report = import_dump(rows)
    assert report.conflicts == []
    assert list(chat.messages.values_list("seq", "text"))[-2:] == [(5, "Added here."), (6, "A new reply.")]
    deleted = chat.messages.get(seq=1)
    deleted.delete()
    assert [c.split(":")[0] for c in import_dump(rows).conflicts] == ["message"]  # a deletion here stands
    assert not chat.messages.filter(seq=1).exists()


@pytest.mark.django_db
def test_a_post_edited_here_is_not_overwritten_by_a_changed_dump(editor):
    rows = json.loads(DUMP.read_text())
    import_dump(rows)
    page = ImportedSource.objects.get(legacy_path="parodynews.post:1").page.specific
    page.title = "Edited here"
    save_draft(page, user=editor)
    post = next(r for r in rows if r["model"] == "parodynews.post" and r["pk"] == 1)
    post["fields"]["post_content"] = "# Breaking\n\nChanged in barodybroject."
    report = import_dump(rows)
    assert report.conflicts == ["parodynews.post:1: changed here since the last import (pass --force to overwrite)"]

    def title():
        return ArticlePage.objects.get(pk=page.pk).get_latest_revision_as_object().title

    assert title() == "Edited here"
    assert "parodynews.post:1" in import_dump(rows, force=True).pages_created
    assert title() == "Local Cat Declares Independence"
