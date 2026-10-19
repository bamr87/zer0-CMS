"""Agent definitions as code: `definitions/*.yaml` → `AgentDefinition` rows.

Each YAML file is one definition and its eval suite, reviewed in a pull
request like any other code. `sync()` provisions the agent's principal, then
creates the definition (not live) or, when anything changed, saves a new
draft revision — never touching the live row, so a running agent keeps the
configuration that passed its evals until a new one passes. Eval cases are
upserted by name, and cases removed from the file are deleted.
"""

from decimal import Decimal
from pathlib import Path

import yaml
from django.conf import settings
from django.db import transaction

from .models import AgentDefinition, EvalCase
from .principals import ensure_principal

FIELDS = (
    "name",
    "description",
    "role",
    "system_prompt",
    "model",
    "tools",
    "policy",
    "max_steps",
    "budget_usd",
    "handler",
    "profile",
)


def load(directory=None) -> list[dict]:
    directory = Path(directory or settings.AGENT_DEFINITIONS_DIR)
    specs = []
    for path in sorted(directory.glob("*.yaml")):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        if spec.get("slug") != path.stem:
            raise ValueError(f"{path.name}: slug must match the file name ({path.stem})")
        specs.append(spec)
    return specs


def _values(spec: dict) -> dict:
    values = {
        "name": spec.get("name", spec["slug"]),
        "description": spec.get("description", ""),
        "role": spec.get("role", "author"),
        "system_prompt": spec.get("system_prompt", ""),
        "model": spec.get("model", ""),
        "tools": list(spec.get("tools", [])),
        "policy": spec.get("policy", "suggest"),
        "max_steps": int(spec.get("max_steps", 8)),
        "budget_usd": Decimal(str(spec.get("budget_usd", "0.50"))),
        "handler": spec.get("handler", ""),
        "profile": spec.get("profile", {}),
    }
    # A file may *ask* for draft or auto; publishing that revision still needs
    # the accept rate the gate checks (agents/evals.py), so asking is not getting.
    return values


def _differs(obj, values: dict) -> bool:
    return any(
        (Decimal(str(getattr(obj, k))) != v) if k == "budget_usd" else getattr(obj, k) != v for k, v in values.items()
    )


@transaction.atomic
def sync_one(spec: dict) -> tuple[AgentDefinition, str]:
    from .registry import registry

    unknown = [t for t in spec.get("tools", []) if t not in registry.names()]
    if unknown:
        raise ValueError(f"{spec['slug']}: unknown tool(s) {', '.join(unknown)}")
    values = _values(spec)
    ensure_principal(spec["slug"], role=values["role"])
    definition = AgentDefinition.objects.filter(slug=spec["slug"]).first()
    if definition is None:
        definition = AgentDefinition(slug=spec["slug"], live=False, **values)
        definition.save()
        definition.save_revision(log_action=False)
        state = "created"
    else:
        latest = definition.get_latest_revision_as_object()
        if _differs(latest, values):
            for key, value in values.items():
                setattr(latest, key, value)
            latest.save_revision(log_action=False)
            state = "revised"
        else:
            state = "unchanged"
    names = []
    for case in spec.get("evals", []):
        EvalCase.objects.update_or_create(
            agent=definition,
            name=case["name"],
            defaults={"input": case.get("input", {}), "checks": case.get("checks", []), "tags": case.get("tags", [])},
        )
        names.append(case["name"])
    EvalCase.objects.filter(agent=definition).exclude(name__in=names).delete()
    return definition, state


def sync(directory=None) -> list[tuple[AgentDefinition, str]]:
    return [sync_one(spec) for spec in load(directory)]
