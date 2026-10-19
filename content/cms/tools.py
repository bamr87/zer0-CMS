"""The content tools (`content.*`, `media.*`), registered into the one
registry (agents/registry.py), so the runner, the MCP server and the APIs all
offer exactly these, under exactly the registry's checks.

Effects, lowest first: `content.get_schema`, `content.get_page`,
`content.search` and `media.describe` read; `content.propose_edit` and
`media.propose_alt` propose (they create Suggestions — the default path for
every agent); `content.draft_revision` writes a draft revision directly and
needs policy `draft`; `content.publish` needs `auto`.
"""

from wagtail.images import get_image_model
from wagtail.models import Page

from agents.registry import ToolError, obj, tool
from agents.schema import export
from suggestions.models import BlockProvenance, Suggestion
from suggestions.services import SuggestionError, apply_op, guard, propose

BLOCK = {
    "type": "object",
    "properties": {"type": {"type": "string"}, "value": {}},
    "required": ["type", "value"],
    "additionalProperties": False,
    "description": "A body block as {type, value}; see content.get_schema for each type's value.",
}
OP = {"type": "string", "enum": ["insert", "replace", "delete", "meta"]}


def page_json(page) -> dict:
    """A page as an agent reads it: its latest revision (draft or live),
    with block ids, so a proposal can name the block it changes."""
    latest = page.get_latest_revision_as_object()
    revision = page.get_latest_revision()
    data = {
        "id": page.pk,
        "type": page._meta.label,
        "title": latest.title,
        "slug": latest.slug,
        "url_path": page.url_path,
        "live": page.live,
        "has_unpublished_changes": page.has_unpublished_changes,
        "revision_id": revision.pk if revision else None,
        "seo_title": latest.seo_title,
        "search_description": latest.search_description,
    }
    if hasattr(latest, "body"):
        data.update(
            {
                "ai_summary": latest.ai_summary,
                "ai_keywords": latest.ai_keywords,
                "agent_policy": latest.agent_policy,
                "legacy_path": latest.legacy_path,
                "body": list(latest.body.get_prep_value()),
            }
        )
    for name in getattr(latest, "hashed_fields", ()):
        value = latest.hashed_value(name)
        data.setdefault("fields", {})[name] = value
    return data


def _page(page_id: int):
    page = Page.objects.filter(pk=page_id).first()
    if page is None:
        raise ToolError("not_found", f"no page {page_id}")
    return page.specific


@tool(
    "content.get_schema",
    effect="read",
    description="The JSON Schema of every page type's meta fields and body blocks. Read it before proposing blocks.",
    input_schema=obj({"page_type": {"type": "string", "description": "e.g. cms.ArticlePage; omit for all."}}),
)
def get_schema(ctx, page_type=None):
    document = export()
    if page_type:
        if page_type not in document["pages"]:
            raise ToolError("not_found", f"no page type {page_type}; known: {', '.join(document['pages'])}")
        return {
            "version": document["version"],
            "page": document["pages"][page_type],
            "blocks": document["$defs"]["blocks"],
        }
    return document


@tool(
    "content.get_page",
    effect="read",
    description="One page's latest revision: title, meta fields, and its body blocks with their ids.",
    input_schema=obj({"page_id": {"type": "integer"}}, required=["page_id"]),
    page_arg="page_id",
)
def get_page(ctx, page_id):
    return page_json(_page(page_id))


@tool(
    "content.search",
    effect="read",
    description="Keyword search over live pages. Returns ids, titles, types and URLs.",
    input_schema=obj(
        {
            "query": {"type": "string", "minLength": 1},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50, "default": 10},
            "page_type": {"type": "string"},
        },
        required=["query"],
    ),
    rate="120/m",
)
def search(ctx, query, limit=10, page_type=None):
    qs = Page.objects.live().specific()
    if page_type:
        from django.apps import apps

        qs = apps.get_model(page_type).objects.live()
    hits = []
    for page in qs.search(query)[:limit]:
        hits.append(
            {"id": page.pk, "title": page.title, "type": page.specific_class._meta.label, "url_path": page.url_path}
        )
    return {"results": hits}


@tool(
    "content.propose_edit",
    effect="propose",
    description=(
        "Propose one change to a page as a Suggestion an editor accepts or rejects: insert a block (after block_id, "
        "or at the end), replace or delete a block by id, or set a meta field (title, seo_title, search_description, "
        "ai_summary, ai_keywords). The block is validated now; an invalid one is refused with the reason."
    ),
    input_schema=obj(
        {
            "page_id": {"type": "integer"},
            "op": OP,
            "block_id": {"type": "string"},
            "block": BLOCK,
            "field": {"type": "string"},
            "value": {},
            "rationale": {"type": "string", "minLength": 1, "maxLength": 2000},
        },
        required=["page_id", "op", "rationale"],
    ),
    perms=["wagtailcore.change_page"],
    page_arg="page_id",
    rate="300/m",
)
def propose_edit(ctx, page_id, op, rationale, block_id="", block=None, field="", value=None):
    page = _page(page_id)
    payload = block if op in ("insert", "replace") else ({"value": value} if op == "meta" else {})
    try:
        s = propose(
            target=page,
            op=op,
            user=ctx.user,
            run=ctx.run,
            agent=ctx.agent,
            block_id=block_id,
            payload=payload,
            field=field,
            rationale=rationale,
        )
    except SuggestionError as e:
        raise ToolError("invalid_args", str(e)) from e
    return {"suggestion_id": s.pk, "status": s.status, "op": s.op}


@tool(
    "content.draft_revision",
    effect="write",
    description=(
        "Write a new draft revision of a page directly, applying ops in order (each like content.propose_edit's). "
        "Needs policy draft; the default path is content.propose_edit."
    ),
    input_schema=obj(
        {
            "page_id": {"type": "integer"},
            "ops": {
                "type": "array",
                "minItems": 1,
                "maxItems": 50,
                "items": obj(
                    {
                        "op": OP,
                        "block_id": {"type": "string"},
                        "block": BLOCK,
                        "field": {"type": "string"},
                        "value": {},
                    },
                    required=["op"],
                ),
            },
            "rationale": {"type": "string", "minLength": 1},
        },
        required=["page_id", "ops", "rationale"],
    ),
    perms=["wagtailcore.change_page"],
    page_arg="page_id",
    rate="20/m",
)
def draft_revision(ctx, page_id, ops, rationale):
    from cms.services import save_draft

    page = _page(page_id)
    latest = page.get_latest_revision_as_object()
    written = []
    try:
        for op in ops:
            payload = op.get("block") if op["op"] in ("insert", "replace") else {"value": op.get("value")}
            if op["op"] != "delete":
                guard(payload.get("value"), payload.get("type"))
            block = apply_op(
                latest, op["op"], block_id=op.get("block_id", ""), payload=payload, field=op.get("field", "")
            )
            if block:
                written.append(block)
    except SuggestionError as e:
        raise ToolError("invalid_args", str(e)) from e
    revision = save_draft(latest, user=ctx.user)
    for block in written:
        BlockProvenance.objects.create(
            page_revision=revision,
            block_id=block,
            run=ctx.run,
            model=ctx.agent.model,
            prompt_version=ctx.run.prompt_version if ctx.run else "",
        )
    return {"revision_id": revision.pk, "blocks_written": written, "rationale": rationale}


@tool(
    "content.publish",
    effect="publish",
    description="Publish a page's latest revision. Needs policy auto on both the agent and the page.",
    input_schema=obj({"page_id": {"type": "integer"}}, required=["page_id"]),
    perms=["wagtailcore.publish_page"],
    page_arg="page_id",
    rate="10/m",
)
def publish_page(ctx, page_id):
    page = _page(page_id)
    revision = page.get_latest_revision()
    if revision is None:
        raise ToolError("not_found", f"page {page_id} has no revision to publish")
    revision.publish(user=ctx.user, skip_permission_checks=True)
    return {"page_id": page_id, "revision_id": revision.pk, "live": True}


def _image(image_id: int):
    image = get_image_model().objects.filter(pk=image_id).first()
    if image is None:
        raise ToolError("not_found", f"no image {image_id}")
    return image


@tool(
    "media.describe",
    effect="read",
    description="An image's title, size, focal point and its agent-proposed alt text, caption and tags.",
    input_schema=obj({"image_id": {"type": "integer"}}, required=["image_id"]),
)
def describe_image(ctx, image_id):
    image = _image(image_id)
    return {
        "id": image.pk,
        "title": image.title,
        "width": image.width,
        "height": image.height,
        "focal_point": [image.focal_point_x, image.focal_point_y, image.focal_point_width, image.focal_point_height],
        "ai_alt": image.ai_alt,
        "ai_caption": image.ai_caption,
        "ai_tags": image.ai_tags,
    }


@tool(
    "media.propose_alt",
    effect="propose",
    description="Propose alt text, a caption or tags for an image, as a Suggestion.",
    input_schema=obj(
        {
            "image_id": {"type": "integer"},
            "field": {"type": "string", "enum": ["ai_alt", "ai_caption", "ai_tags"]},
            "value": {},
            "rationale": {"type": "string", "minLength": 1},
        },
        required=["image_id", "field", "value", "rationale"],
    ),
    perms=["cms.choose_contentimage"],
)
def propose_alt(ctx, image_id, field, value, rationale):
    image = _image(image_id)
    try:
        s = propose(
            target=image,
            op=Suggestion.META,
            user=ctx.user,
            run=ctx.run,
            agent=ctx.agent,
            payload={"value": value},
            field=field,
            rationale=rationale,
        )
    except SuggestionError as e:
        raise ToolError("invalid_args", str(e)) from e
    return {"suggestion_id": s.pk, "status": s.status}
