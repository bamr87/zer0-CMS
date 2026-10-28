"""Distribution's tools in the one registry (agents/registry.py), so an agent,
an MCP client and the published-page consumer reach the queue under the same
checks as everything else.

* `distribution.compose` (`propose`): a draft post of a page for a channel of
  the page's site — never approved, never published; a person reviews it in the
  studio's Distribution queue. It needs the agent's change right on the page.
* `distribution.publish` (`publish`): publish a post **a person approved**, to a
  channel a person armed, on a deployment that armed the kind. The registry adds
  the rest: `publish` needs the narrower of the agent's and the page's policy to
  be `auto`, a live definition, and the page's publish permission as the agent
  user — which no agent group is given by default. It is the armed path, and it
  is off until every one of those is set on purpose.
"""

import uuid

from django.core.exceptions import PermissionDenied
from wagtail.models import Page

from agents.registry import ToolError, obj, tool
from ops.errors import ApiError

from . import services
from .models import Channel, DistributionPost

UUID = {"type": "string", "format": "uuid"}
CODES = {403: "permission_denied", 404: "not_found", 409: "not_allowed"}


def _refused(e: ApiError) -> ToolError:
    return ToolError(CODES.get(e.status, "invalid_args"), e.message)


def _row(model, public_id, ctx):
    try:
        key = uuid.UUID(str(public_id))
    except ValueError as e:
        raise ToolError("invalid_args", f"{public_id!r} is not a uuid") from e
    people = [ctx.user] + ([ctx.on_behalf_of] if ctx.on_behalf_of is not None else [])
    row = model.objects.filter(public_id=key).first()
    if row is None or any(not model.objects.visible_to(p).filter(pk=row.pk).exists() for p in people):
        raise ToolError("not_found", f"no {model.__name__} {public_id}")
    return row


def _summary(post) -> dict:
    return {
        "post": str(post.public_id),
        "status": post.status,
        "channel": str(post.channel.public_id),
        "link": post.link,
        "commentary": post.commentary,
        "guard": post.guard,
    }


@tool(
    "distribution.compose",
    effect="propose",
    description=(
        "Draft a post of a page for one of its site's distribution channels (LinkedIn, WordPress, a GitHub pull "
        "request, a newsletter). The draft waits for a person to approve it; nothing is published. Leave commentary "
        "out to start from the page's own summary and tags."
    ),
    input_schema=obj(
        {
            "channel": UUID,
            "page_id": {"type": "integer"},
            "commentary": {"type": "string", "maxLength": 3000},
            "title": {"type": "string", "maxLength": 255},
            "description": {"type": "string", "maxLength": 1000},
        },
        required=["channel", "page_id"],
    ),
    perms=("wagtailcore.change_page",),
    page_arg="page_id",
    rate="30/m",
)
def compose(ctx, channel, page_id, commentary=None, title=None, description=None):
    target = _row(Channel, channel, ctx)
    page = Page.objects.get(pk=page_id).specific
    try:
        post = services.compose(
            target,
            user=ctx.user,
            page=page,
            commentary=commentary,
            title=title,
            description=description,
            origin=DistributionPost.Origin.AGENT,
            run=ctx.run,
        )
    except ApiError as e:
        raise _refused(e) from e
    except PermissionDenied as e:
        raise ToolError("permission_denied", str(e)) from e
    return _summary(post)


@tool(
    "distribution.publish",
    effect="publish",
    description=(
        "Publish a distribution post a person has approved, to its channel. Refused unless the channel is armed by "
        "a person, the deployment publishes to its kind, and the page's agent policy is auto; returns at once, the "
        "post's status says how it went."
    ),
    input_schema=obj({"post": UUID, "page_id": {"type": "integer"}}, required=["post", "page_id"]),
    perms=("wagtailcore.publish_page",),
    page_arg="page_id",
    rate="10/m",
)
def publish(ctx, post, page_id):
    row = _row(DistributionPost, post, ctx)
    if row.page_id != page_id:
        raise ToolError("invalid_args", f"post {post} is not about page {page_id}")
    try:
        row = services.request_publish(row, ctx.user, agent=True)
    except ApiError as e:
        raise _refused(e) from e
    return _summary(row)
