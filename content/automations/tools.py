"""The automations' tool (`automations.fire_hook`), in the one registry (agents/registry.py), so an agent and an MCP
client fire a named hook under the same checks as every other tool.

What it sets off are other people's automations, which run as their owners and may send email, call webhooks, move
newsroom stories and start agent runs — so its effect is `write`: only an agent at policy `draft` or above, live and
past its evals, that lists the tool may call it. An agent fires only its own hooks: the name it gives is fired as
`agent.<slug>.<name>`, so it can never pose as one of the platform's (`monitor.finding`) or another agent's, and an
automation hears an agent only by naming it. The payload says the hook was fired by `agent:<slug>`; a run an
automation started never fires a hook, so automations cannot set each other off in a loop.
"""

from wagtail.models import Site

from agents.registry import ToolError, obj, tool
from ops.errors import Invalid

from . import services

NAME = {"type": "string", "pattern": r"^[a-z0-9][a-z0-9_.-]{0,63}$", "description": "e.g. flagged"}


def hook_of(agent) -> str:
    """The prefix of every hook `agent` fires."""
    return f"agent.{agent.slug.lower()}."


@tool(
    "automations.fire_hook",
    effect="write",
    description=(
        "Fire your named hook, agent.<your slug>.<hook>: every enabled automation waiting for it runs with the data "
        "you give, as its owner — who may have it email, call a webhook, move a story or start a run. Returns the "
        "hook's full name and how many automations it set off."
    ),
    input_schema=obj(
        {
            "hook": NAME,
            "data": {"type": "object", "description": "What the automations read, under `data` in their payload."},
            "site_id": {
                "type": "integer",
                "description": "The site it concerns: only that site's people's automations hear it.",
            },
        },
        required=["hook"],
    ),
    rate="30/m",
)
def fire_hook(ctx, hook, data=None, site_id=None):
    if services.from_automation(ctx.run):
        raise ToolError("not_allowed", "a run an automation started does not fire hooks")
    site = None
    if site_id is not None:
        site = Site.objects.filter(pk=site_id).first()
        if site is None:
            raise ToolError("not_found", f"no site {site_id}")
    name = hook_of(ctx.agent) + hook
    try:
        runs = services.fire_hook(name, data or {}, site=site, by=ctx.user.username)
    except Invalid as e:
        raise ToolError("invalid_args", e.message) from e
    return {"hook": name, "fired": len(runs)}
