"""The automations' tool (`automations.fire_hook`), in the one registry (agents/registry.py), so an agent and an MCP
client fire a named hook under the same checks as every other tool.

Its effect is `propose`: what it sets off are automations, which run as their owners and only ever make proposals —
answers, briefs, ideas, notifications, a story moved to a stage that publishes nothing. An agent offers it by listing
it in its definition. The payload says the hook was fired by `agent:<slug>`, so an automation may insist on who fires
it; a run an automation started never fires a hook, so automations cannot set each other off in a loop.
"""

from wagtail.models import Site

from agents.registry import ToolError, obj, tool
from ops.errors import Invalid

from . import services, spec


@tool(
    "automations.fire_hook",
    effect="propose",
    description=(
        "Fire a named hook (e.g. monitor.finding): every enabled automation waiting for it runs with the data you "
        "give, as its owner, making proposals a person reviews. Returns how many automations it set off."
    ),
    input_schema=obj(
        {
            "hook": spec.HOOK,
            "data": {"type": "object", "description": "What the automations read, under `data` in their payload."},
            "site_id": {"type": "integer", "description": "The site it concerns: that site's automations hear it."},
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
    try:
        runs = services.fire_hook(hook, data or {}, site=site, by=ctx.user.username)
    except Invalid as e:
        raise ToolError("invalid_args", e.message) from e
    return {"hook": hook, "fired": len(runs)}
