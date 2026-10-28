"""What the AI content layer does: every command, so views, tools and the
admin stay thin (TARGET.md § Rules that keep models and views manageable).

Anything that calls a model or the network is a run of the `assistant` agent
(agents/definitions/assistant.yaml, ai/handlers.py) queued on Celery once the
request's transaction commits: these functions check what they can before
queuing — the rows are the caller's to use, the provider is enabled and inside
its budget — then return the `AgentRun` the caller follows on
`/api/v2/agent-runs/<id>/stream/`. The worker checks the same again when the
run executes, because a run can be started from more than one surface and
things change while it waits. Applying a brief and promoting a message write
rows and propose suggestions, and never publish; so does an assistant or a
pipeline run on a page from the editor (`suggest_on_page`), whose answer the
worker proposes there (`propose_answer`). Every suggestion is proposed through
the registry's `content.propose_edit`, as the `assistant` agent acting for the
person who asked — so its own policy and page permissions, the page's policy,
that person's edit right and the tool's rate hold as for any agent — and only a
person asks for one: an agent proposes with that tool itself.
"""

import json
import re
import uuid
from contextlib import contextmanager
from dataclasses import replace
from functools import cache
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from bs4.element import PreformattedString
from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max, Sum
from django.utils import timezone
from django.utils.text import slugify
from wagtail.blocks import CharBlock, TextBlock

from agents.models import AgentDefinition, AgentRun, AgentStep
from agents.principals import is_agent_user
from agents.registry import ToolContext, ToolError, registry
from agents.runner import RunRefused, start_run
from cms.models import BasePage
from cms.services import save_draft
from importers.jekyll import _unique_slug
from importers.markdown import to_blocks
from ops.errors import ApiError, Conflict, Forbidden, Invalid, NotFound, Unavailable
from suggestions.models import Suggestion

from . import crypto, providers
from .models import Assistant, Brief, Message, ModelEntry, OutputSchema, Pipeline, ProviderConfig, Visibility, usable

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


def start(user, input: dict, *, target=None, parent=None, trigger="rest", options=None) -> AgentRun:
    try:
        return start_run(
            agent(), trigger=trigger, target=target, input=input, user=user, parent=parent, options=options
        )
    except RunRefused as e:
        raise Conflict(str(e)) from e


def spent(slug: str):
    """This month's spend through provider `slug`: each model call once, on the run that made it (a pipeline's
    parent adds its steps' costs to its own total, so summing runs would count them twice)."""
    month = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    calls = AgentStep.objects.filter(kind=AgentStep.LLM, run__llm_backend=slug, created_at__gte=month)
    return calls.aggregate(s=Sum("cost_usd"))["s"] or 0


def check_provider(slug: str) -> str:
    """`slug`, if the registry has it and its row is enabled and inside its monthly budget."""
    if slug not in providers.available():
        raise Invalid(f"no provider {slug!r} in the registry")
    row = ProviderConfig.objects.filter(slug=slug).first()
    if row is not None and not row.enabled:
        raise Conflict(f"the {slug} provider is disabled")
    if row is not None and row.monthly_budget_usd is not None and spent(slug) >= row.monthly_budget_usd:
        raise ApiError(
            f"the {slug} provider has spent its ${row.monthly_budget_usd} budget this month",
            code="budget.exceeded",
            status=429,
        )
    return slug


def slug_of(assistant) -> str:
    """The provider an assistant names — its own, else its model's — or '' for the default."""
    if assistant is None:
        return ""
    if assistant.provider_id:
        return assistant.provider.slug
    return assistant.model.provider.slug if assistant.model_id else ""


def provider_slug(assistant=None) -> str:
    """The provider a generation uses, refused when it is disabled or out of budget."""
    return check_provider(slug_of(assistant) or providers.default_slug())


def _usable(row, user):
    if not usable(row, user):
        raise Forbidden(f"{type(row).__name__.lower()} {row.public_id} is not one {user} may use")
    return row


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


def _check_steps(pipeline, user):
    steps = list(pipeline.steps.select_related("assistant__provider", "assistant__model__provider"))
    if not steps:
        raise Invalid("the pipeline has no steps")
    for step in steps:
        _usable(step.assistant, user)
        provider_slug(step.assistant)


def run_pipeline(pipeline, *, user, prompt="", conversation=None, page=None, trigger="rest") -> AgentRun:
    """A pipeline run; on a conversation a prompt is posted there first (in the worker), for every step to read."""
    _check_steps(pipeline, user)
    _may_read_page(user, page)
    data = {"kind": "pipeline", "pipeline": str(pipeline.public_id), "prompt": prompt}
    if conversation is not None:
        data["conversation"] = str(conversation.public_id)
    return start(user, data, target=page, trigger=trigger)


def assistant_tools() -> list:
    """The read-only tools an assistant may list that its runs will use: the
    registry's `read` tools in the `assistant` definition's live allowlist."""
    definition = agent()
    live = definition.live_revision.as_object() if definition.live_revision_id else definition
    return [t for t in registry.all() if t.effect == "read" and t.name in set(live.tools or [])]


# ── suggestions: proposed by the assistant agent, for a person ─────────────

PROPOSE = "content.propose_edit"
REFUSALS = {"permission_denied": Forbidden, "not_allowed": Forbidden, "policy": Conflict, "not_found": NotFound}


@contextmanager
def _as_api_errors():
    """The registry's refusals as the platform's errors — who may not (403), what a policy forbids (409), the rate
    (429), else what was asked (422); a tool's own failure stays what it is."""
    try:
        yield
    except ToolError as e:
        if e.code == "failed":
            raise
        if e.code == "rate_limited":
            raise ApiError(e.message, code="rate.limited", status=429) from e
        raise REFUSALS.get(e.code, Invalid)(e.message) from e


def _proposer(person, run=None) -> ToolContext:
    """The assistant agent acting for `person`, with its live configuration: what the registry checks a proposal
    against when no run is working — a run that is gives its own context (`acting_for`)."""
    definition = agent()
    config = definition.live_revision.as_object() if definition.live_revision_id else definition
    trigger = run.trigger if run is not None else "rest"
    return ToolContext(user=definition.user, agent=config, run=run, trigger=trigger, on_behalf_of=person)


def acting_for(ctx: ToolContext) -> ToolContext:
    """A working run's context (its agent user and configuration) acting for the person who started the run."""
    return replace(ctx, on_behalf_of=ctx.run.started_by)


def _propose(page, ctx: ToolContext, proposals, rationale: str) -> list:
    """Each `(op, block_id, field, payload)` as a suggestion on `page` — `content.propose_edit` through the
    registry, as `ctx` (the assistant agent acting for a person), each call a step of its run. The suggestions."""
    made = []
    for op, block_id, field, payload in proposals:
        args = {"page_id": page.pk, "op": op, "rationale": rationale[:2000] or "Asked for by a person"}
        if block_id:
            args["block_id"] = block_id
        if op == "meta":
            args |= {"field": field, "value": payload["value"]}
        elif payload is not None:  # a delete names its block and carries none
            args["block"] = payload
        with _as_api_errors():
            made.append(registry.call(PROPOSE, args, ctx)["suggestion_id"])
    found = Suggestion.objects.in_bulk(made)
    return [found[pk] for pk in made]


# ── runs on a page: the answer proposed there ──────────────────────────────


def check_page(user, page, ctx: ToolContext | None = None) -> None:
    """A run may land suggestions on `page`: a content page, asked for by a person who may edit it, where the
    assistant agent may propose — the registry's own checks for `content.propose_edit`, without spending its rate
    (`ctx`: a working run's, else the live configuration). Asked when the run is requested and again before it
    works; the proposals themselves are registry calls."""
    if not isinstance(page, BasePage):
        raise Invalid(f"page {page.pk} is not a content page")
    if user is None or not user.is_authenticated or user.username.startswith("agent:"):
        raise Forbidden(f"suggestions on a page are asked for by a person; an agent proposes with {PROPOSE}")
    _may_read_page(user, page)
    with _as_api_errors():
        registry.check(PROPOSE, {"page_id": page.pk, "op": "insert", "rationale": "-"}, ctx or _proposer(user))


def block_of(page, block_id: str) -> dict | None:
    """A block of the page's latest revision as {id, type, value}, or None."""
    blocks = page.get_latest_revision_as_object().body.get_prep_value()
    return next((b for b in blocks if b.get("id") == block_id), None)


def suggest_on_page(
    source,
    *,
    user,
    page,
    prompt: str = "",
    block_id: str = "",
    selection: str = "",
    field: str = "",
    selection_start: int | None = None,
    trigger="rest",
) -> AgentRun:
    """Run an assistant or a pipeline on a page — the whole page, one block of
    it, or text selected in that block (`place`: where it is, which the run
    keeps) — and have the run propose its answer there as suggestions
    (ai/handlers.py `_page`, then `propose_answer`)."""
    check_page(user, page)
    if selection and not block_id:
        raise Invalid("a selection is text in one block: name the block")
    where = {}
    if block_id:
        aimed = block_of(page, block_id)
        if aimed is None:
            raise Invalid(f"block {block_id!r} is not on the page's latest revision: save the page first")
        if selection:
            field, at = place(aimed, selection, field, selection_start)
            where = {"field": field, "selection_start": at}
    if isinstance(source, Pipeline):
        _check_steps(source, user)
    elif not prompt.strip():
        raise Invalid("say what the assistant should do with the page")
    else:
        provider_slug(source)
    key = "pipeline" if isinstance(source, Pipeline) else "assistant"
    data = {"kind": "page", key: str(source.public_id), "prompt": prompt, "block_id": block_id, "selection": selection}
    return start(user, data | where, target=page, trigger=trigger)


# ── a selection in a block: where it is, and the answer in its place ───────


def text_fields(block_type: str) -> list[str]:
    """The fields of a structured block a selection can be in: its plain-text ones — a heading's text, a code
    block's code and language, a quote's text and who said it — never a choice, an image or a page."""
    child = BasePage._meta.get_field("body").stream_block.child_blocks.get(block_type)
    return [name for name, b in getattr(child, "child_blocks", {}).items() if isinstance(b, CharBlock | TextBlock)]


def _text_nodes(soup) -> list:
    return [s for s in soup.find_all(string=True) if not isinstance(s, PreformattedString)]


def _texts(aimed: dict) -> dict:
    """What a person can select in a block, by field (`""` for a markdown or a paragraph block's own text), as they
    see it: a paragraph's is the text of its HTML — no tag, no attribute, entities read."""
    value = aimed["value"]
    if aimed["type"] == "paragraph":
        return {"": "".join(_text_nodes(BeautifulSoup(str(value), "html.parser")))}
    if isinstance(value, str):
        return {"": value}
    if isinstance(value, dict):
        return {f: value[f] for f in text_fields(aimed["type"]) if isinstance(value.get(f), str)}
    return {}


def place(aimed: dict, selection: str, field: str = "", start: int | None = None) -> tuple[str, int]:
    """Where `selection` is in the block `aimed`: its field and the character it starts at, counted in the text a
    person sees (`_texts`). Given a start, it must be there; without one it must appear in the block exactly once.
    Anything else is refused with the reason — swapping text the person did not choose is worse than asking again."""
    texts = _texts(aimed)
    if field and field not in texts:
        raise Invalid(f"{field!r} is not text of a {aimed['type']} block: select in its text, or work on all of it")
    fields = [field] if field else list(texts)
    if start is not None:
        if len(fields) != 1:
            raise Invalid(f"say which field of the {aimed['type']} block the selection is in")
        if texts[fields[0]][start : start + len(selection)] != selection:
            raise Invalid("the selection is not at that place in the block as saved: save the page, or select again")
        return fields[0], start
    found = [(f, m.start()) for f in fields for m in re.finditer(f"(?={re.escape(selection)})", texts[f])]
    if not found:
        raise Invalid("the selection is not in that block as saved: save the page, or work on the whole block")
    if len(found) > 1:
        raise Invalid(
            f"the selection appears {len(found)} times in that block: select the one you mean in its source, "
            "or work on the whole block"
        )
    return found[0]


def swap(aimed: dict, field: str, start: int, end: int, answer: str):
    """The block's value with the text a person sees from `start` to `end` in `field` replaced by the answer, and
    nothing else: in a paragraph only text changes — never a tag or an attribute — and the answer takes the place
    (and the formatting) of the text where the selection starts."""
    value = aimed["value"]
    if aimed["type"] != "paragraph":
        text = value[field] if field else value
        swapped = text[:start] + answer + text[end:]
        return {**value, field: swapped} if field else swapped
    soup, at, placed = BeautifulSoup(str(value), "html.parser"), 0, False
    for node in _text_nodes(soup):
        text, begins = str(node), at
        at += len(text)
        if at > start and begins < end:
            head, tail = text[: max(start - begins, 0)], text[min(end - begins, len(text)) :]
            node.replace_with(head + ("" if placed else answer) + tail)
            placed = True
    return str(soup)


def in_place_of(aimed: dict, answer: str, selection: str = "", field: str = "", start: int | None = None):
    """The block that takes `aimed`'s place: the same block with the selection swapped for the answer — None
    when the selection is no longer where it was — or the answer as the one block it reads as, else as Markdown
    (a one-line answer for a heading stays that heading)."""
    answer = answer.strip()
    if selection:
        try:
            field, start = place(aimed, selection, field, start)
        except Invalid:
            return None
        return {"type": aimed["type"], "value": swap(aimed, field, start, start + len(selection), answer)}
    if aimed["type"] == "heading" and "\n" not in answer:
        return {"type": "heading", "value": {**aimed["value"], "text": answer.lstrip("#").strip()}}
    blocks = to_blocks(answer)
    return blocks[0] if len(blocks) == 1 else {"type": "markdown", "value": answer}


@transaction.atomic
def propose_answer(
    ctx: ToolContext,
    page,
    answer: str,
    *,
    block_id: str = "",
    selection: str = "",
    field: str = "",
    start: int | None = None,
    rationale: str = "",
):
    """A run's answer on the page it was asked about, proposed by the assistant
    agent acting for the person who asked (`ctx`, `acting_for`) — all of the
    suggestions or none: in place of the aimed block, or as new blocks at the
    end of the page. A selection no longer where it was gets its answer as a
    new block after its block, so nothing the person did not choose is replaced."""
    check_page(ctx.on_behalf_of, page, ctx)
    if not answer.strip():
        raise Invalid("the answer is empty: nothing to suggest")
    aimed = block_of(page, block_id) if block_id else None
    if block_id and aimed is None:
        raise Invalid(f"block {block_id!r} is no longer on the page")
    if aimed is None:
        proposals = [("insert", "", "", block) for block in to_blocks(answer)]
    elif (block := in_place_of(aimed, answer, selection, field, start)) is None:
        proposals = [("insert", block_id, "", {"type": "markdown", "value": answer.strip()})]
    else:
        proposals = [("replace", block_id, "", block)]
    return _propose(page, ctx, proposals, rationale)


def sync_models(row: ProviderConfig, *, user) -> AgentRun:
    return start(user, {"kind": "sync_models", "provider": row.slug})


def check_health(row: ProviderConfig, *, user) -> AgentRun:
    return start(user, {"kind": "health", "provider": row.slug})


# ── providers ──────────────────────────────────────────────────────────────


def ensure_providers(state=apps) -> None:
    """A row for every adapter in the registry (after every migrate, with the migrated models in `state`)."""
    rows = state.get_model("ai", "ProviderConfig").objects
    for slug in providers.available():
        try:
            name = providers.provider_class(slug).display_name
        except ImportError:
            name = slug  # a misconfigured AI_PROVIDERS entry still gets a row to fix it on
        rows.get_or_create(slug=slug, defaults={"display_name": name})


@transaction.atomic
def set_default(row: ProviderConfig) -> ProviderConfig:
    if not row.enabled:
        raise Conflict("enable the provider before making it the default")
    ProviderConfig.objects.filter(is_default=True).exclude(pk=row.pk).update(is_default=False)
    row.is_default = True
    row.save(update_fields=["is_default", "updated_at"])
    return row


@transaction.atomic
def rotate_credentials() -> int:
    """Re-encrypt every stored credential with the first key — the providers' here, every other app's through
    `crypto.credentials_rotated` — and return how many. One no key can read stops it (`NotConfigured`, or a
    receiver's ValueError, naming whose it is) and nothing is changed."""
    rows = list(ProviderConfig.objects.exclude(credential_encrypted=""))
    for row in rows:
        row.set_credential(row.get_credential())
        row.save(update_fields=["credential_encrypted", "updated_at"])
    return len(rows) + sum(count for _, count in crypto.credentials_rotated.send(sender=ProviderConfig))


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


def import_bundled(state=apps, path: Path = DATA / "bundled.yaml") -> dict:
    """Create the bundled schemas and assistants that do not exist yet; one a
    person already edited is left as it is. `state` is the model registry —
    after a migrate, the migrated one. `path` is a bundle: this app's, or one
    an app built on this layer ships (ideas, research), whose schemas are
    written inline (`schema:`) and whose instructions sit beside it."""
    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    schema_rows, assistant_rows = (state.get_model("ai", name).objects for name in ("OutputSchema", "Assistant"))
    schemas, assistants = {}, []
    for item in spec.get("schemas", []):
        schemas[item["key"]], _ = schema_rows.get_or_create(
            public_id=stable_id("bundled-schema", item["key"]),
            defaults={
                "name": item["name"],
                "description": item["description"],
                "schema": item["schema"] if "schema" in item else bundled_schema(item["file"]),
                "render_template": item["template"],
                "bundled": True,
                "visibility": Visibility.SHARED,
            },
        )
    for item in spec.get("assistants", []):
        row, _ = assistant_rows.get_or_create(
            public_id=stable_id("bundled-assistant", item["key"]),
            defaults={
                "name": item["name"],
                "description": item["description"],
                "instructions": (path.parent / item["instructions"]).read_text(encoding="utf-8"),
                "output_schema": schemas.get(item.get("output_schema")),
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
    for row in (brief.assistant, brief.pipeline, brief.output_schema):
        _usable(row, user)
    if brief.pipeline_id:
        _check_steps(brief.pipeline, user)
    provider_slug(brief.assistant)
    run = start(user, {"kind": "brief", "brief": str(brief.public_id)}, trigger=trigger)
    brief.status, brief.run, brief.error = Brief.GENERATING, run, ""
    brief.save(update_fields=["status", "run", "error", "updated_at"])
    return run


@transaction.atomic
def apply_brief(brief: Brief, *, user, parent=None, page_type: str = ""):
    """A draft page from a ready brief: the person who applies it creates the
    page (its title and slug), and everything the model wrote — the body, the
    description, the keywords — arrives as suggestions the assistant agent
    proposes for them, on the brief's run, for the editor to accept. Nothing is
    published, and only a person applies a brief. A brief an agent asked for
    (`ai.generate_brief`) is for the people it is shown to: anyone who sees it
    may apply it where they may add a page. A page type may make itself from a
    brief (`from_brief`): a book outline becomes a draft book with its chapter
    stubs, whichever endpoint applies it."""
    if user.username.startswith("agent:"):
        raise Forbidden(f"a person applies a brief; an agent proposes with {PROPOSE}")
    brief = Brief.objects.select_for_update().get(pk=brief.pk)
    if not (brief.can_edit(user) or is_agent_user(brief.owner)):
        raise Forbidden(f"brief {brief.public_id} is not {user}'s to apply")
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
    made = model.from_brief(brief, user=user) if hasattr(model, "from_brief") else None
    if made is not None:  # a page type made its own way from a brief (a book outline: books/services.py)
        return made, []

    meta = brief.metadata or {}
    title = (meta.get("title") or brief.title or "Untitled draft").strip()[:255]
    page = model(title=title, slug=_unique_slug(parent, slugify(meta.get("slug") or title)[:200] or "draft"))
    page.live = False
    parent.add_child(instance=page)
    save_draft(page, user=user)

    proposals = [("insert", "", "", block) for block in to_blocks(brief.markdown)]
    if meta.get("description"):
        proposals.append(("meta", "", "search_description", {"value": str(meta["description"])[:1000]}))
    keywords = [str(k).strip()[:64] for k in [*meta.get("keywords", []), *meta.get("tags", [])] if str(k).strip()]
    if keywords:
        proposals.append(("meta", "", "ai_keywords", {"value": list(dict.fromkeys(keywords))[:20]}))
    rationale = f"From brief {brief.public_id}" + (f": {brief.prompt[:200]}" if brief.prompt else "")
    suggestions = _propose(page, _proposer(user, brief.run), proposals, rationale)
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
    provider_slug(_usable(assistant, user))
    answer = append(conversation, role=Message.ASSISTANT, assistant=assistant, status=Message.QUEUED)
    run = start(user, {"kind": "message", "message": str(answer.public_id)}, trigger=trigger)
    answer.run = run
    answer.save(update_fields=["run"])
    return answer, run


@transaction.atomic
def post_message(conversation, *, user, text: str, assistant=None, answer=True, trigger="rest"):
    """A person's message; with an assistant (or the conversation's), its reply is queued — or, when that
    assistant is not theirs to use, nothing is."""
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
    makes the draft page. The brief keeps the message's (or the conversation's)
    assistant only if the person may still use it."""
    if not message.text.strip():
        raise Invalid("the message has no text")
    conversation = message.conversation
    fields = {
        "owner": user,
        "site": conversation.site,
        "conversation": conversation,
        "source_message": message,
        "assistant": next((a for a in (message.assistant, conversation.assistant) if a and usable(a, user)), None),
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
