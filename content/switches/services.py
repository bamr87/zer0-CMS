"""The content switches: the hub's switch map, each outlet's live variables, and
what a flip would write — read, compared and written in one place
(switches/README.md).

**The record.** The hub's switch map (bamr87/bamr87 `_data/fleet.yml`,
`switches:`, schema `switches/v1`) records every loop's kill switch: its
repository, workflow, group, gate (`repo_variable` with a `name` and
`semantics`), default, state (`on`, `off` or `unverified`), who set it, when
and why, and an optional `hold` — a code-level hold that idles the workflow
whatever the variable says. It is the source of truth and the repositories'
variables are its projections (the hub's constitution § 17). The platform reads
it from GitHub (`ZER0_HUB_CHECKOUT` reads a local checkout instead) and never
writes it: after a flip a switch shows drift until the hub records it.

**Reading a switch the way its loop reads it** (`effective`), as the hub's
`tools/weekly/prepare.py` `switch_state` does: a global or group level that is
off wins; then an `opt_in` switch is on only when its variable is exactly
`true` (unset is off) and an `opt_out` one is on unless it is exactly `false`
(unset is on). A variable that could not be read is `unknown` — a 401, 403 or
404 on the list is "unreadable", never "off". A `*_ENABLED` variable the map
has no record of is listed too ("not in the hub map"); its semantics are
unknown, but `true` is on and `false` off either way.

**Drift** is the live value disagreeing with the map's recorded state (its
default while the state is `unverified`). The hub's weekly report compares
with the default; this compares with the recorded state, since recording the
flip in the hub is what clears it.

**Flipping.** `preview` says what a flip of one switch, or of every switch of
an outlet, would write — `true` to switch on and `false` to switch off, which
is right under either semantics — and writes nothing. `apply` re-reads, refuses
when anything changed since the preview (its digest), and starts the `switches`
job: the worker sets each variable (PATCH, POST on a 404), reads it back, and
emits `content.switches.flipped` (schemas/events/) with who, what, the scope,
the reason, and each old and new value. What merges without a person
(`MERGE_AUTHORITY`) is a brake here: a flip may switch it off, never on — the
same line the extension's Fleet console draws (`src/core/fleet/policy.ts`).
"""

import hashlib
import json
import re
from pathlib import Path

import yaml
from django.conf import settings
from django.db import transaction

from jobs import services as jobs
from outbox.services import emit

from . import github
from .models import SwitchConfig

HUB_REPO = "bamr87/bamr87"
HUB_PATH = "_data/fleet.yml"
HUB_REF = "main"
SCHEMA = "switches/v1"
EVENT = "content.switches.flipped"
SWITCHY = re.compile(r"\A[A-Z][A-Z0-9_]*_ENABLED\Z")
MERGE_AUTHORITY = re.compile(r"AUTO_?MERGE|\AAUTO_UPDATE_ENABLED\Z|\AAUTO_FIX_ENABLED\Z")
NEEDS = (
    "a fine-grained personal access token whose repository permission “Variables” (the Actions variables) is "
    "read and write, on {repos}"
)


class SwitchError(Exception):
    """A request the switches cannot serve as asked; the message says why."""


class Changed(SwitchError):
    """What the person previewed is no longer what a flip would write."""


def needs(outlets) -> str:
    return NEEDS.format(repos=", ".join(outlets) or "the outlets")


def merge_authority(name: str) -> bool:
    return bool(MERGE_AUTHORITY.search(str(name or "")))


# ── the hub's map ─────────────────────────────────────────────────────────────


def read_hub(client: github.Client) -> dict:
    """The map's `switches:` section and where it was read; `map` is None, with the reason, when it could not be."""
    checkout = settings.SWITCHES_HUB_CHECKOUT
    where = {"repo": HUB_REPO, "path": HUB_PATH, "ref": HUB_REF, "read_from": "checkout" if checkout else "github"}
    try:
        if checkout:
            text = (Path(checkout) / HUB_PATH).read_text(encoding="utf-8")
        else:
            owner, repo = github.split_repo(HUB_REPO)
            text = client.request("hub_map", owner=owner, repo=repo, path=HUB_PATH, query={"ref": HUB_REF}).text
    except OSError:
        return {**where, "map": None, "error": f"{HUB_PATH} could not be read from the hub checkout"}
    except github.Error as e:
        return {**where, "map": None, "error": f"the hub's {HUB_PATH} could not be read ({e})"}
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError:
        return {**where, "map": None, "error": f"the hub's {HUB_PATH} is not YAML"}
    switches = document.get("switches") if isinstance(document, dict) else None
    if not isinstance(switches, dict) or switches.get("schema") != SCHEMA:
        return {**where, "map": None, "error": f"the hub's {HUB_PATH} has no `switches:` section of schema {SCHEMA}"}
    return {**where, "map": switches, "error": ""}


def records_for(switch_map: dict | None, repo: str) -> list[tuple[str, dict]]:
    """The map's loops of one repository, in the map's order."""
    loops = (switch_map or {}).get("loops") or {}
    return [
        (str(ident), entry)
        for ident, entry in loops.items()
        if isinstance(entry, dict) and str(entry.get("repo") or "").lower() == repo.lower()
    ]


# ── the live variables ──────────────────────────────────────────────────────


def read_variables(client: github.Client, repo: str) -> tuple[dict[str, str] | None, str]:
    """Every Actions variable of a repository, by name — or None, with the reason, when GitHub would not say."""
    owner, name = github.split_repo(repo)
    found: dict[str, str] = {}
    page = 1
    while True:
        try:
            body = client.request(
                "variables", owner=owner, repo=name, query={"per_page": github.PAGE, "page": page}
            ).json()
        except github.Error as e:
            return None, f"{repo}'s variables could not be read ({e})"
        except ValueError:
            return None, f"{repo}'s variables came back as something other than JSON"
        rows = body.get("variables") or []
        found.update({str(v.get("name")): str(v.get("value", "")) for v in rows if v.get("name")})
        if not rows or len(found) >= int(body.get("total_count") or 0) or page >= 20:
            return found, ""
        page += 1


# ── one switch, read the way its loop reads it ─────────────────────────────────


def effective(semantics: str | None, value: str | None, *, readable: bool = True) -> str:
    """`on`, `off` or `unknown` for a variable's value (None: unset). `semantics` None is a variable the map has no
    record of: `true` and `false` mean the same under either, anything else is unknown."""
    if not readable:
        return "unknown"
    if semantics == "opt_in":
        return "on" if value == "true" else "off"
    if semantics == "opt_out":
        return "off" if value == "false" else "on"
    return {"true": "on", "false": "off"}.get(value or "", "unknown")


def _hold(entry: dict) -> dict | None:
    hold = entry.get("hold")
    if not isinstance(hold, dict):
        return None
    return {key: str(hold[key]) for key in ("kind", "name", "value", "source", "lift") if hold.get(key) is not None}


def _text(value) -> str | None:
    return None if value in (None, "") else str(value)


def evaluate(ident: str, entry: dict, switch_map: dict, live: dict[str, str] | None) -> dict:
    """One map record as a row: the live value, what it means for the loop, what the map says, drift and hold."""
    gate = entry.get("gate") if isinstance(entry.get("gate"), dict) else {}
    kind = str(gate.get("kind") or "none")
    semantics = gate.get("semantics") if gate.get("semantics") in ("opt_in", "opt_out") else None
    variable = str(gate["name"]) if kind == "repo_variable" and gate.get("name") else None
    default = "off" if str(entry.get("default") or "on") == "off" else "on"
    state = str(entry.get("state") or "unverified")
    state = state if state in ("on", "off") else "unverified"
    row = {
        "loop": ident,
        "workflow": _text(entry.get("workflow")),
        "variable": variable,
        "gate": kind,
        "semantics": semantics,
        "default": default,
        "in_map": True,
        "live": None,
        "live_state": "none",
        "effective": "unknown",
        "why": "",
        "map_state": state,
        "verified": bool(entry.get("verified")),
        "reason": _text(entry.get("reason")),
        "set_by": _text(entry.get("set_by")),
        "set_at": _text(entry.get("set_at")),
        "drift": False,
        "hold": _hold(entry),
        "flippable": variable is not None and semantics is not None,
        "merge_authority": merge_authority(variable or ""),
    }
    levels = (
        ("global", switch_map.get("global") or {}),
        (f"group {entry.get('group')}", ((switch_map.get("groups") or {}).get(entry.get("group")) or {})),
    )
    if variable is not None:
        if live is None:
            row["live_state"] = "unreadable"
        else:
            row["live"] = live.get(variable)
            row["live_state"] = "unset" if variable not in live else "set"
    for name, level in levels:
        if isinstance(level, dict) and level.get("state") == "off":
            row["effective"], row["why"] = (
                "off",
                f"{name} is off" + (f": {level['reason']}" if level.get("reason") else ""),
            )
            return row
    if variable is not None and semantics is not None:
        row["effective"] = effective(semantics, row["live"], readable=live is not None)
        if live is None:
            row["why"] = f"{variable} could not be read"
        else:
            shown = repr(row["live"]) if row["live_state"] == "set" else "unset"
            row["why"] = f"{variable} is {shown} ({semantics.replace('_', '-')})"
            recorded = state if state != "unverified" else default
            row["drift"] = row["effective"] != recorded
    elif kind in ("none", "env", "fleet_config", "planned") or variable is None:
        row["effective"] = state if state != "unverified" else default
        row["why"] = "no repository switch: " + (
            f"the map says {state}" if state != "unverified" else f"the map's default is {default}"
        )
    if row["hold"]:
        row["why"] += f"; held by {row['hold'].get('name', 'a hold')} whatever the variable says"
    return row


def unmapped(live: dict[str, str] | None, mapped: set[str]) -> list[dict]:
    """The `*_ENABLED` variables of a repository the map has no record of."""
    rows = []
    for variable in sorted(name for name in (live or {}) if SWITCHY.match(name) and name not in mapped):
        value = live[variable]
        rows.append(
            {
                "loop": None,
                "workflow": None,
                "variable": variable,
                "gate": "repo_variable",
                "semantics": None,
                "default": None,
                "in_map": False,
                "live": value,
                "live_state": "set",
                "effective": effective(None, value),
                "why": f"{variable} is {value!r}; not in the hub map, so its semantics are unknown",
                "map_state": None,
                "verified": False,
                "reason": None,
                "set_by": None,
                "set_at": None,
                "drift": False,
                "hold": None,
                "flippable": True,
                "merge_authority": merge_authority(variable),
            }
        )
    return rows


def outlet(repo: str, switch_map: dict | None, client: github.Client, *, token: bool) -> dict:
    """An outlet's switches: the map's records of it, then the variables it has that the map does not."""
    live, error = read_variables(client, repo) if token else (None, "no credential: the variables are not read")
    records = records_for(switch_map, repo)
    rows = [evaluate(ident, entry, switch_map or {}, live) for ident, entry in records]
    rows += unmapped(live, {row["variable"] for row in rows if row["variable"]})
    return {"repo": repo, "readable": live is not None, "error": error, "switches": rows}


def _credential(config: SwitchConfig) -> tuple[str, str]:
    token = config.get_credential()
    if config.has_credential and not token:
        return "", "the stored credential was encrypted with a key that is gone: set it again"
    return token, ""


def board(config: SwitchConfig | None = None, *, repos: list[str] | None = None) -> dict:
    """Everything the studio's table shows: the map as read, the credential's state, and each outlet's switches."""
    config = config or SwitchConfig.load()
    token, problem = _credential(config)
    with github.Client(token) as client:
        hub = read_hub(client)
        outlets = [outlet(repo, hub["map"], client, token=bool(token)) for repo in (repos or config.outlets)]
    return {
        "hub": {key: hub[key] for key in ("repo", "path", "ref", "read_from", "error")}
        | {"read": hub["map"] is not None},
        "credential": {"set": config.has_credential, "error": problem, "needs": needs(config.outlets)},
        "outlets": outlets,
    }


# ── preview and apply ───────────────────────────────────────────────────────


def preview(repo: str, *, target: str, switch: str | None = None, reason: str = "", config=None) -> dict:
    """What flipping one switch (`switch`, a variable name) or every switch of an outlet to `target` would write,
    read from GitHub now. Writes nothing."""
    config = config or SwitchConfig.load()
    if repo not in config.outlets:
        raise SwitchError(f"{repo} is not one of the outlets")
    if target not in ("on", "off"):
        raise SwitchError("target is on or off")
    read = board(config, repos=[repo])
    rows = [row for row in read["outlets"][0]["switches"] if row["flippable"]]
    if switch is not None:
        rows = [row for row in rows if row["variable"] == switch]
        if not rows:
            raise SwitchError(f"{repo} has no switch {switch} that this can flip")
    new = "true" if target == "on" else "false"
    changes, seen = [], {}
    for row in rows:
        if row["variable"] in seen:
            if row["loop"]:
                seen[row["variable"]]["loops"].append(row["loop"])
            continue
        change = {
            "name": row["variable"],
            "loops": [row["loop"]] if row["loop"] else [],
            "in_map": row["in_map"],
            "current": row["live"],
            "current_state": row["live_state"],
            "new": new,
            "action": "",
            "why": "",
            "hold": row["hold"],
        }
        if row["live_state"] == "unreadable":
            change["action"], change["why"] = "unreadable", read["outlets"][0]["error"] or "it could not be read"
        elif effective(row["semantics"], row["live"]) == target:
            shown = repr(row["live"]) if row["live_state"] == "set" else "unset"
            change["action"], change["why"] = "none", f"already {target} ({shown})"
        elif target == "on" and row["merge_authority"]:
            change["action"] = "refused"
            change["why"] = "it decides what merges without a person: switch it on in the hub, not from here"
        else:
            change["action"] = "create" if row["live_state"] == "unset" else "update"
            change["why"] = (
                "not in the hub map: record it there" if not row["in_map"] else "then record it in the hub map"
            )
        seen[row["variable"]] = change
        changes.append(change)
    plan = [[c["name"], c["current_state"], c["current"], c["new"], c["action"]] for c in changes]
    digest = hashlib.sha256(json.dumps([repo, target, plan]).encode()).hexdigest()
    return {
        "repo": repo,
        "scope": "switch" if switch else "outlet",
        "switch": switch,
        "target": target,
        "reason": reason,
        "changes": changes,
        "writes": sum(c["action"] in ("create", "update") for c in changes),
        "digest": digest,
        "credential": read["credential"],
        "hub": read["hub"],
    }


def apply(repo: str, *, target: str, switch: str | None, reason: str, digest: str, user):
    """Start the flip a person previewed and confirmed (the `switches` job), after reading it all again."""
    config = SwitchConfig.load()
    if not reason.strip():
        raise SwitchError("a flip needs a reason")
    if not config.has_credential:
        raise SwitchError(f"no credential: the platform needs {needs(config.outlets)}")
    fresh = preview(repo, target=target, switch=switch, reason=reason, config=config)
    if fresh["credential"]["error"]:
        raise SwitchError(fresh["credential"]["error"])
    if fresh["digest"] != digest:
        raise Changed("the switches changed since the preview: preview the flip again")
    if any(c["action"] == "unreadable" for c in fresh["changes"]):
        raise Changed("a switch in scope could not be read: preview the flip again once it can be")
    writes = [c for c in fresh["changes"] if c["action"] in ("create", "update")]
    if not writes:
        raise SwitchError(f"nothing to write: every switch in scope is already {target} or refused")
    params = {
        "repo": repo,
        "scope": fresh["scope"],
        "switch": switch,
        "target": target,
        "reason": reason.strip(),
        "by": user.get_username(),
        "changes": [{key: c[key] for key in ("name", "loops", "current", "new", "action")} for c in writes],
    }
    return jobs.start("switches", user=user, params=params)


def _write(client: github.Client, owner: str, repo: str, name: str, value: str) -> str:
    body = {"name": name, "value": value}
    try:
        client.request("variable_update", owner=owner, repo=repo, name=name, json=body)
        return "updated"
    except github.Error as e:
        if e.status != 404:
            raise
    client.request("variable_create", owner=owner, repo=repo, json=body)
    return "created"


@jobs.handler("switches")
def run_flip(job, ctx) -> dict:
    """The worker's half of `apply`: set each variable, read it back, and record the flip as an event — every write
    attempted is recorded, whether or not it held."""
    p = job.params
    owner, name = github.split_repo(p["repo"])
    token, problem = _credential(SwitchConfig.load())
    if not token:
        ctx.log(problem or "no credential", "error")
        raise jobs.Failed(problem or "no credential to write the variables with")
    results = []
    with github.Client(token) as client:
        for change in p["changes"]:
            result = {**change, "old": change["current"], "result": "failed", "verified": False, "error": ""}
            try:
                result["result"] = _write(client, owner, name, change["name"], change["new"])
                back = client.request("variable", owner=owner, repo=name, name=change["name"]).json()
                result["verified"] = str(back.get("value")) == change["new"]
            except (github.Error, ValueError) as e:
                result["error"] = str(e)
            ctx.log(
                f"{change['name']}: {change['current'] if change['current'] is not None else 'unset'} → {change['new']}"
                f" ({result['result']}{', read back' if result['verified'] else ''}){' — ' + result['error'] if result['error'] else ''}",
                "info" if result["verified"] else "error",
            )
            results.append(result)
    changes = [
        {key: r[key] for key in ("name", "loops", "old", "new", "result", "verified")}
        | ({"error": r["error"]} if r["error"] else {})
        for r in results
    ]
    data = {
        "repo": p["repo"],
        "scope": p["scope"],
        "switch": p["switch"],
        "target": p["target"],
        "reason": p["reason"],
        "by": p["by"],
        "job": str(job.public_id),
        "changes": changes,
    }
    with transaction.atomic():
        emit(EVENT, data, subject=f"repo:{p['repo']}")
    ctx.log(
        f"Recorded as {EVENT}. The hub's map still says what it said: record the flip there ({HUB_REPO} {HUB_PATH})."
    )
    failed = [r["name"] for r in results if not r["verified"]]
    if failed:
        raise jobs.Failed(f"{len(failed)} of {len(results)} did not hold: {', '.join(failed)}")
    return {"repo": p["repo"], "target": p["target"], "changes": changes}


@transaction.atomic
def rotate_credentials(**_signal) -> int:
    """The credential under the AI layer's first key, for `manage.py rotate_ai_credentials` (it sends
    `ai.crypto.credentials_rotated` in its transaction)."""
    from ai import crypto
    from ai.providers import NotConfigured

    rows = list(SwitchConfig.objects.exclude(credential_encrypted=""))
    for config in rows:
        try:
            fresh = crypto.encrypt(crypto.decrypt(config.credential_encrypted))
        except crypto.InvalidToken as e:
            raise NotConfigured(
                "the content switches' credential was encrypted with a key that is gone: add that key to "
                "AI_CREDENTIAL_KEYS (or its SECRET_KEY to SECRET_KEY_FALLBACKS) and rotate again, or set it again"
            ) from e
        SwitchConfig.objects.filter(pk=config.pk).update(credential_encrypted=fresh)
    return len(rows)
