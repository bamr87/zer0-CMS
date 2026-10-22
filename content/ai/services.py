"""What the AI content layer does: every command, so views, tools and the
admin stay thin (TARGET.md § Rules that keep models and views manageable).

Anything that calls a model or the network is a run of the `assistant` agent
(agents/definitions/assistant.yaml, ai/handlers.py) queued on Celery once the
request's transaction commits: these functions check what they can before
queuing — the rows are the caller's to use, the provider is enabled and inside
its budget — then return the `AgentRun` the caller follows on
`/api/v2/agent-runs/<id>/stream/`. Applying a brief and promoting a message
write rows and propose suggestions, and never publish.
"""

import json
import uuid
from functools import cache
from pathlib import Path

import yaml
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone
from django.utils.text import slugify

from agents.models import AgentDefinition, AgentRun
from agents.runner import RunRefused, start_run
from cms.models import BasePage
from cms.services import save_draft
from importers.jekyll import _unique_slug
from importers.markdown import to_blocks
from ops.errors import ApiError, Conflict, Forbidden, Invalid, Unavailable
from suggestions.services import SuggestionError, propose

from . import crypto, providers
from .models import Assistant, Brief, Message, ModelEntry, OutputSchema, ProviderConfig, Visibility

AGENT = "assistant"
DATA = Path(__file__).resolve().parent / "data"
IDS = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/bamr87/zer0-CMS/content/ai")


def stable_id(kind: str, key) -> uuid.UUID:
    """The public id of a seeded or imported row, the same on every run."""
    return uuid.uuid5(IDS, f"{kind}:{key}")


# ── runs ───────────────────────────────────────────────────────────────────


def agent() -> AgentDefinition:
    definition = AgentDefinition.objects.filter(slug=AGENT).first()
    if definition is None:
        raise Unavailable(f"the {AGENT} agent is not synced: run manage.py sync_agents --publish")
    return definition


def start(user, input: dict, *, target=None, parent=None, trigger="rest") -> AgentRun:
    try:
        return start_run(agent(), trigger=trigger, target=target, input=input, user=user, parent=parent)
    except RunRefused as e:
        raise Conflict(str(e)) from e


def provider_slug(assistant=None) -> str:
    """The provider a generation uses — the assistant's, its model's, then the
    default — refused when it is disabled or out of budget."""
    slug = None
    if assistant is not None:
        slug = (
            assistant.provider.slug
            if assistant.provider_id
            else (assistant.model.provider.slug if assistant.model_id else None)
        )
    slug = slug or providers.default_slug()
    if slug not in providers.available():
        raise Invalid(f"no provider {slug!r} in the registry")
    row = ProviderConfig.objects.filter(slug=slug).first()
    if row is not None and not row.enabled:
        raise Conflict(f"the {slug} provider is disabled")
    if row is not None and row.monthly_budget_usd is not None:
        month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        spent = AgentRun.objects.filter(llm_backend=slug, created_at__gte=month).aggregate(s=Sum("cost_usd"))["s"]
        if (spent or 0) >= row.monthly_budget_usd:
            raise ApiError(
                f"the {slug} provider has spent its ${row.monthly_budget_usd} budget this month",
                code="budget.exceeded",
                status=429,
            )
    return slug


def _may_read_page(user, page):
    if page is not None and not page.permissions_for_user(user).can_edit():
        raise Forbidden(f"{user} may not edit page {page.pk}")


def run_assistant(assistant, *, user, prompt: str, page=None, parent=None, trigger="rest") -> AgentRun:
    if not prompt.strip():
        raise Invalid("a run needs a prompt")
    _may_read_page(user, page)
    provider_slug(assistant)
    data = {"kind": "assistant", "assistant": str(assistant.public_id), "prompt": prompt}
    return start(user, data | ({"page_id": page.pk} if page else {}), target=page, parent=parent, trigger=trigger)


def run_pipeline(pipeline, *, user, prompt="", conversation=None, page=None, trigger="rest") -> AgentRun:
    steps = list(pipeline.steps.select_related("assistant__provider", "assistant__model__provider"))
    if not steps:
        raise Invalid("the pipeline has no steps")
    _may_read_page(user, page)
    for step in steps:
        provider_slug(step.assistant)
    data = {"kind": "pipeline", "pipeline": str(pipeline.public_id), "prompt": prompt}
    if conversation is not None:
        data["conversation"] = str(conversation.public_id)
    return start(user, data, target=page, trigger=trigger)


def sync_models(row: ProviderConfig, *, user) -> AgentRun:
    return start(user, {"kind": "sync_models", "provider": row.slug})


def check_health(row: ProviderConfig, *, user) -> AgentRun:
    return start(user, {"kind": "health", "provider": row.slug})


# ── providers ──────────────────────────────────────────────────────────────


def ensure_providers() -> None:
    """A row for every adapter in the registry (after every migrate)."""
    for slug in providers.available():
        try:
            name = providers.provider_class(slug).display_name
        except ImportError:
            name = slug  # a misconfigured AI_PROVIDERS entry still gets a row to fix it on
        ProviderConfig.objects.get_or_create(slug=slug, defaults={"display_name": name})


@transaction.atomic
def set_default(row: ProviderConfig) -> ProviderConfig:
    if not row.enabled:
        raise Conflict("enable the provider before making it the default")
    ProviderConfig.objects.filter(is_default=True).exclude(pk=row.pk).update(is_default=False)
    row.is_default = True
    row.save(update_fields=["is_default", "updated_at"])
    return row


def rotate_credentials() -> int:
    """Re-encrypt every stored credential with the first key; returns how many."""
    rows = list(ProviderConfig.objects.exclude(credential_encrypted=""))
    for row in rows:
        row.credential_encrypted = crypto.rotate(row.credential_encrypted)
        row.save(update_fields=["credential_encrypted", "updated_at"])
    return len(rows)


def record_models(row: ProviderConfig, found) -> dict:
    """Upsert the catalog from what a provider says it runs."""
    now, created = timezone.now(), []
    for info in found:
        defaults = {"display_name": info.display_name or info.id, "active": True, "synced_at": now}
        if info.capabilities:
            defaults["capabilities"] = info.capabilities
        for field in ("input_usd_per_mtok", "output_usd_per_mtok"):
            if getattr(info, field) is not None:
                defaults[field] = getattr(info, field)
        _, new = ModelEntry.objects.update_or_create(provider=row, model_id=info.id, defaults=defaults)
        if new:
            created.append(info.id)
    return {"provider": row.slug, "models": [m.id for m in found], "created": created}


# ── output schemas and the bundled set ─────────────────────────────────────


def _inline_refs(node):
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("./"):
            return {k: v for k, v in bundled_schema(ref[2:]).items() if k != "$schema"}
        return {k: _inline_refs(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_inline_refs(v) for v in node]
    return node


@cache
def _bundled_schema(name: str) -> str:
    return json.dumps(_inline_refs(json.loads((DATA / name).read_text(encoding="utf-8"))))


def bundled_schema(name: str) -> dict:
    """A schema file from ai/data/, its local `$ref`s inlined."""
    return json.loads(_bundled_schema(name))


def import_bundled() -> dict:
    """Create the bundled schemas and assistant that do not exist yet; one a
    person already edited is left as it is."""
    spec = yaml.safe_load((DATA / "bundled.yaml").read_text(encoding="utf-8"))
    schemas, assistants = {}, []
    for item in spec["schemas"]:
        schemas[item["key"]], _ = OutputSchema.objects.get_or_create(
            public_id=stable_id("bundled-schema", item["key"]),
            defaults={
                "name": item["name"],
                "description": item["description"],
                "schema": bundled_schema(item["file"]),
                "render_template": item["template"],
                "bundled": True,
                "visibility": Visibility.SHARED,
            },
        )
    for item in spec["assistants"]:
        row, _ = Assistant.objects.get_or_create(
            public_id=stable_id("bundled-assistant", item["key"]),
            defaults={
                "name": item["name"],
                "description": item["description"],
                "instructions": (DATA / item["instructions"]).read_text(encoding="utf-8"),
                "output_schema": schemas[item["output_schema"]],
                "visibility": Visibility.SHARED,
            },
        )
        assistants.append(row)
    return {"schemas": list(schemas.values()), "assistants": assistants}


# ── assistants as documents ────────────────────────────────────────────────

PORTABLE = ("name", "description", "instructions", "prompt_template", "params", "tools")
SCHEMA_FIELDS = ("name", "description", "schema", "render_template")


def export_assistant(assistant: Assistant) -> dict:
    """An assistant as a self-contained document: its provider by slug, its
    model by id, its output schema inline — what `import_assistant` reads."""
    schema = assistant.output_schema
    return {
        **{field: getattr(assistant, field) for field in PORTABLE},
        "provider": assistant.provider.slug if assistant.provider_id else None,
        "model": assistant.model.model_id if assistant.model_id else None,
        "output_schema": {field: getattr(schema, field) for field in SCHEMA_FIELDS} if schema else None,
    }


@transaction.atomic
def import_assistant(document: dict, *, user) -> Assistant:
    """A new private assistant (and its output schema) from an exported document."""
    if not isinstance(document, dict) or not str(document.get("name") or "").strip():
        raise Invalid("an assistant document is an object with a name")
    provider = None
    if document.get("provider"):
        provider = ProviderConfig.objects.filter(slug=document["provider"]).first()
        if provider is None:
            raise Invalid(f"no provider {document['provider']!r}")
    model = None
    if document.get("model"):
        if provider is None:
            raise Invalid("a model needs its provider")
        model, _ = ModelEntry.objects.get_or_create(provider=provider, model_id=document["model"])
    schema = document.get("output_schema")
    try:
        if schema is not None:
            schema = OutputSchema.objects.create(owner=user, **{f: schema.get(f, "") for f in SCHEMA_FIELDS})
        return Assistant.objects.create(
            owner=user,
            provider=provider,
            model=model,
            output_schema=schema,
            **{field: document[field] for field in PORTABLE if field in document},
        )
    except ValidationError as e:
        raise Invalid("; ".join(e.messages)) from e


# ── briefs ─────────────────────────────────────────────────────────────────


def generate_brief(brief: Brief, *, user, trigger="rest") -> AgentRun:
    if brief.status in (Brief.GENERATING, Brief.APPLIED):
        raise Conflict(f"the brief is {brief.status}")
    if not (brief.source_text.strip() or brief.prompt.strip()):
        raise Invalid("a brief needs a prompt or a source text")
    if not (brief.source_text.strip() or brief.assistant_id or brief.pipeline_id):
        raise Invalid("a brief needs an assistant or a pipeline to write it")
    if brief.pipeline_id:
        for step in brief.pipeline.steps.select_related("assistant__provider", "assistant__model__provider"):
            provider_slug(step.assistant)
    provider_slug(brief.assistant)
    run = start(user, {"kind": "brief", "brief": str(brief.public_id)}, trigger=trigger)
    brief.status, brief.run, brief.error = Brief.GENERATING, run, ""
    brief.save(update_fields=["status", "run", "error", "updated_at"])
    return run


@transaction.atomic
def apply_brief(brief: Brief, *, user, parent=None, page_type: str = ""):
    """A draft page from a ready brief: the person who applies it creates the
    page (its title and slug), and everything the model wrote — the body, the
    description, the keywords — arrives as suggestions from the assistant agent,
    on the brief's run, for the editor to accept. Nothing is published."""
    brief = Brief.objects.select_for_update().get(pk=brief.pk)
    if brief.status != Brief.READY:
        raise Conflict(f"a brief is applied once it is ready; this one is {brief.status}")
    parent = parent or brief.parent or (brief.site.root_page if brief.site_id else None)
    if parent is None:
        raise Invalid("choose where the draft goes: a parent page")
    parent = parent.specific
    page_type = page_type or brief.page_type
    try:
        model = apps.get_model(page_type)
    except (LookupError, ValueError) as e:
        raise Invalid(f"no page type {page_type!r}") from e
    if not issubclass(model, BasePage) or not model.can_create_at(parent):
        raise Invalid(f"a {page_type} cannot go under {parent.title!r}")
    if not parent.permissions_for_user(user).can_add_subpage():
        raise Forbidden(f"{user} may not add a page under {parent.title!r}")

    meta = brief.metadata or {}
    title = (meta.get("title") or brief.title or "Untitled draft").strip()[:255]
    page = model(title=title, slug=_unique_slug(parent, slugify(meta.get("slug") or title)[:200] or "draft"))
    page.live = False
    parent.add_child(instance=page)
    save_draft(page, user=user)

    definition = agent()
    proposals = [("insert", "", {"type": b["type"], "value": b["value"]}) for b in to_blocks(brief.markdown)]
    if meta.get("description"):
        proposals.append(("meta", "search_description", {"value": str(meta["description"])[:1000]}))
    keywords = [str(k).strip()[:64] for k in [*meta.get("keywords", []), *meta.get("tags", [])] if str(k).strip()]
    if keywords:
        proposals.append(("meta", "ai_keywords", {"value": list(dict.fromkeys(keywords))[:20]}))
    rationale = f"From brief {brief.public_id}" + (f": {brief.prompt[:200]}" if brief.prompt else "")
    try:
        suggestions = [
            propose(
                target=page,
                op=op,
                user=definition.user,
                run=brief.run,
                agent=definition,
                field=field,
                payload=payload,
                rationale=rationale,
            )
            for op, field, payload in proposals
        ]
    except SuggestionError as e:
        raise Invalid(f"the brief's text was refused: {e}") from e
    brief.page, brief.status, brief.applied_at = page, Brief.APPLIED, timezone.now()
    brief.save(update_fields=["page", "status", "applied_at", "updated_at"])
    return page, suggestions


# ── conversations ──────────────────────────────────────────────────────────


def append(conversation, **fields) -> Message:
    """A message at the end of the conversation (its `seq` numbered under a lock)."""
    with transaction.atomic():
        type(conversation).objects.select_for_update().filter(pk=conversation.pk).first()
        seq = (conversation.messages.aggregate(m=Max("seq"))["m"] or 0) + 1
        message = Message.objects.create(conversation=conversation, seq=seq, **fields)
        type(conversation).objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
    return message


def converse_about(conversation, brief: Brief, *, link=True) -> Message:
    """Start a conversation from a brief: its text (or its prompt) is the first
    turn, and — when the brief is the person's to change — it points back."""
    text = brief.markdown or brief.source_text or brief.prompt
    if not text.strip():
        raise Invalid("the brief has no text to talk about")
    if link and brief.conversation_id is None:
        Brief.objects.filter(pk=brief.pk).update(conversation=conversation)
    return append(conversation, role=Message.USER, text=text)


def reply(conversation, assistant, *, user, trigger="rest"):
    """Queue `assistant`'s reply: a placeholder message and the run that fills it."""
    if assistant is None:
        raise Invalid("choose an assistant to reply")
    provider_slug(assistant)
    answer = append(conversation, role=Message.ASSISTANT, assistant=assistant, status=Message.QUEUED)
    run = start(user, {"kind": "message", "message": str(answer.public_id)}, trigger=trigger)
    answer.run = run
    answer.save(update_fields=["run"])
    return answer, run


def post_message(conversation, *, user, text: str, assistant=None, answer=True, trigger="rest"):
    """A person's message; with an assistant (or the conversation's), its reply is queued."""
    if not text.strip():
        raise Invalid("a message needs text")
    message = append(conversation, role=Message.USER, text=text)
    assistant = assistant or conversation.assistant
    if not answer or assistant is None:
        return message, None, None
    reply_message, run = reply(conversation, assistant, user=user, trigger=trigger)
    return message, reply_message, run


def rerun(message: Message, *, user, assistant=None, trigger="rest"):
    """Ask again: a new reply from the message's assistant (or another), at the end."""
    conversation = message.conversation
    return reply(conversation, assistant or message.assistant or conversation.assistant, user=user, trigger=trigger)


def promote(message: Message, *, user, to: str, parent=None, page_type: str = "", trigger="rest"):
    """A message → a brief to write from (its text is the prompt), or → a draft:
    its text kept as written, the metadata step queued; applying the ready brief
    makes the draft page."""
    if not message.text.strip():
        raise Invalid("the message has no text")
    conversation = message.conversation
    fields = {
        "owner": user,
        "site": conversation.site,
        "conversation": conversation,
        "source_message": message,
        "assistant": message.assistant or conversation.assistant,
        "parent": parent,
        "page_type": page_type or "cms.ArticlePage",
        "title": conversation.title[:255],
    }
    if to == "brief":
        return Brief.objects.create(prompt=message.text, **fields), None
    if to != "draft":
        raise Invalid("promote a message to a brief or a draft")
    brief = Brief.objects.create(source_text=message.text, **fields)
    return brief, generate_brief(brief, user=user, trigger=trigger)
