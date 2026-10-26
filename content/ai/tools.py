"""The AI content layer's tools (`ai.*`), in the one registry
(agents/registry.py), so an agent, an MCP client and the APIs reach them under
the same checks.

Both are `propose`: they queue a generation whose result someone reviews — an
assistant's answer, a brief — and return the run to follow; nothing is written
to content. An agent offers them by listing them in its definition. A brief an
agent asks for belongs to the agent user, so it is made visible to the site of
the page it is for (or shared), where a person can review and apply it.
"""

import uuid

from wagtail.models import Page

from agents.registry import ToolError, obj, tool
from ops.errors import ApiError

from . import services
from .models import Assistant, Brief, OutputSchema, Pipeline, Visibility

UUID = {"type": "string", "format": "uuid"}
CODES = {403: "permission_denied", 404: "not_found", 429: "rate_limited"}


def _refused(e: ApiError) -> ToolError:
    return ToolError(CODES.get(e.status, "invalid_args"), e.message)


def _run_json(run) -> dict:
    return {"run_id": run.pk, "status": run.status, "stream": f"/api/v2/agent-runs/{run.pk}/stream/"}


def _visible(model, public_id, ctx):
    if public_id is None:
        return None
    try:
        key = uuid.UUID(str(public_id))
    except ValueError as e:
        raise ToolError("invalid_args", f"{public_id!r} is not a uuid") from e
    row = model.objects.visible_to(ctx.user).filter(public_id=key).first()
    if row is None:
        raise ToolError("not_found", f"no {model.__name__} {public_id}")
    return row


def _page(page_id):
    if page_id is None:
        return None
    page = Page.objects.filter(pk=page_id).first()
    if page is None:
        raise ToolError("not_found", f"no page {page_id}")
    return page.specific


@tool(
    "ai.run_assistant",
    effect="propose",
    description=(
        "Run a user-managed assistant on a prompt, optionally about a page you can edit. Returns the run to follow; "
        "the assistant's answer is a proposal in the run's output, never a change."
    ),
    input_schema=obj(
        {
            "assistant": UUID,
            "prompt": {"type": "string", "minLength": 1, "maxLength": 50000},
            "page_id": {"type": "integer"},
        },
        required=["assistant", "prompt"],
    ),
    page_arg="page_id",
    rate="30/m",
)
def run_assistant(ctx, assistant, prompt, page_id=None):
    try:
        run = services.run_assistant(
            _visible(Assistant, assistant, ctx),
            user=ctx.user,
            prompt=prompt,
            page=_page(page_id),
            parent=ctx.run,
            trigger=ctx.trigger,
        )
    except ApiError as e:
        raise _refused(e) from e
    return _run_json(run)


@tool(
    "ai.generate_brief",
    effect="propose",
    description=(
        "Ask for a brief: an assistant (or a pipeline) writes a structured draft from the prompt, with its title, "
        "slug, description, keywords and tags, for a person to review and apply as a draft page. Returns the brief "
        "and the run to follow."
    ),
    input_schema=obj(
        {
            "prompt": {"type": "string", "minLength": 1, "maxLength": 50000},
            "assistant": UUID,
            "pipeline": UUID,
            "output_schema": UUID,
            "parent_page_id": {"type": "integer"},
            "page_type": {"type": "string"},
        },
        required=["prompt"],
    ),
    page_arg="parent_page_id",
    rate="20/m",
)
def generate_brief(ctx, prompt, assistant=None, pipeline=None, output_schema=None, parent_page_id=None, page_type=None):
    parent = _page(parent_page_id)
    site = parent.get_site() if parent is not None else None
    brief = Brief.objects.create(
        owner=ctx.user,
        site=site,
        visibility=Visibility.SITE if site is not None else Visibility.SHARED,
        prompt=prompt,
        assistant=_visible(Assistant, assistant, ctx),
        pipeline=_visible(Pipeline, pipeline, ctx),
        output_schema=_visible(OutputSchema, output_schema, ctx),
        parent=parent,
        page_type=page_type or "cms.ArticlePage",
    )
    try:
        run = services.generate_brief(brief, user=ctx.user, trigger=ctx.trigger)
    except ApiError as e:
        raise _refused(e) from e
    return {"brief": str(brief.public_id), **_run_json(run)}
