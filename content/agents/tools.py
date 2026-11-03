"""The harness's own tools: scoped memory, the house style and the runs an agent may read.

`memory.remember` writes to `Memory`, the agent-owned layer editors can read
and correct (note §4); it is `propose`, not `write`, because it changes no
content. Agents read the brand rules before writing (`brand.rules`). A tool
that starts a run (`ai.run_assistant`, `ai.generate_brief`) answers with its
id; `runs.get` reads it back, scoped as REST is (`AgentRun.objects.visible_to`).
"""

import uuid
from datetime import timedelta

from django.utils import timezone

from .models import AgentRun, Memory
from .registry import ToolError, obj, tool

SCOPE = {"type": "string", "enum": Memory.SCOPES}


@tool(
    "memory.recall",
    effect="read",
    description="What has been remembered under a scope (global, site, section, page, user, agent), optionally one key.",
    input_schema=obj({"scope": SCOPE, "scope_id": {"type": "string"}, "key": {"type": "string"}}, required=["scope"]),
)
def recall(ctx, scope, scope_id="", key=None):
    now = timezone.now()
    qs = Memory.objects.filter(scope=scope, scope_id=scope_id).exclude(expires_at__lt=now)
    if key:
        qs = qs.filter(key=key)
    return {"memories": [{"key": m.key, "value": m.value, "updated_at": m.updated_at.isoformat()} for m in qs]}


@tool(
    "memory.remember",
    effect="propose",
    description="Remember a value under a scope and key, optionally for a number of days.",
    input_schema=obj(
        {
            "scope": SCOPE,
            "scope_id": {"type": "string"},
            "key": {"type": "string", "minLength": 1, "maxLength": 120},
            "value": {},
            "ttl_days": {"type": "integer", "minimum": 1, "maximum": 3650},
        },
        required=["scope", "key", "value"],
    ),
    rate="60/m",
)
def remember(ctx, scope, key, value, scope_id="", ttl_days=None):
    memory, _ = Memory.objects.update_or_create(
        scope=scope,
        scope_id=scope_id,
        key=key,
        defaults={
            "value": value if isinstance(value, dict) else {"value": value},
            "updated_by_run": ctx.run,
            "expires_at": timezone.now() + timedelta(days=ttl_days) if ttl_days else None,
        },
    )
    return {"key": memory.key, "scope": memory.scope}


@tool(
    "brand.rules",
    effect="read",
    description="The house style guide and the banned phrases every proposal is checked against — the run's "
    "page's site's own brand voice and bans included, the built-in ones left out where its book switched them off.",
    input_schema=obj({}),
)
def brand_rules(ctx):
    """From the one composition of a voice (voice/services.py), which the studio's Voice tab shows."""
    from suggestions.guard import site_of
    from voice.services import resolve, told

    target = ctx.extra.get("target")
    return told(resolve(site_of(target), page=target))


@tool(
    "runs.get",
    effect="read",
    description="A run you may read — your own, or one you started with a tool such as ai.run_assistant: its status, "
    "output and error, and with steps each model and tool call it made.",
    input_schema=obj(
        {"run_id": {"type": "string", "format": "uuid"}, "steps": {"type": "boolean"}}, required=["run_id"]
    ),
)
def get_run(ctx, run_id, steps=False):
    from api.views import run_json  # noqa: PLC0415 — the one JSON shape of a run; api imports the harness

    try:
        key = uuid.UUID(str(run_id))
    except ValueError as e:
        raise ToolError("invalid_args", f"{run_id!r} is not a uuid") from e
    run = AgentRun.objects.visible_to(ctx.user).select_related("agent", "target_ct").filter(public_id=key).first()
    if run is None:
        raise ToolError("not_found", f"no run {run_id}")
    return run_json(run, steps=steps)
