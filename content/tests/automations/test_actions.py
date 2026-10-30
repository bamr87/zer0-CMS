"""What an automation does (PLAN G16): each action runs as the automation's owner — through the services a person's
request goes through, with that person's permissions, which are asked again when it runs — and nothing it does
publishes. Every run logs each action's inputs and outcome with links to the runs and rows it made; a failing action
is recorded and the run stops or goes on as the automation says; a firing over the runs per hour is limited; email
goes to the platform's people within its owner's hourly budget; a webhook is reached through the research fetcher,
within its deadline, signed so that it never fires an automation. The provider is the scripted fake and a webhook is
recorded HTTP: nothing reaches a model or a network."""

import asyncio
import hashlib
import hmac
import json
import time

import httpx
import pytest
from celery.exceptions import SoftTimeLimitExceeded
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core import mail
from django.core.exceptions import ValidationError
from django.test import override_settings

from agents.llm import FakeLLM, use_llm
from agents.models import AgentDefinition, AgentRun
from ai.models import Assistant, Brief, Pipeline, PipelineStep, Visibility
from automations import services
from automations.models import Automation, AutomationRun
from ideas.models import Board, Idea
from newsroom import services as newsroom
from newsroom.models import Story
from outbox.models import OutboxEvent
from tests.ai.test_services import DETAIL

from .conftest import PUBLIC

HOOK = {"kind": "hook", "hook": "act"}


def fired(worker, data=None, hook="act"):
    """Fire the hook and run what it queued; the runs, as they ended."""
    runs = worker(services.fire_hook, hook, data or {})
    for run in runs:
        run.refresh_from_db()
    return runs


def published() -> int:
    return OutboxEvent.objects.filter(type="content.page.published").count()


# ── the AI layer: assistants, pipelines, agents, briefs ────────────────────


@pytest.mark.django_db
def test_an_assistant_runs_as_the_owner_and_answers_in_its_run(alice, bob, make, fake, worker):
    summarizer = Assistant.objects.create(owner=alice, name="Summarizer")
    action = {"kind": "assistant", "assistant": str(summarizer.public_id), "prompt": "Summarize {{ data.url }}"}
    make(alice, HOOK, [action])
    fake.script.append({"text": "A short summary."})
    before = published()
    [run] = fired(worker, {"url": "https://example.com/a"})
    assert run.status == AutomationRun.SUCCEEDED, run.outcomes
    [outcome] = run.outcomes
    started = AgentRun.objects.get(pk=outcome["result"]["run"])
    assert (started.started_by, started.status, started.output["text"]) == (alice, "succeeded", "A short summary.")
    assert started.trigger == "event" and started.started_by_event == f"automation-run:{run.public_id}"
    assert outcome["input"]["prompt"] == "Summarize https://example.com/a"
    assert published() == before

    # Asked again when it runs: an assistant its owner may no longer use fails the action, with the reason.
    shared = Assistant.objects.create(owner=bob, name="Bob's", visibility=Visibility.SHARED)
    make(alice, {"kind": "hook", "hook": "bobs"}, [{**action, "assistant": str(shared.public_id)}])
    Assistant.objects.filter(pk=shared.pk).update(visibility=Visibility.PRIVATE)
    [refused] = fired(worker, hook="bobs")
    assert refused.status == AutomationRun.FAILED and refused.outcomes[0]["status"] == "failed"
    assert "that alice may use" in refused.outcomes[0]["error"]


@pytest.mark.django_db
def test_a_row_its_owner_may_not_use_is_refused_when_saved(alice, bob, make):
    private = Assistant.objects.create(owner=bob, name="Bob's own")
    board = Board.objects.create(owner=bob, name="Bob's board")
    for action in (
        {"kind": "assistant", "assistant": str(private.public_id), "prompt": "hi"},
        {"kind": "idea", "title": "x", "board": str(board.public_id)},
    ):
        with pytest.raises(ValidationError) as refused:
            make(alice, HOOK, [action])
        assert "may use" in refused.value.message_dict["actions"][0]


@pytest.mark.django_db
def test_a_pipeline_runs_as_the_owner(alice, make, fake, worker):
    writer = Assistant.objects.create(owner=alice, name="Writer")
    pipeline = Pipeline.objects.create(owner=alice, name="Write")
    PipelineStep.objects.create(pipeline=pipeline, position=1, assistant=writer)
    make(alice, HOOK, [{"kind": "pipeline", "pipeline": str(pipeline.public_id), "prompt": "About {{ data.topic }}"}])
    fake.script.append({"text": "A draft about tides."})
    [run] = fired(worker, {"topic": "tides"})
    started = AgentRun.objects.get(pk=run.outcomes[0]["result"]["run"])
    assert run.status == AutomationRun.SUCCEEDED and started.started_by == alice and started.status == "succeeded"
    assert started.input["prompt"] == "About tides" and started.children.count() == 1


@pytest.mark.django_db
def test_an_agent_runs_on_a_page_its_owner_may_edit_and_never_one_that_publishes(alice, bob, make, worker, article):
    action = {"kind": "agent", "agent": "seo", "page": "{{ data.page_id }}", "input": {"note": "{{ data.why }}"}}
    make(alice, HOOK, [action])
    with use_llm(FakeLLM([{"text": "The metadata reads well."}])):
        [run] = fired(worker, {"page_id": article.pk, "why": "it went live"})
    started = AgentRun.objects.get(pk=run.outcomes[0]["result"]["run"])
    assert run.status == AutomationRun.SUCCEEDED and started.agent.slug == "seo" and started.target == article
    assert (started.started_by, started.input, started.status) == (alice, {"note": "it went live"}, "succeeded")
    assert started.started_by_event == f"automation-run:{run.public_id}"

    make(bob, {"kind": "hook", "hook": "bob"}, [action])  # bob may not edit the page
    [refused] = fired(worker, {"page_id": article.pk}, hook="bob")
    assert refused.status == AutomationRun.FAILED and "may not edit page" in refused.outcomes[0]["error"]

    publisher = AgentDefinition.objects.create(slug="publisher", name="Publisher", tools=["content.publish"])
    publisher.publish(publisher.save_revision(), skip_eval_gate=True)
    for slug, why in (("publisher", "never publishes"), ("assistant", "its own app"), ("review", "workflow tasks")):
        with pytest.raises(ValidationError) as refused_on_save:
            make(alice, HOOK, [{"kind": "agent", "agent": slug}])
        assert why in refused_on_save.value.message_dict["actions"][0]
    slugs = [a["slug"] for a in services.options()["agents"]]
    assert "seo" in slugs and not {"publisher", "assistant", "review", "brand", "books"} & set(slugs)


@pytest.mark.django_db
def test_a_brief_is_made_and_written_for_a_person_to_apply_never_applied(alice, make, fake, worker):
    writer = Assistant.objects.create(owner=alice, name="Writer")
    action = {
        "kind": "brief",
        "title": "On {{ data.topic }}",
        "prompt": "Write about {{ data.topic }}",
        "assistant": str(writer.public_id),
        "generate": True,
    }
    make(alice, HOOK, [action], visibility=Visibility.SHARED)  # the automation is shared; what it writes is hers
    fake.script += [{"text": "Tides rise twice a day."}, {"text": json.dumps(DETAIL)}]
    before = published()
    [run] = fired(worker, {"topic": "tides"})
    brief = Brief.objects.get(public_id=run.outcomes[0]["result"]["brief"])
    assert run.status == AutomationRun.SUCCEEDED and run.outcomes[0]["result"]["run"] == brief.run_id
    assert (brief.owner, brief.prompt, brief.status) == (alice, "Write about tides", "ready")
    assert brief.visibility == Visibility.PRIVATE
    assert run.outcomes[0]["input"]["title"] == "On tides"  # the title it was made with; writing it found a better one
    assert brief.page is None and published() == before  # a person applies it; nothing went live


@pytest.mark.django_db
def test_an_idea_is_captured_on_a_board_its_owner_sees(alice, make, worker):
    board = Board.objects.create(owner=alice, name="Pitches")
    action = {"kind": "idea", "title": "{{ data.title }}", "notes": "Seen at {{ data.url }}", "url": "{{ data.url }}"}
    make(alice, HOOK, [{**action, "board": str(board.public_id), "tags": ["wire"]}])
    [run] = fired(worker, {"title": "A bridge vote", "url": "https://news.example.com/w-1"})
    idea = Idea.objects.get(public_id=run.outcomes[0]["result"]["idea"])
    assert (idea.owner, idea.board, idea.title, idea.url) == (
        alice,
        board,
        "A bridge vote",
        "https://news.example.com/w-1",
    )
    assert idea.notes == "Seen at https://news.example.com/w-1" and list(idea.tags.names()) == ["wire"]


# ── notifications ──────────────────────────────────────────────────────────


def addressed(user, email):
    user.email = email
    user.save(update_fields=["email"])
    return user


@pytest.mark.django_db
def test_an_email_goes_to_the_platforms_people_through_its_mail(alice, bob, make, worker):
    addressed(bob, "bob@example.com")
    action = {
        "kind": "email",
        "to": ["Bob@Example.com"],
        "subject": "Finding: {{ data.rule }}",
        "body": "On {{ data.url }}",
    }
    automation = make(alice, HOOK, [action])
    [run] = fired(worker, {"rule": "broken-link", "url": "https://example.com/a"})
    assert run.status == AutomationRun.SUCCEEDED
    [sent] = mail.outbox
    assert (sent.to, sent.subject, sent.body) == (
        ["Bob@Example.com"],
        "Finding: broken-link",
        "On https://example.com/a",
    )
    assert sent.tags == ["automation"]  # what the mail provider sees: it is an automation's, and whose
    assert sent.metadata == {"automation": str(automation.public_id), "run": str(run.public_id)}
    with pytest.raises(ValidationError):
        make(alice, HOOK, [{**action, "to": ["not an address"]}])

    # Asked again when it runs: someone who has left the platform is mailed no longer.
    bob.is_active = False
    bob.save(update_fields=["is_active"])
    [gone] = fired(worker)
    assert gone.status == AutomationRun.FAILED and "not the address of a person" in gone.outcomes[0]["error"]
    assert len(mail.outbox) == 1

    # Anyone else's address is refused when it is saved, unless its owner may email anyone.
    outside = {**action, "to": ["someone@elsewhere.example"]}
    with pytest.raises(ValidationError) as refused:
        make(alice, {"kind": "hook", "hook": "out"}, [outside])
    assert "not the address of a person on the platform" in refused.value.message_dict["actions"][0]
    alice.user_permissions.add(Permission.objects.get(codename="email_anyone"))
    make(get_user_model().objects.get(pk=alice.pk), {"kind": "hook", "hook": "out"}, [outside])
    [out] = fired(worker, hook="out")
    assert out.status == AutomationRun.SUCCEEDED and mail.outbox[-1].to == ["someone@elsewhere.example"]


@pytest.mark.django_db
@override_settings(AUTOMATIONS_EMAILS_PER_HOUR=3)
def test_a_persons_automations_send_so_many_emails_an_hour_and_no_more(alice, bob, make, worker):
    two = {"kind": "email", "to": [addressed(alice, "alice@example.com").email, addressed(bob, "b@example.com").email]}
    make(alice, {"kind": "hook", "hook": "one"}, [{**two, "subject": "One"}])
    make(alice, {"kind": "hook", "hook": "two"}, [{**two, "subject": "Two"}])
    [first] = fired(worker, hook="one")
    [second] = fired(worker, hook="two")  # another of her automations: the budget is hers, across all of them
    assert first.status == AutomationRun.SUCCEEDED and second.status == AutomationRun.FAILED
    assert "at most 3 emails an hour" in second.outcomes[0]["error"]
    assert [m.subject for m in mail.outbox] == ["One"]


@pytest.mark.django_db
def test_a_webhook_is_notified_signed_through_the_ssrf_guard(alice, make, worker, web):
    automation = make(alice, HOOK, [{"kind": "webhook", "url": "https://hooks.example.com/notify"}])
    route = web.post(f"https://{PUBLIC}/notify").respond(204)
    before = int(time.time())
    [run] = fired(worker, {"rule": "broken-link"})
    assert run.status == AutomationRun.SUCCEEDED and run.outcomes[0]["result"] == {"http_status": 204}
    request = route.calls.last.request
    body = json.loads(request.content)
    assert body["run"] == str(run.public_id) and body["payload"]["data"] == {"rule": "broken-link"}
    # Signed over its time and its body, so a receiver can refuse an old one.
    sent = dict(part.split("=", 1) for part in request.headers["X-Zer0-Signature"].split(","))
    assert int(sent["t"]) >= before and "X-Zer0-Signature-256" not in request.headers
    signed = f"{sent['t']}.".encode() + request.content
    assert sent["v1"] == hmac.new(automation.get_secret().encode(), signed, hashlib.sha256).hexdigest()
    assert request.headers["Host"] == "hooks.example.com"  # the name, sent to the address the guard checked

    route.respond(500)
    [failed] = fired(worker)
    assert failed.status == AutomationRun.FAILED and "HTTP 500" in failed.outcomes[0]["error"]

    make(alice, {"kind": "hook", "hook": "inside"}, [{"kind": "webhook", "url": "https://intranet.example.com/x"}])
    [inside] = fired(worker, hook="inside")
    assert inside.status == AutomationRun.FAILED and "not a public address" in inside.outcomes[0]["error"]
    with pytest.raises(ValidationError):  # a private address written out is refused when it is saved
        make(alice, HOOK, [{"kind": "webhook", "url": "http://10.0.0.5/hook"}])


@pytest.mark.django_db
def test_a_webhook_never_calls_an_automation_and_what_one_sends_never_fires_one(alice, make, worker, web, api):
    """One automation never sets another off — itself included — through a webhook: an automation's endpoint is refused
    as an action's URL, here or elsewhere, and a request an automation sent is not one an automation accepts."""
    listener = make(alice, {"kind": "webhook"}, [{"kind": "idea", "title": "Heard"}])
    for url in (
        f"https://hooks.example.com/api/v2/automations/{listener.public_id}/webhook/",
        f"https://hooks.example.com/cms/api/v2/automations/{listener.public_id}/webhook",
        "https://hooks.example.com/api/v2/automations/x%2Fwebhook/",
    ):
        with pytest.raises(ValidationError) as refused:
            make(alice, HOOK, [{"kind": "webhook", "url": url}])
        assert "never calls an automation's webhook" in refused.value.message_dict["actions"][0], url

    # What an automation sends, replayed to the automation's own endpoint as it was sent, fires nothing.
    make(alice, {"kind": "hook", "hook": "tell"}, [{"kind": "webhook", "url": "https://hooks.example.com/notify"}])
    route = web.post(f"https://{PUBLIC}/notify").respond(204)
    automation = Automation.objects.get(trigger__hook="tell")
    Automation.objects.filter(pk=listener.pk).update(secret_encrypted=automation.secret_encrypted)  # one secret
    fired(worker, hook="tell")
    sent = route.calls.last.request
    headers = {
        f"HTTP_{name.upper().replace('-', '_')}": value for name, value in sent.headers.items() if name.startswith("x-")
    }
    assert set(headers) == {"HTTP_X_ZER0_SIGNATURE", "HTTP_X_ZER0_DELIVERY"}
    path = f"/api/v2/automations/{listener.public_id}/webhook/"
    replayed = worker(api().post, path, data=sent.content, content_type="application/json", **headers)
    assert replayed.status_code == 401
    # Nor with its MAC moved to the header an automation reads: it signs `<t>.<body>`, which is never JSON.
    t, v1 = (part.split("=", 1)[1] for part in sent.headers["X-Zer0-Signature"].split(","))
    moved = worker(
        api().post,
        path,
        data=f"{t}.".encode() + sent.content,
        content_type="application/json",
        HTTP_X_ZER0_SIGNATURE_256=f"sha256={v1}",
    )
    assert moved.status_code == 422 and not AutomationRun.objects.filter(automation=listener).exists()


@pytest.mark.django_db
@override_settings(RESEARCH_FETCH_TIMEOUT=0.3)
def test_a_slow_webhook_is_cut_off_at_the_fetchers_deadline_and_a_late_action_does_not_start(
    alice, make, worker, web, monkeypatch
):
    async def late(request):
        await asyncio.sleep(5)
        return httpx.Response(204)

    web.post(f"https://{PUBLIC}/slow").mock(side_effect=late)
    slow = {"kind": "webhook", "url": "https://hooks.example.com/slow"}
    make(alice, HOOK, [slow, {"kind": "idea", "title": "After it"}], on_error=Automation.CONTINUE)
    started = time.monotonic()
    [run] = fired(worker)
    assert time.monotonic() - started < 3  # the whole exchange, not each read, is bounded
    assert run.status == AutomationRun.FAILED and "did not answer within 0.3 seconds" in run.outcomes[0]["error"]
    assert run.outcomes[1]["status"] == "succeeded"

    monkeypatch.setattr(services, "RUN_SECONDS", 0.1)  # the second action would start after the run's time
    [late_run] = fired(worker)
    assert [o["status"] for o in late_run.outcomes] == ["failed", "not_run"]
    assert late_run.status == AutomationRun.FAILED and late_run.error.startswith("out of time")
    assert Idea.objects.count() == 1


@pytest.mark.django_db
def test_a_run_its_task_stops_at_the_time_limit_is_recorded_never_left_running(alice, make, worker, monkeypatch):
    def stopped(given, run, owner):
        raise SoftTimeLimitExceeded()  # what Celery raises inside the task at its soft limit (tasks.py)

    monkeypatch.setitem(services.ACTS, "idea", stopped)
    make(alice, HOOK, [{"kind": "idea", "title": "Never made"}])
    [run] = fired(worker)
    assert run.status == AutomationRun.FAILED and run.finished_at is not None
    assert run.outcomes[0] | {"ms": 0} == {
        "index": 0,
        "kind": "idea",
        "input": {"title": "Never made"},
        "status": "failed",
        "error": "its run ran out of time",
        "ms": 0,
    }


def test_an_automations_run_waits_on_the_queue_for_work_that_waits_on_other_servers():
    from django.conf import settings

    assert settings.CELERY_TASK_ROUTES["automations.tasks.execute_run"] == {"queue": "research"}


# ── the newsroom ───────────────────────────────────────────────────────────


@pytest.mark.django_db
def test_a_story_moves_to_a_stage_as_its_owner_and_never_to_one_that_publishes(
    ed, reporter, outsider, desk, make, worker
):
    story = newsroom.pitch(desk, user=ed, headline="Bridge vote")
    assign = {"kind": "story", "story": "{{ data.story }}", "to": "assigned", "assignee": "{{ data.who }}"}
    make(ed, HOOK, [{**assign, "comment": "From the wire"}])
    before = published()
    [run] = fired(worker, {"story": str(story.public_id), "who": "reporter"})
    story.refresh_from_db()
    assert run.status == AutomationRun.SUCCEEDED and (story.status, story.assignee) == ("assigned", reporter)
    assert run.outcomes[0]["result"] == {"story": str(story.public_id), "status": "assigned"}
    assert story.events.last().actor == ed

    # As its owner: a reporter may not assign, and someone outside the desk does not see the story.
    another = newsroom.pitch(desk, user=ed, headline="Library hours")
    make(reporter, {"kind": "hook", "hook": "reporter"}, [assign])
    make(outsider, {"kind": "hook", "hook": "outsider"}, [assign])
    data = {"story": str(another.public_id), "who": "reporter"}
    [refused] = fired(worker, data, hook="reporter")
    [unseen] = fired(worker, data, hook="outsider")
    assert "only the desk's editors assign" in refused.outcomes[0]["error"]
    assert "no story" in unseen.outcomes[0]["error"]
    assert Story.objects.get(pk=another.pk).status == "pitch" and published() == before
    for stage in ("scheduled", "published", "corrected"):
        with pytest.raises(ValidationError):
            make(ed, HOOK, [{"kind": "story", "story": "{{ data.story }}", "to": stage}])


# ── how a run goes ─────────────────────────────────────────────────────────

FAILING = {"kind": "assistant", "assistant": "", "prompt": "{{ data.missing }}"}


@pytest.mark.django_db
def test_a_failing_action_stops_the_run_or_lets_it_go_on(alice, make, worker):
    failing = {**FAILING, "assistant": str(Assistant.objects.create(owner=alice, name="A").public_id)}
    idea = {"kind": "idea", "title": "After the failure"}
    make(alice, {"kind": "hook", "hook": "stop"}, [failing, idea])
    make(alice, {"kind": "hook", "hook": "go-on"}, [failing, idea], on_error=Automation.CONTINUE)
    [stopped] = fired(worker, hook="stop")
    assert stopped.status == AutomationRun.FAILED and [o["status"] for o in stopped.outcomes] == ["failed", "not_run"]
    assert stopped.outcomes[0]["error"] == "a run needs a prompt" and not Idea.objects.exists()
    [went_on] = fired(worker, hook="go-on")
    assert went_on.status == AutomationRun.FAILED and [o["status"] for o in went_on.outcomes] == ["failed", "succeeded"]
    assert Idea.objects.get().title == "After the failure"


@pytest.mark.django_db
def test_runs_over_the_hourly_limit_are_recorded_and_not_run(alice, make, worker):
    make(alice, HOOK, [{"kind": "idea", "title": "Once more"}], max_runs_per_hour=2)
    runs = [r for _ in range(4) for r in fired(worker)]
    assert [r.status for r in runs] == ["succeeded", "succeeded", "limited", "limited"]
    assert runs[2].error == "over its 2 runs per hour: nothing ran" and runs[2].outcomes == []
    assert Idea.objects.count() == 2


@pytest.mark.django_db
def test_a_run_needs_its_owner_and_its_automation_still_enabled(alice, make, worker):
    automation = make(alice, HOOK)
    [queued] = services.fire_hook("act", {})  # queued; the worker has not taken it yet
    services.disable(automation, user=alice)
    assert services.execute(queued.pk).status == AutomationRun.SKIPPED
    assert AutomationRun.objects.get(pk=queued.pk).error == "paused before it ran"
    assert services.execute(queued.pk) is None  # a run is executed once

    alice.is_active = False
    alice.save()
    tested = worker(services.test, automation, {}, user=alice)
    tested.refresh_from_db()
    assert tested.status == AutomationRun.FAILED and "not an active person" in tested.error
