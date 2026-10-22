"""What automations do: every command, so the views, the tool, the tasks and the hooks other apps call stay thin
(TARGET.md § Rules that keep models and views manageable).

**Firing** (`fire`) records a run — the trigger's payload is its input — inside the transaction that caused it, and
queues it once that commits; a paused automation does not fire (a person's test aside), one fires once per key (an
event, a source, a schedule tick, a webhook delivery), and a firing over the automation's runs per hour is recorded as
`limited` and does nothing else. The triggers:

* an event the platform announces — `on_event`, the outbox consumer `automations` (consumers.py), reading the
  stream the relay writes, where the platform already consumes events;
* a schedule — `tick`, which Celery beat calls every minute, reading each cron line with Celery's own `crontab`;
* a webhook — `receive_webhook`, its HMAC signature checked against the automation's secret before anything else;
* a new research source — `on_source`, when a source becomes ready (apps.py connects it);
* a named hook — `fire_hook`, which the platform's apps call (G12's monitor findings) and the `automations.fire_hook`
  tool calls for an agent.

An automation hears only what its owner may see (a suggestion, an agent run, a source), and only its site's when it
has one; an automation's own work — an agent run it started, or one under it — never fires another.

**Running** (`execute`, in the worker) evaluates the condition and then runs the actions in order, each as the
automation's owner — through the same services and permission checks a person's request goes through, in a
savepoint of its own — and writes each action's inputs and outcome to the run, with links to the agent runs and rows
it made. Nothing here publishes: an assistant or a pipeline answers in its run, an agent that lists a publishing tool
is refused, a brief waits for a person to apply it, and a newsroom story moves only to a stage that publishes
nothing. A failing action is recorded, and the run stops there or goes on as the automation says (`on_error`).
Network calls — a webhook notified — happen only here, through the research fetcher's SSRF guard.
"""

import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import timedelta

import httpx
import yaml
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.serializers.json import DjangoJSONEncoder
from django.db import IntegrityError, transaction
from django.utils import timezone
from wagtail.models import Page

from agents.models import AgentDefinition, AgentRun
from agents.runner import RunRefused, start_run
from ai import crypto
from ai import services as ai
from ai.models import Assistant, Brief, OutputSchema, Pipeline
from api.access import may_request_run
from api.pages import service_errors
from ideas import services as ideas
from ideas.models import Board
from newsroom import services as newsroom
from newsroom.models import Story
from ops.errors import ApiError, Conflict, Forbidden, Invalid, NotFound
from research import fetch
from research.models import Source
from suggestions.models import Suggestion

from . import spec
from .models import Automation, AutomationRun

log = logging.getLogger(__name__)

MAX_PAYLOAD = 256 * 1024  # bytes of JSON one payload may take
SOURCE_TEXT = 5000  # characters of a source's text its payload carries
LOGGED = 2000  # characters of each rendered input a run's log keeps
SIGNATURE = "X-Zer0-Signature-256"
SIGNATURES = (SIGNATURE, "X-Hub-Signature-256")  # GitHub signs the same way, under its own name
DELIVERIES = ("X-Zer0-Delivery", "X-GitHub-Delivery")
UNKEPT = {"x-zer0-signature-256", "x-hub-signature", "x-hub-signature-256", "x-csrftoken", "x-request-id"}
MARK = "automation-run:"  # what an agent run an action started carries in `started_by_event`
DOCUMENT = ("name", "description", "trigger", "condition", "actions", "on_error", "max_runs_per_hour")


class ActionFailed(Exception):
    """An action could not do what it was asked; the message says why, on the run."""


# ── firing ─────────────────────────────────────────────────────────────────


def check_size(payload) -> None:
    if len(json.dumps(payload, cls=DjangoJSONEncoder)) > MAX_PAYLOAD:
        raise Invalid(f"a payload is at most {MAX_PAYLOAD} bytes of JSON")


def fire(automation: Automation, trigger: str, payload: dict, *, key: str = "", force: bool = False):
    """Record a firing of `automation` with `payload` and queue it once the caller's transaction commits: the run,
    or None when it is paused (and not `force`d by a person's test) or has fired for `key` already."""
    now = timezone.now()
    try:
        with transaction.atomic():
            row = Automation.objects.select_for_update().filter(pk=automation.pk).first()
            if row is None or not (row.enabled or force) or (key and row.runs.filter(key=key).exists()):
                return None
            used = row.runs.filter(created_at__gte=now - timedelta(hours=1)).exclude(status=AutomationRun.LIMITED)
            limited = used.count() >= row.max_runs_per_hour
            run = AutomationRun.objects.create(
                automation=row,
                trigger=trigger,
                payload=payload,
                key=key[:200],
                status=AutomationRun.LIMITED if limited else AutomationRun.QUEUED,
                error=f"over its {row.max_runs_per_hour} runs per hour: nothing ran" if limited else "",
                finished_at=now if limited else None,
            )
            Automation.objects.filter(pk=row.pk).update(last_run=run)
    except IntegrityError:
        return None  # the same key fired at the same moment elsewhere: once is the point
    if not limited:
        from .tasks import execute_run

        transaction.on_commit(lambda: execute_run.delay(run.pk))
    return run


def listening(kind: str, **config):
    """The enabled automations whose trigger is `kind` (with these settings), owned by an active person."""
    rows = Automation.objects.filter(enabled=True, owner__is_active=True, trigger__kind=kind)
    return rows.filter(**{f"trigger__{name}": value for name, value in config.items()}).select_related("owner")


def elsewhere(automation: Automation, site_id) -> bool:
    """An automation of one site does not hear another site's events, sources or hooks."""
    return automation.site_id is not None and site_id is not None and automation.site_id != site_id


def from_automation(run) -> bool:
    """Whether an agent run (or its id) was started by an automation — itself, or the run above it."""
    run = AgentRun.objects.filter(pk=run).first() if isinstance(run, int) else run
    for _ in range(10):
        if run is None:
            return False
        if run.started_by_event.startswith(MARK):
            return True
        run = run.parent_run
    return True  # ten runs deep is a loop, whatever started it


def _sees(owner, event_type: str, data: dict) -> bool:
    """Whether an automation's owner may see what an event is about: a suggestion, an agent run (a page that went
    live is public)."""
    if event_type == "content.suggestion.created":
        return Suggestion.objects.visible_to(owner).filter(pk=data["suggestion_id"]).exists()
    if event_type == "agent.run.completed":
        return AgentRun.objects.visible_to(owner).filter(pk=data["run_id"]).exists()
    return True


def on_event(envelope: dict) -> list[AutomationRun]:
    """An event this platform announced, as the outbox consumer `automations` reads it (consumers.py)."""
    if envelope.get("source") != settings.EVENTS_SOURCE or envelope.get("type") not in spec.EVENTS:
        return []
    data = envelope.get("data") or {}
    if data.get("run_id") and from_automation(data["run_id"]):
        return []  # an automation's own work never fires automations
    page = Page.objects.filter(pk=data["page_id"]).first() if data.get("page_id") else None
    site = page.get_site() if page is not None else None
    runs = []
    for automation in listening("event", event=envelope["type"]):
        if elsewhere(automation, site.pk if site else None) or not _sees(automation.owner, envelope["type"], data):
            continue
        if run := fire(automation, "event", envelope, key=f"event:{envelope['id']}"):
            runs.append(run)
    return runs


def source_payload(source: Source) -> dict:
    return {
        "id": str(source.public_id),
        "kind": source.kind,
        "title": source.title,
        "url": source.url,
        "author": source.author,
        "published": source.published,
        "summary": source.summary,
        "text": source.text[:SOURCE_TEXT],
        "collection": str(source.collection.public_id) if source.collection_id else None,
        "feed": str(source.feed.public_id) if source.feed_id else None,
        "site": source.site_id,
    }


def _same(wanted, row) -> bool:
    return not wanted or (row is not None and uuid.UUID(str(wanted)) == row.public_id)


def on_source(source: Source) -> list[AutomationRun]:
    """A research source that has just become ready — a feed item, a note, a document, a captured page fetched —
    for every automation waiting for one (in its collection, from its feed) whose owner may see it, once each."""
    runs = []
    for automation in listening("source"):
        wanted = automation.trigger
        if not (_same(wanted.get("collection"), source.collection) and _same(wanted.get("feed"), source.feed)):
            continue
        if elsewhere(automation, source.site_id):
            continue
        if not Source.objects.visible_to(automation.owner).filter(pk=source.pk).exists():
            continue
        payload = {"source": source_payload(source)}
        if run := fire(automation, "source", payload, key=f"source:{source.public_id}"):
            runs.append(run)
    return runs


def fire_hook(name: str, data: dict | None = None, *, site=None, by: str = "") -> list[AutomationRun]:
    """Fire the named hook: every enabled automation waiting for it runs with `{hook, by, site, data}` — `by` says
    who fired it (an app, or `agent:<slug>` for the tool), so a condition can insist on one. How the platform's apps
    hand automations something to act on; G12's monitor findings fire `monitor.finding`."""
    payload = {"hook": name, "by": by, "site": site.pk if site is not None else None, "data": data or {}}
    check_size(payload)
    runs = []
    for automation in listening("hook", hook=name):
        if not elsewhere(automation, payload["site"]) and (run := fire(automation, "hook", payload)):
            runs.append(run)
    return runs


def tick(now=None) -> list[AutomationRun]:
    """Fire every enabled schedule that came due since its last tick (Celery beat calls this every minute). A tick
    is claimed before it fires, so two beats never fire it twice; missed ticks fire once, as beat's own do."""
    now = now or timezone.now()
    runs = []
    for automation in listening("schedule"):
        last = automation.scheduled_at or automation.created_at
        try:
            due = spec.cron(automation.trigger["cron"], now).is_due(last).is_due
        except ValueError:
            continue  # a cron line is checked when it is saved; one that no longer reads never fires
        if not due or not Automation.objects.filter(pk=automation.pk, scheduled_at=automation.scheduled_at).update(
            scheduled_at=now
        ):
            continue
        payload = {"scheduled_at": now.isoformat(), "cron": automation.trigger["cron"]}
        if run := fire(automation, "schedule", payload, key=f"schedule:{now:%Y-%m-%dT%H:%M}"):
            runs.append(run)
    return runs


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def receive_webhook(automation: Automation, body: bytes, headers) -> AutomationRun:
    """A request to an automation's webhook: its signature (`X-Zer0-Signature-256`, or GitHub's
    `X-Hub-Signature-256`: `sha256=` and the HMAC-SHA256 of the body with the automation's secret) checked before
    anything else is read; then the JSON body and the request's `X-…` headers are the payload. A delivery sent again
    (`X-Zer0-Delivery`, `X-GitHub-Delivery`) gets the run it made the first time."""
    sent = next((headers.get(name) for name in SIGNATURES if headers.get(name)), "")
    try:
        expected = signature(automation.get_secret(), body)
    except ValueError:
        log.exception("automation %s: its secret cannot be read; its owner gives it a new one", automation.public_id)
        expected = ""  # nothing a sender sends matches it
    if not expected or not hmac.compare_digest(sent.encode(), expected.encode()):
        raise ApiError("the request is not signed with this automation's secret", code="webhook.signature", status=401)
    if not automation.enabled:
        raise Conflict("the automation is paused", code="automation.paused")
    if len(body) > MAX_PAYLOAD:
        raise Invalid(f"a webhook's body is at most {MAX_PAYLOAD} bytes")
    try:
        parsed = json.loads(body or b"null")
    except ValueError as e:
        raise Invalid("a webhook's body is JSON") from e
    kept = {
        name.lower(): value
        for name, value in headers.items()
        if (name.lower().startswith("x-") or name.lower() in ("content-type", "user-agent"))
        and name.lower() not in UNKEPT
    }
    delivery = next((headers.get(name) for name in DELIVERIES if headers.get(name)), "")
    key = f"webhook:{delivery}"[:200] if delivery else ""
    run = fire(automation, "webhook", {"body": parsed, "headers": kept}, key=key)
    if run is None and key:
        run = automation.runs.filter(key=key).first()
    if run is None:
        raise Conflict("the automation is paused", code="automation.paused")
    return run


# ── running ────────────────────────────────────────────────────────────────


def inputs(action: dict, payload: dict) -> dict:
    """The action with its templates rendered against the payload: what it is asked to do this time."""
    given = {key: value for key, value in action.items() if key != "kind"}
    for name in spec.TEMPLATES[action["kind"]]:
        if isinstance(action.get(name), str):
            given[name] = spec.render(action[name], payload)
    if action["kind"] == "agent" and "input" in action:
        given["input"] = spec.render_all(action["input"], payload)
    return given


def _logged(value):
    if isinstance(value, str):
        return value if len(value) <= LOGGED else value[:LOGGED] + "…"
    if isinstance(value, dict):
        return {key: _logged(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_logged(item) for item in value]
    return value


def _message(error: Exception) -> str:
    if isinstance(error, ApiError):
        return error.message
    if isinstance(error, ValidationError):
        return "; ".join(error.messages)
    if isinstance(error, (ActionFailed, RunRefused)):
        return str(error)
    return f"{type(error).__name__}: {error}"


def _finish(run: AutomationRun, status: str, *, matched=None, outcomes=None, error: str = "") -> AutomationRun:
    run.status, run.matched, run.error, run.finished_at = status, matched, error, timezone.now()
    if outcomes is not None:
        run.outcomes = outcomes
    run.save(update_fields=["status", "matched", "error", "finished_at", "outcomes"])
    return run


def execute(pk: int) -> AutomationRun | None:
    """Run a queued firing (in the worker): the condition, then each action in order as the automation's owner, in
    a savepoint of its own; its inputs and outcome go on the run. None when no run with this id is still queued."""
    if not AutomationRun.objects.filter(pk=pk, status=AutomationRun.QUEUED).update(
        status=AutomationRun.RUNNING, started_at=timezone.now()
    ):
        return None  # gone, or another worker has it
    run = AutomationRun.objects.select_related("automation__owner", "automation__site").get(pk=pk)
    automation, owner = run.automation, run.automation.owner
    if run.trigger != "test" and not automation.enabled:
        return _finish(run, AutomationRun.SKIPPED, error="paused before it ran")
    if owner is None or not owner.is_active or owner.username.startswith("agent:"):
        return _finish(run, AutomationRun.FAILED, error="its owner is not an active person, so nothing runs as them")
    try:
        matched = spec.matches(automation.condition, run.payload)
    except spec.ConditionError as e:
        return _finish(run, AutomationRun.FAILED, error=f"the condition could not be evaluated: {e}")
    if not matched:
        return _finish(run, AutomationRun.SKIPPED, matched=False, error="the condition did not match")
    outcomes, failed = [], False
    for index, action in enumerate(automation.actions):
        if failed and automation.on_error == Automation.STOP:
            outcomes.append({"index": index, "kind": action.get("kind", ""), "status": "not_run"})
            continue
        outcomes.append(_act(run, index, action, owner))
        failed = failed or outcomes[-1]["status"] == "failed"
    status = AutomationRun.FAILED if failed else AutomationRun.SUCCEEDED
    return _finish(run, status, matched=True, outcomes=outcomes, error="an action failed" if failed else "")


def _act(run: AutomationRun, index: int, action: dict, owner) -> dict:
    started = time.monotonic()
    outcome = {"index": index, "kind": action.get("kind", "")}
    try:
        given = inputs(action, run.payload)
        outcome["input"] = _logged(given)
        with transaction.atomic():
            result = ACTS[action["kind"]](given, run, owner)
        outcome |= {"status": "succeeded", "result": result}
    except Exception as e:  # noqa: BLE001 — an action's failure is recorded on its run, and `on_error` decides what follows
        if not isinstance(e, ApiError | ValidationError | ActionFailed | RunRefused):
            log.exception("automation run %s: action %s failed", run.public_id, index)
        outcome |= {"status": "failed", "error": _message(e)}
    outcome["ms"] = int((time.monotonic() - started) * 1000)
    return outcome


# ── the actions, each as the automation's owner ────────────────────────────


def _agent_trigger(run: AutomationRun) -> str:
    """What an agent run an action starts records as its trigger (`AgentRun.TRIGGERS`)."""
    return {"schedule": "schedule", "test": "manual"}.get(run.trigger, "event")


def _mark(started: AgentRun, run: AutomationRun) -> int:
    """The agent run says which automation run started it — the link back, and what keeps an automation's own work
    from firing automations (`from_automation`)."""
    AgentRun.objects.filter(pk=started.pk).update(started_by_event=f"{MARK}{run.public_id}")
    return started.pk


def _row(model, public_id, owner, what: str):
    if not public_id:
        return None
    row = model.objects.visible_to(owner).filter(public_id=public_id).first()
    if row is None:
        raise NotFound(f"no {what} {public_id} that {owner} may use")
    return row


def _page(value: str):
    value = (value or "").strip()
    if not value:
        return None
    if not value.isdigit():
        raise Invalid(f"page: {value[:60]!r} is not a page id")
    page = Page.objects.filter(pk=int(value)).first()
    if page is None:
        raise NotFound(f"no page {value}")
    return page.specific


def _assistant(given, run, owner):
    assistant = _row(Assistant, given["assistant"], owner, "assistant")
    page = _page(given.get("page", ""))
    started = ai.run_assistant(assistant, user=owner, prompt=given["prompt"], page=page, trigger=_agent_trigger(run))
    return {"run": _mark(started, run)}


def _pipeline(given, run, owner):
    pipeline = _row(Pipeline, given["pipeline"], owner, "pipeline")
    page = _page(given.get("page", ""))
    prompt = given.get("prompt", "")
    started = ai.run_pipeline(pipeline, user=owner, prompt=prompt, page=page, trigger=_agent_trigger(run))
    return {"run": _mark(started, run)}


def _agent(given, run, owner):
    definition = AgentDefinition.objects.filter(slug=given["agent"]).first()
    if definition is None:
        raise NotFound(f"no agent {given['agent']!r}")
    if problem := spec.unstartable(definition):
        raise Forbidden(problem)
    page = _page(given.get("page", ""))
    allowed, reason = may_request_run(owner, definition, page)
    if not allowed:
        raise Forbidden(reason)
    trigger, event = _agent_trigger(run), f"{MARK}{run.public_id}"
    try:
        started = start_run(
            definition, trigger=trigger, target=page, input=given.get("input") or {}, user=owner, event_id=event
        )
    except RunRefused as e:
        raise Conflict(str(e)) from e
    return {"run": started.pk}


def _brief(given, run, owner):
    automation = run.automation
    brief = Brief(
        owner=owner,
        site=automation.site,
        visibility=automation.visibility,
        title=given.get("title", "").strip()[:255],
        prompt=given["prompt"],
        assistant=_row(Assistant, given.get("assistant"), owner, "assistant"),
        pipeline=_row(Pipeline, given.get("pipeline"), owner, "pipeline"),
        output_schema=_row(OutputSchema, given.get("output_schema"), owner, "output schema"),
    )
    brief.clean()
    brief.save()
    result = {"brief": str(brief.public_id)}
    if given.get("generate"):
        result["run"] = _mark(ai.generate_brief(brief, user=owner, trigger=_agent_trigger(run)), run)
    return result


def _idea(given, run, owner):
    url = given.get("url", "").strip()
    if url and not url.startswith(("http://", "https://")):
        raise Invalid(f"url: {url[:100]!r} is not a web address")
    notes = given.get("notes", "").strip()
    text = given["title"].strip() + (f"\n{notes}" if notes else "")
    board = _row(Board, given.get("board"), owner, "board")
    idea = ideas.capture(owner, text, board=board, url=url[:2000], tags=given.get("tags", []))
    return {"idea": str(idea.public_id)}


def _email(given, run, owner):
    subject = " ".join(given["subject"].split())[:200] or run.automation.name
    sent = send_mail(subject, given.get("body", ""), None, given["to"], fail_silently=False)
    return {"to": given["to"], "sent": sent}


def post(url: str, body: bytes, headers: dict) -> int:
    """POST `body` to `url` through the research fetcher's SSRF guard (`fetch.pinned`: every address the name resolves
    to public, the connection pinned to the one checked), with no proxy and no redirect, within the fetcher's time;
    the status it answered."""
    try:
        target, host, name = fetch.pinned(url)
        sent = {"User-Agent": settings.RESEARCH_USER_AGENT, **headers, "Host": host}
        with httpx.Client(trust_env=False, follow_redirects=False, timeout=settings.RESEARCH_FETCH_TIMEOUT) as client:
            with client.stream("POST", target, content=body, headers=sent, extensions={"sni_hostname": name}) as reply:
                return reply.status_code
    except fetch.FetchError as e:
        raise ActionFailed(str(e)) from e
    except httpx.HTTPError as e:
        raise ActionFailed(f"the webhook could not be reached: {type(e).__name__}") from e


def _webhook(given, run, owner):
    automation = run.automation
    document = {
        "automation": {"id": str(automation.public_id), "name": automation.name},
        "run": str(run.public_id),
        "trigger": run.trigger,
        "payload": run.payload,
    }
    body = json.dumps(document, cls=DjangoJSONEncoder).encode()
    headers = {
        "Content-Type": "application/json",
        SIGNATURE: signature(automation.get_secret(), body),
        "X-Zer0-Delivery": str(run.public_id),
    }
    status = post(given["url"], body, headers)
    if status >= 400:
        raise ActionFailed(f"the webhook answered HTTP {status}")
    return {"http_status": status}


def _story(given, run, owner):
    if given["to"] not in spec.STAGES:
        raise Forbidden(f"an automation never publishes: it moves a story to {', '.join(spec.STAGES)}")
    key = given["story"].strip()
    try:
        public_id = uuid.UUID(key)
    except ValueError as e:
        raise Invalid(f"story: {key[:60]!r} is not a story id") from e
    story = Story.objects.visible_to(owner).filter(public_id=public_id).first()
    if story is None:
        raise NotFound(f"no story {key} that {owner} works on")
    assignee = None
    if given["to"] == "assigned":
        assignee = get_user_model().objects.filter(username=given.get("assignee", "").strip()).first()
    moved = newsroom.move(story, given["to"], user=owner, assignee=assignee, comment=given.get("comment", ""))
    return {"story": str(moved.public_id), "status": moved.status}


ACTS = {
    "assistant": _assistant,
    "pipeline": _pipeline,
    "agent": _agent,
    "brief": _brief,
    "idea": _idea,
    "email": _email,
    "webhook": _webhook,
    "story": _story,
}


# ── what a person does with an automation ──────────────────────────────────


def changing(automation: Automation, user) -> Automation:
    if not automation.can_edit(user):
        raise Forbidden(f"automation {automation.public_id} runs as its owner: only they change, test or enable it")
    return automation


def validate(automation: Automation) -> None:
    """The model's own checks — fields, trigger, condition, actions, the rows they name — as the error envelope."""
    with service_errors():
        automation.full_clean(exclude=["owner", "last_run"])


@transaction.atomic
def enable(automation: Automation, *, user) -> Automation:
    """Start it: checked again first (the rows it names may have changed), and a schedule counts from now."""
    changing(automation, user)
    if not automation.actions:
        raise Invalid("an automation needs an action before it runs")
    validate(automation)
    automation.enabled, automation.scheduled_at = True, timezone.now()
    automation.save(update_fields=["enabled", "scheduled_at", "updated_at"])
    return automation


@transaction.atomic
def disable(automation: Automation, *, user) -> Automation:
    """Pause it: its owner, a superuser — or staff, who may stop anyone's."""
    if not automation.can_pause(user):
        raise Forbidden(f"automation {automation.public_id} is paused by its owner or staff")
    automation.enabled = False
    automation.save(update_fields=["enabled", "updated_at"])
    return automation


@transaction.atomic
def reencrypt_secrets() -> int:
    """Re-encrypt every automation's secret with the first key — the keys provider credentials use (ai/crypto.py),
    so this runs beside `rotate_ai_credentials` when they change. One no key reads stops it, named, and nothing is
    changed. How many it re-encrypted."""
    rows = list(Automation.objects.exclude(secret_encrypted=""))
    for row in rows:
        row.secret_encrypted = crypto.encrypt(row.get_secret())
    Automation.objects.bulk_update(rows, ["secret_encrypted"])
    return len(rows)


@transaction.atomic
def rotate_secret(automation: Automation, *, user) -> str:
    """A new secret, returned this once: webhooks signed with the old one are refused from now on."""
    changing(automation, user)
    secret = automation.rotate_secret()
    automation.save(update_fields=["secret_encrypted", "updated_at"])
    return secret


def test(automation: Automation, payload: dict, *, user) -> AutomationRun:
    """Fire it now with a sample payload, paused or not: a real run, logged like any other (`trigger` test)."""
    changing(automation, user)
    if not automation.actions:
        raise Invalid("an automation needs an action before it runs")
    check_size(payload)
    return fire(automation, "test", payload, force=True)


def dry_run(automation: Automation, payload: dict) -> dict:
    """What it would do with this payload, doing nothing: the condition's verdict and each action as rendered."""
    verdict = spec.evaluate(automation.condition, payload)
    actions = [
        {"index": i, "kind": a["kind"], "input": _logged(inputs(a, payload))} for i, a in enumerate(automation.actions)
    ]
    return {**verdict, "actions": actions}


def options() -> dict:
    """What a person picks from: the events, the stages a story may be moved to, the agents an automation may
    start, and a sample payload for each trigger."""
    agents = [
        {"slug": d.slug, "name": d.name}
        for d in AgentDefinition.objects.filter(live=True).select_related("live_revision")
        if not spec.unstartable(d)
    ]
    return {"events": list(spec.EVENTS), "stages": list(spec.STAGES), "agents": agents, "samples": spec.samples()}


# ── as YAML ────────────────────────────────────────────────────────────────


def export_yaml(automation: Automation) -> str:
    """The automation as a YAML document — what it does, never who owns it, its secret or whether it runs — so a
    site's automations can live in git like agent definitions do."""
    document = {field: getattr(automation, field) for field in DOCUMENT}
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


@transaction.atomic
def import_yaml(text: str, *, user) -> Automation:
    """A new automation from a YAML document, owned by `user` — private, with a secret of its own, and paused."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise Invalid(f"not a YAML document: {e}") from e
    if not isinstance(document, dict) or not str(document.get("name") or "").strip():
        raise Invalid("an automation document is a mapping with a name")
    if unknown := sorted(set(document) - set(DOCUMENT)):
        raise Invalid(f"an automation document has no {', '.join(map(str, unknown))}: it has {', '.join(DOCUMENT)}")
    automation = Automation(owner=user, **{field: document[field] for field in DOCUMENT if field in document})
    validate(automation)
    automation.save()
    return automation
