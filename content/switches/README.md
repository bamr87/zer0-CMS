# `switches/` — the content outlets' switches

> The GitHub Actions content loops of the outlets the platform publishes through, read against the hub's switch map, and flipped by a person who manages sites — previewed first, applied only on confirmation with a reason, recorded as an event.

The content outlets — `bash-365/bash-365.com`, `bamr87/lifehacker.dev` and `bamr87/it-journey` until a person changes the list — run their content loops (the content factory, the content loop, auto-merge, the weekly epic …) as GitHub Actions workflows, each gated by a repository variable: a **switch**. The studio's **Content switches** section (`/studio/sites/switches`, `web/packages/ui/src/sites/ContentSwitches.tsx`, also in the extension through the Sites workspace) shows every outlet's switches and flips them. ADR 0013 records why the platform holds a credential for it and records each flip as an event.

## The record and its projections

The hub's switch map — bamr87/bamr87 `_data/fleet.yml`, section `switches:`, schema `switches/v1` — is the record of every loop's switch: its repository, workflow, group, gate (`kind: repo_variable` with a `name` and `semantics: opt_in | opt_out`), default, state (`on`, `off` or `unverified`), who set it, when and why, and an optional `hold:` (a code-level hold that idles the workflow whatever the variable says). The repositories' variables are its projections (the hub's constitution § 17). The platform reads the map — from GitHub (`GET /repos/bamr87/bamr87/contents/_data/fleet.yml?ref=main`, with the credential when one is set), or from a local checkout of the hub when `ZER0_HUB_CHECKOUT` names one — and **never writes it**: after a flip a switch shows drift until the hub records it, and the hub's console is where that is done.

## Reading a switch

`services.evaluate` reads a switch the way its loop does, as the hub's `tools/weekly/prepare.py` `switch_state` does:

- a global or group level of the map that is `off` wins;
- an `opt_in` switch is on only when its variable is exactly `true` (unset is off); an `opt_out` one is on unless it is exactly `false` (unset is on);
- a variable GitHub would not give (401, 403, 404, the rate limit, no credential) is **unknown**, never off;
- a loop with no repository switch (`gate.kind` none, env, fleet_config, planned) is what the map says.

Each row also carries the map's state, whether it was verified, its reason, who set it and when, its hold, and **drift**: the live value disagreeing with the map's recorded state (its default while the state is `unverified`). The hub's weekly report compares with the default; this compares with the recorded state, since recording the flip in the hub is what clears it. Every `*_ENABLED` variable an outlet has that the map has no record of is listed too, "not in the hub map": its semantics are unknown, but `true` is on and `false` off either way.

## Flipping

| Step | What happens |
|---|---|
| Preview (`POST /api/v2/switches/preview/`) | For one switch (`switch`, a variable name) or every switch of an outlet, to `on` or `off`: each variable as it is and as it would be — `true` to switch on and `false` to switch off, right under either semantics — and what happens to it (`update`, `create`, `none` when it is already there, `refused`, `unreadable`), with a digest of the whole plan. Writes nothing. The reason may come with it, and is not needed yet |
| Apply (`POST /api/v2/switches/apply/`) | Needs `confirm: true`, a reason and the preview's digest. It reads everything again and is refused (409 `switches.changed`) when the plan is no longer the one previewed, or a switch in scope cannot be read; then starts the `switches` job (202) |
| The job (`run_flip`, on the worker) | Sets each variable (`PATCH`, and `POST` to create it when the update answers 404), reads it back, logs each old → new, and emits `content.switches.flipped` (`schemas/events/`) with who, the outlet, the scope, the reason and each old and new value and whether it held — every write attempted, whether or not it held. A write that did not hold fails the job |

What merges without a person — `AUTO_MERGE_ENABLED`, `AUTO_UPDATE_ENABLED`, `AUTO_FIX_ENABLED` and any `*AUTOMERGE*` switch (`MERGE_AUTHORITY`) — is a **brake** here: a flip may switch it off, never on (`refused`), the line the extension's Fleet console draws (`src/core/fleet/policy.ts`). Arming it is recorded in the hub.

## The GitHub surface

`github.py` declares every call before it is made (`CALLS`), and `Client.request` takes a call id, never a URL: the hub's file (raw), an outlet's variables (a page of 30 at a time), one variable, and the two writes, update and create. Three guards are tests (`tests/switches/test_github.py`): every path is a repository's own Actions variables or a file of its contents and every `returns` says "own"; no path reaches a secret; nothing is deleted. A name is one path segment, checked before a URL is built. Nothing dispatches a workflow, merges or reads a secret.

## The credential

`SwitchConfig` (one row) keeps the outlets and the credential: a fine-grained personal access token whose repository permission "Variables" (the Actions variables) is read and write, on the outlets. A person who manages sites types it in the studio; it is encrypted at rest with the AI layer's keys (`ai/crypto.py`, rotated with them by `manage.py rotate_ai_credentials`), never returned by the API (only `has_credential`), never logged and never put in an error — the client scrubs it out of any message. Without one, the section shows the map read-only and says what is needed.

## Who may

Everything here is for people who manage sites (`sites.manage_site`; a superuser holds it): the variables are read with the platform's credential, which GitHub gives only to a repository's collaborators. Agents are refused, as at every studio endpoint.

## Settings

| Variable | Default | What |
|---|---|---|
| `ZER0_HUB_CHECKOUT` | — | A local checkout of the hub: the map is read from its `_data/fleet.yml` instead of GitHub |
| `ZER0_GITHUB_API` | `https://api.github.com` | GitHub's API (an Enterprise host, or a stub in a test) |
| `ZER0_GITHUB_TIMEOUT` | `10` | Seconds one GitHub call may take |

## The API (`/api/v2/switches/`)

| Path | What |
|---|---|
| `GET /` | The hub's map as read (`hub`), the credential's state and what is needed (`credential`), and every outlet's switches (`outlets`) |
| `GET`, `PATCH /config/` | The outlets (owner/name each), and the credential — write-only, `""` removes it |
| `POST /preview/` | What a flip would write; writes nothing |
| `POST /apply/` | The flip a person previewed and confirmed (202 with the job, followed at `/api/v2/jobs/<id>/`; `Idempotency-Key`) |

Tests: `tests/switches/` — `test_services.py` (reading a switch), `test_github.py` (the surface and the client), `test_api.py` (the API and the job end to end over recorded GitHub, with respx: nothing reaches GitHub).
