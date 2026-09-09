# `src/core/fleet` — the Fleet console's pure half

This repository's AI lanes, read from its `fleet.manifest.yml`, and the gate in front of the two things a person can do to one: flip its `*_ENABLED` switch, or dispatch it once. Pure Node, like everything under `src/core/` — no `vscode`, no filesystem in the gate, and the network behind an injected `fetch`.

| File | What it owns |
|---|---|
| `manifest.ts` | `readFleetManifest` / `parseFleetManifest` / `coerceFleetManifest`: `fleet.manifest.yml` (spec `fleet/v1`, from bamr87/wtd `docs/FLEET-SPEC.md`) → the `FleetManifest` shape declared in `shared/types.ts`. Plus the small readers: `laneById`, `isDispatchable`, `workflowFileOf`, `describeTriggers`, `describeGuardrails`. |
| `fleet.ts` | The domain. `FleetLaneState` (a lane plus what the repository says about it), `switchValueOf`, `nextSwitchValue`, `buildLaneStates`, and **`evaluateFleetGates`** — the gate. |
| `github.ts` | The GitHub surface **as data** (`FLEET_READS`, `FLEET_WRITES`, `FLEET_PLAN`), the guard `fleetSurfaceIsRepoScopedOnly`, `describeFleetPlan`, and `githubFleetClient` — a `FleetClient` over an injected `fetch` that refuses any request not in the plan. |

## The manifest is untrusted

It is written by a tool, edited by hand and committed, so it is coerced field by field the way `contract/contract.ts` coerces the engine's index: an unknown `harness` becomes `none`, an unknown trigger kind is dropped, a missing list is `[]`, a guardrail the manifest did not mention is `null` — which is a different answer from `false`, and the console renders it as one. A malformed manifest is a well-typed `FleetManifest`, never a `TypeError`.

The one refusal is the spec version. No `spec_version`, or one that is not `fleet/v1`, yields `{ manifest: null, reason }`. The console says "this is not a manifest I understand" rather than rendering an empty table somebody could dispatch against. A missing file is reported the same way, not thrown: a repository without a fleet is a normal state (decision D9, again).

The wrapped `summary:` that `wtd fleet adopt` writes is why `parseYamlSubset` learned to fold plain-scalar continuation lines; the irony-works manifest is checked in verbatim as `src/test/fixtures/workspace/fleet.manifest.yml` and the suite asserts that sentence parses whole.

## The gate

`evaluateFleetGates(mode, input)` is `governance/approval.ts` with a different vocabulary and the same three properties: pure, fixed order, and a master gate nothing overrides.

```
noWorkspace, dispatchDisabled, noCredential, manifestAbsent,
laneUnknown, laneHasNoSwitch (toggle), laneNotDispatchable (dispatch), guardrailViolation
```

`dispatchDisabled` is `zer0Cms.fleet.enabled` AND `zer0Cms.fleet.dispatchAllow`. There is no `force` flag anywhere in this directory; the manifest cannot set either; and `dispatchAllow` is read from the VS Code **settings** layer alone (`settingsFleetDispatchAllow()` in `src/config.ts`), so a `zer0.json` arriving with a cloned repository cannot arm it — the same reasoning that keeps `zer0.json` from arming the MCP publish flag.

`guardrailViolation` refuses to arm or dispatch a lane whose own manifest says `never_merges: false` or `writes_directly_to_default_branch: true`. Those are the two things the fleet doctrine says an agent never does; a lane admitting to either is for a person to run by hand with their eyes open, not from a button. A guardrail left `null` is an absence, not a violation.

`FleetBlocker` is its own type rather than `Blocker` because `kind` is a different closed union. The shape is the same `{ kind, message }`, the webview's `BlockerView` renders both, and declaring a second `Blocker` would make the core barrel ambiguous.

## The network, declared before it is used

`FLEET_READS` (three `GET`s: a variable, a workflow's newest run, the default branch) and `FLEET_WRITES` (`PATCH`/`POST` a variable, `POST` a dispatch) are the whole surface, in the style of `analytics/analytics.ts`'s `MEMBER_READS`. `fleetSurfaceIsRepoScopedOnly` asserts every path sits under `/repos/{owner}/{repo}`, names no person-shaped resource, and that every `returns` sentence says "the repository's own". `githubFleetClient` checks each real request against the same plan before opening a socket, and `fleet.test.ts` checks it again from the outside with an intercepting `fetch`.

The client stores nothing. `token()` is called per request and its result goes straight into one `Authorization` header. There is no retry, no pagination and no cache: one variable and one run per lane, on demand, for a person looking at the screen.

**Decision D11**, stated where it is enforced: this extension promises no network and no auth on activation (`src/extension.ts`). The Fleet console keeps that promise by doing network only from an explicit user action, through the `fetch` the shell injects here, and never at activation. See `src/commands/fleet.ts`.

## What is deliberately absent

No multi-repo roster, no facts or audit engines, no write tool for the MCP server. Slice 2 brings those from the hub's `@bamr87/fleet-engines` package; this directory is one repository's lanes and two human-gated verbs.

## Tests

`src/test/fleet.test.ts`, plain Node: the verbatim irony-works fixture parses (wrapped summary whole), a malformed manifest coerces without throwing, the blocker order in both modes, the surface guard (and that a members call fails it), and every request the client makes lands in the plan.
