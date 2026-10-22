"""What an automation may say — its trigger, its condition and its actions — and the checks a saved one passes.

One JSON Schema per trigger kind and per action kind (`TRIGGERS`, `ACTIONS`). They validate what is stored
(`check`, from `Automation.clean`) by kind, so a person reads which field is wrong rather than "valid under none of
the schemas", and they are how the OpenAPI document describes the two fields (`TRIGGER_SCHEMA`, `ACTIONS_SCHEMA`), so
the generated client types them as the unions they are. Beyond the schemas:

* a schedule is a cron line — minute, hour, day of the month, month, day of the week, in UTC — read by Celery's own
  `crontab`, the parser beat itself uses (`cron`);
* a condition is a JMESPath expression over the run's payload (`matches`): empty always matches, and a value
  JMESPath counts as false (null, false, an empty string, list or object) does not;
* every template compiles as a Django template (`ai.rendering`, no loaders or libraries) and is rendered against
  the payload (`render`: `{{ data.page_id }}`); a webhook's URL and an email's recipients are never templates, so a
  payload never chooses where anything goes;
* a webhook's URL is http(s), carries no credentials and is not a private address written out — the research
  fetcher's guard (`research.fetch`) checks the address it resolves to when it is called;
* the rows an automation names — assistants, pipelines, output schemas, boards, collections, feeds, agents — are
  ones its owner may use (`check_rows`), and an agent it starts lists no tool that publishes.
"""

import json
from pathlib import Path

import jmespath
from celery.schedules import ParseException, crontab
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from jmespath.exceptions import JMESPathError
from jsonschema import Draft202012Validator, FormatChecker

from ai import rendering
from research import fetch

# The events an automation may wait for: the ones this platform announces (schemas/events/). The Rails plane's
# behavioural events are not among them — their reader ids are never stored here (graph/consumers.py).
EVENTS = ("content.page.published", "content.suggestion.created", "agent.run.completed")
# The newsroom stages an automation may move a story to: the ones that publish nothing. Scheduled and published are
# releases, and a correction or an update shows on the site at once (newsroom/services.py `MOVES`).
STAGES = ("assigned", "drafting", "editing", "copy")
MAX_ACTIONS = 20
UUID = {"type": "string", "format": "uuid"}
TEMPLATE = {"type": "string", "maxLength": 20000, "description": "A Django template, rendered against the payload."}
HOOK = {"type": "string", "pattern": r"^[a-z0-9][a-z0-9._-]{0,63}$", "description": "e.g. monitor.finding"}
OBJECT = {"type": "object", "additionalProperties": True}


class ConditionError(Exception):
    """The condition could not be evaluated against this payload."""


def _kind(name: str, description: str, properties: dict | None = None, required=()) -> dict:
    return {
        "type": "object",
        "description": description,
        "properties": {"kind": {"const": name}, **(properties or {})},
        "required": ["kind", *required],
        "additionalProperties": False,
    }


TRIGGERS = {
    "event": _kind("event", "An event the platform announces.", {"event": {"enum": list(EVENTS)}}, ["event"]),
    "schedule": _kind(
        "schedule",
        "A schedule: a cron line (minute hour day-of-month month day-of-week), in UTC.",
        {"cron": {"type": "string", "maxLength": 120}},
        ["cron"],
    ),
    "webhook": _kind("webhook", "A request to the automation's webhook URL, signed with its secret."),
    "source": _kind(
        "source",
        "A new research source its owner may see: a feed item, a note, a document, a captured page once fetched.",
        {"collection": UUID, "feed": UUID},
    ),
    "hook": _kind("hook", "A named hook the platform's apps (or an agent's tool) fire.", {"hook": HOOK}, ["hook"]),
}
ACTIONS = {
    "assistant": _kind(
        "assistant",
        "Run an assistant on a prompt (optionally about a page): its answer is a run's output to review.",
        {"assistant": UUID, "prompt": TEMPLATE, "page": TEMPLATE},
        ["assistant", "prompt"],
    ),
    "pipeline": _kind(
        "pipeline",
        "Run a pipeline on a prompt.",
        {"pipeline": UUID, "prompt": TEMPLATE, "page": TEMPLATE},
        ["pipeline"],
    ),
    "agent": _kind(
        "agent",
        "Start a run of a live agent that lists no publishing tool.",
        {"agent": {"type": "string", "pattern": r"^[-a-zA-Z0-9_]+$"}, "page": TEMPLATE, "input": OBJECT},
        ["agent"],
    ),
    "brief": _kind(
        "brief",
        "Create a brief for a person to apply — written now by its assistant or pipeline when `generate` is set.",
        {
            "title": TEMPLATE,
            "prompt": TEMPLATE,
            "assistant": UUID,
            "pipeline": UUID,
            "output_schema": UUID,
            "generate": {"type": "boolean"},
        },
        ["prompt"],
    ),
    "idea": _kind(
        "idea",
        "Capture an idea, onto a board or into the inbox.",
        {
            "title": TEMPLATE,
            "notes": TEMPLATE,
            "url": TEMPLATE,
            "board": UUID,
            "tags": {"type": "array", "items": {"type": "string", "maxLength": 100}, "maxItems": 20},
        },
        ["title"],
    ),
    "email": _kind(
        "email",
        "Notify people by email, through the platform's mail setup.",
        {
            "to": {"type": "array", "items": {"type": "string", "maxLength": 254}, "minItems": 1, "maxItems": 20},
            "subject": TEMPLATE,
            "body": TEMPLATE,
        },
        ["to", "subject"],
    ),
    "webhook": _kind(
        "webhook",
        "Notify a webhook: the run and its payload as JSON, signed with the automation's secret.",
        {"url": {"type": "string", "maxLength": 2000}},
        ["url"],
    ),
    "story": _kind(
        "story",
        "Move a newsroom story (its id, usually from the payload) to a stage that publishes nothing.",
        {"story": TEMPLATE, "to": {"enum": list(STAGES)}, "assignee": TEMPLATE, "comment": TEMPLATE},
        ["story", "to"],
    ),
}
TRIGGER_SCHEMA = {"oneOf": list(TRIGGERS.values())}
ACTIONS_SCHEMA = {"type": "array", "maxItems": MAX_ACTIONS, "items": {"oneOf": list(ACTIONS.values())}}
# The fields of each action that are templates.
TEMPLATES = {
    kind: [name for name, s in schema["properties"].items() if s is TEMPLATE] for kind, schema in ACTIONS.items()
}


# ── reading a trigger and a condition ──────────────────────────────────────


def cron(line: str, now=None) -> crontab:
    """The schedule of a cron line, as Celery beat reads one; `now` pins the clock it is asked about."""
    fields = (line or "").split()
    if len(fields) != 5:
        raise ValueError("five fields: minute hour day-of-month month day-of-week")
    try:
        schedule = crontab.from_string(" ".join(fields))
    except ParseException as e:
        raise ValueError(str(e)) from e
    if now is not None:
        schedule.nowfun = lambda: now
    return schedule


def truthy(value) -> bool:
    """JMESPath's own truth: null, false and an empty string, list or object are false; everything else — 0
    included — is true."""
    return value is not None and value is not False and value not in ("", [], {})


def matches(condition: str, payload) -> bool:
    """Whether the payload passes the condition (an empty one always does)."""
    if not (condition or "").strip():
        return True
    try:
        return truthy(jmespath.search(condition, payload))
    except JMESPathError as e:
        raise ConditionError(str(e)) from e


def evaluate(condition: str, payload) -> dict:
    """What a condition makes of a sample payload: its verdict, the value it found, or why it could not."""
    try:
        value = jmespath.search(condition, payload) if condition.strip() else True
    except JMESPathError as e:
        return {"matched": None, "value": None, "error": str(e)}
    return {"matched": truthy(value), "value": value, "error": ""}


def render(template: str, payload: dict) -> str:
    """A template rendered against the payload (a string without tags is itself)."""
    return rendering.render(template, payload) if template else ""


def render_all(value, payload: dict):
    """Every string in `value` (an agent's input) rendered against the payload."""
    if isinstance(value, str):
        return render(value, payload)
    if isinstance(value, dict):
        return {key: render_all(item, payload) for key, item in value.items()}
    if isinstance(value, list):
        return [render_all(item, payload) for item in value]
    return value


# ── checking what is stored ────────────────────────────────────────────────


def _by_kind(schemas: dict, value, what: str) -> str:
    """The first way `value` fails its kind's schema (its formats — a uuid — checked too), or ''."""
    if not isinstance(value, dict) or value.get("kind") not in schemas:
        return f"{what} is an object whose kind is one of: {', '.join(schemas)}"
    validator = Draft202012Validator(schemas[value["kind"]], format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(value), key=lambda e: list(e.path))
    return f"{'/'.join(map(str, errors[0].path)) or '(root)'}: {errors[0].message}" if errors else ""


def _trigger(trigger) -> str:
    problem = _by_kind(TRIGGERS, trigger, "a trigger")
    if not problem and trigger["kind"] == "schedule":
        try:
            cron(trigger["cron"])
        except ValueError as e:
            problem = f"cron: not a schedule ({e})"
    return problem


def _condition(condition: str) -> str:
    if not (condition or "").strip():
        return ""
    try:
        jmespath.compile(condition)
    except JMESPathError as e:
        return f"not a JMESPath expression: {e}"
    return ""


def _templates(action: dict) -> list[str]:
    found = [action[name] for name in TEMPLATES[action["kind"]] if isinstance(action.get(name), str)]
    if action["kind"] == "agent":
        found += _strings(action.get("input", {}))
    return found


def _strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for item in value.values() for s in _strings(item)]
    if isinstance(value, list):
        return [s for item in value for s in _strings(item)]
    return []


def _action(action) -> str:
    problem = _by_kind(ACTIONS, action, "an action")
    if problem:
        return problem
    for template in _templates(action):
        try:
            rendering.check(template)
        except ValidationError as e:
            return e.messages[0]
    if action["kind"] == "email":
        for address in action["to"]:
            try:
                validate_email(address)
            except ValidationError:
                return f"to: {address!r} is not an email address"
    if action["kind"] == "webhook":
        try:
            fetch.refuse_private_literal(action["url"])
        except fetch.Blocked as e:
            return f"url: {e}"
    return ""


def _actions(actions) -> str:
    if not isinstance(actions, list):
        return "actions are a list"
    if len(actions) > MAX_ACTIONS:
        return f"at most {MAX_ACTIONS} actions"
    for n, action in enumerate(actions, start=1):
        if problem := _action(action):
            return f"action {n}: {problem}"
    return ""


def check(trigger, condition: str, actions) -> None:
    """Raise ValidationError, by field, unless this is a trigger, a condition and actions the platform runs."""
    problems = {
        field: problem
        for field, problem in (
            ("trigger", _trigger(trigger)),
            ("condition", _condition(condition)),
            ("actions", _actions(actions)),
        )
        if problem
    }
    if problems:
        raise ValidationError(problems)


def unstartable(definition) -> str:
    """Why an automation may not start a run of this agent, or '': it must be live, work from a prompt on a page —
    not run a handler of its own (the assistant runner is reached through the assistant and pipeline actions, the
    books agent through its app) nor decide workflow tasks (a review agent) — and list no tool that publishes."""
    from agents.registry import registry

    if not definition.live:
        return f"{definition.slug} is not live"
    config = definition.live_revision.as_object() if definition.live_revision_id else definition
    if config.handler:
        return f"{definition.slug} runs through its own app, not as an automation's agent run"
    if config.role == "review":
        return f"{definition.slug} decides workflow tasks"
    known = set(registry.names())
    publishing = [name for name in config.tools or [] if name in known and registry.get(name).effect == "publish"]
    if publishing:
        return f"an automation never publishes, and {definition.slug} lists {', '.join(publishing)}"
    return ""


def check_rows(trigger, actions, owner) -> None:
    """Raise ValidationError unless every row the trigger and the actions name is one `owner` may use."""
    from agents.models import AgentDefinition
    from ai.models import Assistant, OutputSchema, Pipeline
    from ideas.models import Board
    from research.models import Collection, FeedSubscription

    rows = {
        "collection": Collection,
        "feed": FeedSubscription,
        "assistant": Assistant,
        "pipeline": Pipeline,
        "output_schema": OutputSchema,
        "board": Board,
    }

    def missing(spec: dict) -> str:
        for name, model in rows.items():
            if spec.get(name) and not model.objects.visible_to(owner).filter(public_id=spec[name]).exists():
                return f"{name}: no {model._meta.verbose_name} {spec[name]} that its owner may use"
        if spec.get("kind") == "agent" and "agent" in spec:
            definition = AgentDefinition.objects.filter(slug=spec["agent"]).first()
            if definition is None:
                return f"agent: no agent {spec['agent']!r}"
            if problem := unstartable(definition):
                return f"agent: {problem}"
        return ""

    if isinstance(trigger, dict) and (problem := missing({k: v for k, v in trigger.items() if k != "kind"})):
        raise ValidationError({"trigger": problem})
    for n, action in enumerate(actions if isinstance(actions, list) else [], start=1):
        if isinstance(action, dict) and (problem := missing(action)):
            raise ValidationError({"actions": f"action {n}: {problem}"})


def samples() -> dict:
    """A sample payload for each trigger kind (an event's is its type's example envelope in schemas/events/), for a
    person to test a condition or a dry run against."""
    examples = Path(settings.EVENTS_SCHEMA_DIR) / "examples"
    return {
        "event": {t: json.loads((examples / f"{t}.json").read_text(encoding="utf-8")) for t in EVENTS},
        "schedule": {"scheduled_at": "2026-10-22T09:00:00+00:00", "cron": "0 9 * * 1-5"},
        "webhook": {
            "body": {"action": "opened", "issue": {"title": "The archive page is slow", "number": 42}},
            "headers": {"content-type": "application/json", "x-github-event": "issues"},
        },
        "source": {
            "source": {
                "id": "6f1c2a8e-0b1d-4f5e-9a3c-2d4b5e6f7a80",
                "kind": "feed",
                "title": "Backups, weekly",
                "url": "https://news.example.com/a-1",
                "author": "",
                "published": "Mon, 19 Oct 2026 08:00:00 GMT",
                "summary": "",
                "text": "Weekly backups are not enough.",
                "collection": None,
                "feed": "0d3e5b7a-9c1f-4e2d-8b6a-7f5c3e1d9b20",
                "site": None,
            }
        },
        "hook": {
            "hook": "monitor.finding",
            "by": "monitor",
            "site": None,
            "data": {"rule": "broken-link", "severity": "high", "url": "https://example.com/archive/"},
        },
    }
