"""`/api/v2/ai/` (ai/views.py): signed-in only; rows scoped by `visible_to`
(another person's private row is a 404, changing a visible one you do not own
a 403); providers configured by staff with a write-only credential; anything
that reaches a model answers 202 with the run to follow on the existing
`/api/v2/agent-runs/<id>/stream/`, executed here as the worker would after
commit; an `Idempotency-Key` replays the first answer. The fake provider
answers; nothing reaches a model."""

import json
from datetime import timedelta

import pytest
from django.utils import timezone

from agents.models import AgentRun
from ai.models import (
    Assistant,
    Brief,
    Conversation,
    IdempotencyKey,
    Message,
    ModelEntry,
    OutputSchema,
    ProviderConfig,
    Visibility,
)
from suggestions.models import Suggestion

from .test_services import DETAIL, STORY

BASE = "/api/v2/ai"


def ran(response):
    """The run a 202 points at, as it is after the worker ran it."""
    assert response.status_code == 202, response.content
    run = response.json()["run"]
    assert run["links"] == {
        "self": f"/api/v2/agent-runs/{run['id']}/",
        "stream": f"/api/v2/agent-runs/{run['id']}/stream/",
    }
    return AgentRun.objects.get(pk=run["id"])


@pytest.mark.django_db
def test_every_endpoint_needs_a_signed_in_person(api):
    for path in ("providers/", "models/", "output-schemas/", "assistants/", "pipelines/", "briefs/", "conversations/"):
        response = api().get(f"{BASE}/{path}")
        assert response.status_code == 401 and response.json()["error"]["code"] == "auth.required"


# ── providers and models ───────────────────────────────────────────────────


@pytest.mark.django_db
def test_providers_are_listed_for_everyone_and_configured_by_staff_with_a_write_only_credential(api, alice, staff):
    listed = api(alice).get(f"{BASE}/providers/").json()
    assert {p["slug"] for p in listed["results"]} >= {
        "anthropic",
        "claude_code",
        "openai",
        "litellm",
        "fake",
        "recorded",
    }
    anthropic = next(p for p in listed["results"] if p["slug"] == "anthropic")
    assert "credential" not in anthropic and not anthropic["has_credential"] and "tools" in anthropic["capabilities"]
    url = f"{BASE}/providers/{anthropic['id']}/"
    assert api(alice).patch(url, {"enabled": False}, format="json").status_code == 403
    response = api(staff).patch(
        url, {"credential": "sk-ant-api-secret", "default_model": "claude-sonnet-5-5"}, format="json"
    )
    assert response.status_code == 200 and response.json()["has_credential"] and "credential" not in response.json()
    assert response.json()["credential_source"] == "database" and "secret" not in response.content.decode()
    row = ProviderConfig.objects.get(slug="anthropic")
    assert row.get_credential() == "sk-ant-api-secret" and "secret" not in row.credential_encrypted
    assert "secret" not in api(staff).get(url).content.decode()
    assert api(staff).patch(url, {"credential": ""}, format="json").json()["has_credential"] is False


@pytest.mark.django_db
def test_staff_test_a_provider_sync_its_models_and_set_the_default(
    api, alice, staff, fake, django_capture_on_commit_callbacks
):
    fake_id = str(ProviderConfig.objects.get(slug="fake").public_id)
    assert api(alice).post(f"{BASE}/providers/{fake_id}/test/").status_code == 403
    fake.script.append({"text": "OK"})
    with django_capture_on_commit_callbacks(execute=True):
        run = ran(api(staff).post(f"{BASE}/providers/{fake_id}/test/"))
    assert (
        AgentRun.objects.get(pk=run.pk).status == "succeeded"
        and ProviderConfig.objects.get(slug="fake").last_health["ok"]
    )
    with django_capture_on_commit_callbacks(execute=True):
        ran(api(staff).post(f"{BASE}/providers/{fake_id}/sync-models/"))
    models = api(alice).get(f"{BASE}/models/", {"provider": "fake", "active": "true"}).json()["results"]
    assert [m["model_id"] for m in models] == ["fake-1"] and models[0]["provider"] == "fake"
    assert api(alice).get(f"{BASE}/models/", {"provider": "openai"}).json()["results"] == []
    response = api(staff).post(f"{BASE}/providers/{fake_id}/set-default/")
    assert response.status_code == 200 and response.json()["is_default"]
    assert api(staff).patch(f"{BASE}/providers/{fake_id}/", {"enabled": False}, format="json").status_code == 422


# ── output schemas ─────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_output_schemas_are_validated_exported_and_bundled(api, alice, staff):
    created = api(alice).post(f"{BASE}/output-schemas/", {"name": "Story", "schema": STORY}, format="json")
    assert created.status_code == 201 and created.json()["owner"] == "alice" and created.json()["version"] == 1
    bad = api(alice).post(f"{BASE}/output-schemas/", {"name": "Bad", "schema": {"type": 7}}, format="json")
    assert bad.status_code == 422 and "not a valid JSON Schema" in json.dumps(bad.json())
    exported = api(alice).get(f"{BASE}/output-schemas/{created.json()['id']}/export/").json()
    assert exported == {"name": "Story", "description": "", "version": 1, "schema": STORY, "render_template": ""}
    listed = api(alice).get(f"{BASE}/output-schemas/", {"bundled": "true"}).json()["results"]
    assert sorted(s["name"] for s in listed) == ["Content detail", "News article", "Parody news article"]
    bundled = listed[0]["id"]
    assert api(alice).patch(f"{BASE}/output-schemas/{bundled}/", {"name": "mine now"}, format="json").status_code == 403
    assert api(alice).post(f"{BASE}/output-schemas/import-bundled/").status_code == 403
    imported = api(staff).post(f"{BASE}/output-schemas/import-bundled/").json()
    assert len(imported["schemas"]) == 3 and len(imported["assistants"]) == 1
    assert OutputSchema.objects.filter(bundled=True).count() == 3


# ── assistants: visibility, runs, idempotency ──────────────────────────────


@pytest.mark.django_db
def test_assistants_are_scoped_by_visibility_and_changed_only_by_their_owner(api, alice, bob):
    private = api(alice).post(f"{BASE}/assistants/", {"name": "Mine", "instructions": "x"}, format="json").json()
    shared = api(alice).post(f"{BASE}/assistants/", {"name": "Ours", "visibility": "shared"}, format="json").json()
    assert private["effect"] == "propose" and private["owner"] == "alice" and private["visibility"] == "private"
    names = {a["name"] for a in api(bob).get(f"{BASE}/assistants/").json()["results"]}
    assert "Ours" in names and "Mine" not in names
    assert api(bob).get(f"{BASE}/assistants/{private['id']}/").status_code == 404
    assert api(bob).patch(f"{BASE}/assistants/{shared['id']}/", {"name": "taken"}, format="json").status_code == 403
    assert api(bob).delete(f"{BASE}/assistants/{shared['id']}/").status_code == 403
    assert (
        api(alice).patch(f"{BASE}/assistants/{shared['id']}/", {"name": "Ours, renamed"}, format="json").status_code
        == 200
    )
    bad = api(alice).post(f"{BASE}/assistants/", {"name": "W", "tools": ["content.publish"]}, format="json")
    assert bad.status_code == 422 and "read-only tools" in json.dumps(bad.json())
    hidden = api(bob).post(f"{BASE}/assistants/", {"name": "B", "output_schema": private["id"]}, format="json")
    assert hidden.status_code == 422  # someone else's private row cannot be named
    assert api(alice).post(f"{BASE}/assistants/", {"name": "S", "visibility": "site"}, format="json").status_code == 422


@pytest.mark.django_db
def test_running_a_visible_assistant_is_a_202_with_the_run_and_a_key_replays_it(
    api, alice, bob, fake, django_capture_on_commit_callbacks
):
    shared = Assistant.objects.create(owner=alice, name="Ours", visibility=Visibility.SHARED, instructions="Be brief.")
    url = f"{BASE}/assistants/{shared.public_id}/run/"
    fake.script.append({"text": "Brief answer."})
    with django_capture_on_commit_callbacks(execute=True):
        response = api(bob).post(url, {"prompt": "hi"}, format="json", HTTP_IDEMPOTENCY_KEY="k-1")
    run = ran(response)
    assert run.status == "succeeded" and run.output["text"] == "Brief answer." and run.started_by == bob
    detail = api(bob).get(f"/api/v2/agent-runs/{run.pk}/").json()
    assert detail["agent"] == "assistant" and detail["steps"][0]["kind"] == "llm"
    stream = api(bob).get(f"/api/v2/agent-runs/{run.pk}/stream/")
    assert b'"status": "succeeded"' in b"".join(stream.streaming_content)
    again = api(bob).post(url, {"prompt": "hi"}, format="json", HTTP_IDEMPOTENCY_KEY="k-1")
    assert again.status_code == 202 and again.json() == response.json() and again["Idempotent-Replayed"] == "true"
    assert AgentRun.objects.filter(input__kind="assistant").count() == 1
    changed = api(bob).post(url, {"prompt": "other"}, format="json", HTTP_IDEMPOTENCY_KEY="k-1")
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "request.idempotency"
    other_person = api(alice).post(url, {"prompt": "hi"}, format="json", HTTP_IDEMPOTENCY_KEY="k-1")
    assert other_person.status_code == 202 and other_person.json()["run"]["id"] != run.pk
    assert api(bob).post(url, {}, format="json").status_code == 422
    IdempotencyKey.objects.filter(user=bob).update(created_at=timezone.now() - timedelta(days=2))
    expired = api(bob).post(url, {"prompt": "other"}, format="json", HTTP_IDEMPOTENCY_KEY="k-1")
    assert expired.status_code == 202 and expired.json()["run"]["id"] not in (run.pk, other_person.json()["run"]["id"])
    assert IdempotencyKey.objects.filter(user=bob, key="k-1").count() == 1  # the expired answer is gone


# ── pipelines ──────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_pipeline_is_written_with_its_steps_and_run(api, alice, fake, django_capture_on_commit_callbacks):
    one = Assistant.objects.create(owner=alice, name="One")
    two = Assistant.objects.create(owner=alice, name="Two")
    body = {
        "name": "Two steps",
        "steps": [{"assistant": str(one.public_id)}, {"assistant": str(two.public_id), "source": "conversation"}],
    }
    created = api(alice).post(f"{BASE}/pipelines/", body, format="json")
    assert created.status_code == 201, created.content
    assert [(s["position"], s["source"]) for s in created.json()["steps"]] == [(1, "previous"), (2, "conversation")]
    url = f"{BASE}/pipelines/{created.json()['id']}/"
    swapped = api(alice).patch(url, {"steps": [{"assistant": str(two.public_id)}]}, format="json").json()
    assert [s["assistant"] for s in swapped["steps"]] == [str(two.public_id)]
    fake.script.append({"text": "done"})
    with django_capture_on_commit_callbacks(execute=True):
        run = ran(api(alice).post(f"{url}run/", {"prompt": "go"}, format="json"))
    run.refresh_from_db()
    assert run.status == "succeeded" and run.children.count() == 1
    assert api(alice).delete(f"{BASE}/assistants/{two.public_id}/").status_code == 409  # a pipeline uses it


# ── briefs ─────────────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_brief_is_generated_as_a_run_and_applied_as_a_draft_with_suggestions(
    api, alice, bob, fake, site_root, django_capture_on_commit_callbacks
):
    schema = OutputSchema.objects.create(
        owner=alice, name="Story", schema=STORY, render_template="## {{ headline }}\n\n{{ body }}"
    )
    writer = Assistant.objects.create(owner=alice, name="Writer", output_schema=schema)
    created = api(alice).post(
        f"{BASE}/briefs/", {"prompt": "cats", "assistant": str(writer.public_id), "parent": site_root.pk}, format="json"
    )
    assert created.status_code == 201 and created.json()["status"] == "draft"
    url = f"{BASE}/briefs/{created.json()['id']}/"
    assert api(bob).post(f"{url}generate/").status_code == 404
    fake.script += [{"text": json.dumps({"headline": "Why cats", "body": "They rule."})}, {"text": json.dumps(DETAIL)}]
    with django_capture_on_commit_callbacks(execute=True):
        response = api(alice).post(f"{url}generate/")
    assert response.json()["brief"]["status"] == "generating"
    ran(response)
    brief = api(alice).get(url).json()
    assert (
        brief["status"] == "ready"
        and brief["markdown"] == "## Why cats\n\nThey rule."
        and brief["title"] == "Cats Rule the Sofa"
    )
    edited = api(alice).patch(url, {"metadata": {**brief["metadata"], "title": "Cats, Edited"}}, format="json")
    assert edited.status_code == 200
    applied = api(alice).post(f"{url}apply/", {}, format="json")
    assert applied.status_code == 201, applied.content
    page_id, suggestions = applied.json()["page_id"], applied.json()["suggestions"]
    assert applied.json()["brief"]["status"] == "applied" and applied.json()["brief"]["page"] == page_id
    assert Suggestion.objects.filter(pk__in=suggestions, status="pending").count() == len(suggestions) == 4
    from wagtail.models import Page

    page = Page.objects.get(pk=page_id)
    assert page.title == "Cats, Edited" and not page.live
    assert api(alice).post(f"{url}apply/", {}, format="json").status_code == 409
    assert api(alice).patch(url, {"prompt": "again"}, format="json").status_code == 422
    listed = api(alice).get(f"{BASE}/briefs/", {"status": "applied", "assistant": str(writer.public_id)}).json()
    assert [b["id"] for b in listed["results"]] == [created.json()["id"]]


# ── conversations and messages ─────────────────────────────────────────────


@pytest.mark.django_db
def test_a_conversation_takes_messages_lists_them_by_cursor_and_promotes_one(
    api, alice, bob, fake, django_capture_on_commit_callbacks
):
    chat = Assistant.objects.create(owner=alice, name="Chat")
    created = api(alice).post(
        f"{BASE}/conversations/", {"title": "Ideas", "assistant": str(chat.public_id)}, format="json"
    )
    url = f"{BASE}/conversations/{created.json()['id']}/"
    fake.script.append({"text": "Hello."})
    with django_capture_on_commit_callbacks(execute=True):
        posted = api(alice).post(f"{url}messages/", {"text": "Hi"}, format="json")
    run = ran(posted)
    assert posted.json()["message"]["seq"] == 1 and posted.json()["reply"]["status"] == "queued"
    reply = Message.objects.get(public_id=posted.json()["reply"]["id"])
    assert reply.status == "completed" and reply.text == "Hello." and reply.run_id == run.pk
    quiet = api(alice).post(f"{url}messages/", {"text": "A note", "answer": False}, format="json")
    assert quiet.status_code == 201 and quiet.json()["reply"] is None and quiet.json()["run"] is None
    page_one = api(alice).get(f"{url}messages/", {"page_size": 2}).json()
    assert [m["seq"] for m in page_one["results"]] == [1, 2] and page_one["next"]
    page_two = api(alice).get(page_one["next"]).json()
    assert [m["seq"] for m in page_two["results"]] == [3] and page_two["next"] is None
    assert api(bob).post(f"{url}messages/", {"text": "intrude"}, format="json").status_code == 404
    note = quiet.json()["message"]["id"]
    promoted = api(alice).post(f"{BASE}/messages/{note}/promote/", {"to": "brief"}, format="json")
    assert (
        promoted.status_code == 201
        and promoted.json()["brief"]["prompt"] == "A note"
        and promoted.json()["run"] is None
    )
    fake.script.append({"text": json.dumps(DETAIL)})
    with django_capture_on_commit_callbacks(execute=True):
        drafted = api(alice).post(f"{BASE}/messages/{note}/promote/", {"to": "draft"}, format="json")
    ran(drafted)
    assert Brief.objects.get(public_id=drafted.json()["brief"]["id"]).status == "ready"
    other = Assistant.objects.create(owner=alice, name="Other")
    assigned = api(alice).patch(
        f"{BASE}/messages/{note}/", {"assistant": str(other.public_id), "text": "ignored"}, format="json"
    )
    assert (
        assigned.status_code == 200
        and assigned.json()["assistant"] == str(other.public_id)
        and assigned.json()["text"] == "A note"
    )
    fake.script.append({"text": "Again."})
    with django_capture_on_commit_callbacks(execute=True):
        rerun = api(alice).post(f"{BASE}/messages/{note}/rerun/", {}, format="json")
    ran(rerun)
    assert Message.objects.get(public_id=rerun.json()["message"]["id"]).text == "Again."
    assert Conversation.objects.get(public_id=created.json()["id"]).messages.count() == 4


@pytest.mark.django_db
def test_a_conversation_runs_its_pipeline(api, alice, fake, django_capture_on_commit_callbacks):
    from ai.models import Pipeline, PipelineStep

    pipeline = Pipeline.objects.create(owner=alice, name="P")
    PipelineStep.objects.create(
        pipeline=pipeline, position=1, assistant=Assistant.objects.create(owner=alice, name="A")
    )
    conversation = Conversation.objects.create(owner=alice, pipeline=pipeline)
    url = f"{BASE}/conversations/{conversation.public_id}/run-pipeline/"
    fake.script.append({"text": "Step one."})
    with django_capture_on_commit_callbacks(execute=True):
        ran(api(alice).post(url, {"prompt": ""}, format="json"))
    assert list(conversation.messages.values_list("text", flat=True)) == ["Step one."]
    bare = Conversation.objects.create(owner=alice)
    assert api(alice).post(f"{BASE}/conversations/{bare.public_id}/run-pipeline/", {}, format="json").status_code == 422


@pytest.mark.django_db
def test_lists_filter_order_paginate_and_scope_by_site(api, alice, root_page):
    from wagtail.models import Site

    site = Site.objects.create(hostname="news.example", root_page=root_page, site_name="News")
    Conversation.objects.create(owner=alice, title="b", site=site)
    Conversation.objects.create(owner=alice, title="a")
    Conversation.objects.create(owner=alice, title="c", visibility=Visibility.SHARED)
    listed = api(alice).get(f"{BASE}/conversations/", {"ordering": "title", "page_size": 2}).json()
    assert [c["title"] for c in listed["results"]] == ["a", "b"] and listed["count"] == 3 and listed["next"]
    assert [
        c["title"] for c in api(alice).get(f"{BASE}/conversations/", {"visibility": "shared"}).json()["results"]
    ] == ["c"]
    on_site = api(alice).get(f"{BASE}/conversations/", {"site": site.pk, "ordering": "title"}).json()["results"]
    assert [c["title"] for c in on_site] == ["a", "b", "c"]
    assert api(alice).get(f"{BASE}/conversations/", {"site": 999}).json()["results"] == []
    assert ModelEntry.objects.count() == 0  # nothing synced unless asked


@pytest.mark.django_db
def test_an_assistant_exports_as_a_document_and_imports_as_a_new_private_one(api, alice, bob):
    schema = OutputSchema.objects.create(owner=alice, name="Story", schema=STORY, render_template="# {{ headline }}")
    anthropic = ProviderConfig.objects.get(slug="anthropic")
    model = ModelEntry.objects.create(provider=anthropic, model_id="claude-sonnet-5-5")
    original = Assistant.objects.create(
        owner=alice,
        name="Writer",
        visibility=Visibility.SHARED,
        instructions="Write.",
        provider=anthropic,
        model=model,
        params={"effort": "low"},
        output_schema=schema,
        tools=["content.search"],
    )
    document = api(bob).get(f"{BASE}/assistants/{original.public_id}/export/").json()
    assert document["provider"] == "anthropic" and document["model"] == "claude-sonnet-5-5"
    assert document["output_schema"]["schema"] == STORY and "id" not in document and "owner" not in document
    imported = api(bob).post(f"{BASE}/assistants/import/", document, format="json")
    assert imported.status_code == 201, imported.content
    copy = Assistant.objects.get(public_id=imported.json()["id"])
    assert (copy.owner, copy.visibility, copy.instructions, copy.params, copy.tools) == (
        bob,
        Visibility.PRIVATE,
        "Write.",
        {"effort": "low"},
        ["content.search"],
    )
    assert copy.model == model and copy.output_schema.owner == bob and copy.output_schema.schema == STORY
    broken = {**document, "output_schema": {"name": "x", "schema": {"type": 1}}}
    assert api(bob).post(f"{BASE}/assistants/import/", broken, format="json").status_code == 422
    assert Assistant.objects.filter(owner=bob).count() == 1


@pytest.mark.django_db
def test_a_conversation_starts_from_a_brief_and_its_messages_filter_and_delete(api, alice, bob):
    from ai import services

    brief = Brief.objects.create(owner=alice, prompt="cats", markdown="Cats rule the sofa.")
    body = {"title": "About cats", "from_brief": str(brief.public_id)}
    created = api(alice).post(f"{BASE}/conversations/", body, format="json")
    assert created.status_code == 201 and "from_brief" not in created.json()
    conversation = Conversation.objects.get(public_id=created.json()["id"])
    assert list(conversation.messages.values_list("role", "text")) == [("user", "Cats rule the sofa.")]
    brief.refresh_from_db()
    assert brief.conversation == conversation
    hidden = api(bob).post(f"{BASE}/conversations/", {"from_brief": str(brief.public_id)}, format="json")
    assert hidden.status_code == 422  # alice's private brief cannot be named
    services.append(conversation, role=Message.ASSISTANT, text="Indeed.", status=Message.COMPLETED)
    url = f"{BASE}/conversations/{conversation.public_id}/messages/"
    assert [m["text"] for m in api(alice).get(url, {"role": "assistant"}).json()["results"]] == ["Indeed."]
    first = conversation.messages.get(seq=1)
    assert api(bob).delete(f"{BASE}/messages/{first.public_id}/").status_code == 404
    assert api(alice).delete(f"{BASE}/messages/{first.public_id}/").status_code == 204
    assert list(conversation.messages.values_list("seq", flat=True)) == [2]
