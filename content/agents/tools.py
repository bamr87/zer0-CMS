"""The harness's own tools: scoped memory and the house style.

`memory.remember` writes to `Memory`, the agent-owned layer editors can read
and correct (note §4); it is `propose`, not `write`, because it changes no
content. Agents read the brand rules before writing (`brand.rules`).
"""

from datetime import timedelta

from django.utils import timezone

from .models import Memory
from .registry import obj, tool

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
    "page's site's own brand voice and bans included.",
    input_schema=obj({}),
)
def brand_rules(ctx):
    from cms.models import BrandRules
    from sites.models import SiteSettings
    from suggestions.guard import BANNED_PATTERNS, site_of

    active = BrandRules.objects.filter(is_active=True)
    own = SiteSettings.objects.filter(site=site_of(ctx.extra.get("target"))).first()
    entries = [p for r in active for p in (r.banned_patterns or [])] + (own.banned_patterns if own else [])
    return {
        "style_guides": [r.style_guide for r in active if r.style_guide]
        + ([own.brand_voice] if own and own.brand_voice else []),
        "banned": [name for name, _ in BANNED_PATTERNS] + [p.get("name") for p in entries if isinstance(p, dict)],
    }
