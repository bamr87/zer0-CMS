# `src/core/fleet` — the Fleet console's pure half

This repository's AI lanes, read from its `fleet.manifest.yml`, and the gate in front of the two things a person can do to one: flip its `*_ENABLED` switch, or dispatch it once. Pure Node, like everything under `src/core/` — no `vscode`, no filesystem in the gate, and the network behind an injected `fetch`.

| File | What it owns |
|---|---|
| `manifest.ts` | `readFleetManifest` / `parseFleetManifest` / `coerceFleetManifest`: `fleet.manifest.yml` (spec `fleet/v1`, from bamr87/wtd `docs/FLEET-SPEC.md`) → the `FleetManifest` shape declared in `shared/types.ts`. Plus the small readers: `laneById`, `isDispatchable`, `workflowFileOf`, `describeTriggers`, `describeGuardrails`. |
| `fleet.ts` | The domain. `FleetLaneState` (a lane plus what the repository says about it), `switchValueOf`, `nextSwitchValue`, `buildLaneStates`, and **`evaluateFleetGates`** — the gate. |
| `github.ts` | The GitHub surface **as data** (`FLEET_READS`, `FLEET_WRITES`, `FLEET_PLAN`), the guard `fleetSurfaceIsRepoScopedOnly`, `describeFleetPlan`, and `githubFleetClient` — a `FleetClient` over an injected `fetch` that refuses any request not in the plan. |
| `engines.ts` | **The seam.** The only file in the repository that imports `@bamr87/fleet-engines`, re-exporting what the console uses under non-colliding names, plus `ENGINES_VERSION`. Never re-exported through the core barrel. |
| `adapters.ts` | The boundary conversions — `toEngineLane` / `fromEngineLane` / `toEngineManifest` with their `LaneLoss` record, `runnerShapeOf`, `manifestDrift`, `runsToFactoryRuns`. `import type` only, so it is barrel-safe. |
| `registry.ts` | A tolerant `harness-registry/v1` reader over the hub's `_data/harness_registry.yml`, limited to the fields `docs/HARNESS-OPS.md` names stable, refusing a foreign marker, carrying its blind spot as data. |
| `handoff.ts` | `gitFactoryLink()` — one URL to GitFactory, asserted **parseable by** that app's own `parseDeepLink`. |
| `inspect.ts` | `inspectWorkspaceFleet()` — facts, an audit grade, drift rows and the unmatched sets for one repository, computed entirely from files on disk with no network at all. |

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

## The engines, and the one door they come through

`@bamr87/fleet-engines` is the hub's copy of the fleet's pure engines — workflow facts, the 15-rule audit, run metrics, the harness scorecard, the hub reader, the roster helpers, the manifest emitter. GitFactory consumes the same package. This console consumes it rather than re-porting it (decision **D14**), as an exact-pinned **devDependency** bundled into `dist/extension.js` alone. `dependencies` is still `{}` and still will be.

**`engines.ts` is the only file that imports it, and the barrel never re-exports `engines.ts`.** Both halves are load-bearing. The package exports `FleetLane`, `FleetManifest`, `parseFleetManifest`, `LANE_KINDS` and `RosterEntry`, all of which this directory already declares with different shapes, so a star export makes the barrel ambiguous. And the barrel is what `src/mcp/` imports through, while `dist/mcp-server.js` is built with `external: []` and an **empty** bare-import allow-list — esbuild resolves the whole import graph before it tree-shakes, so "the MCP server never calls it" is not a defence. `eslint.config.mjs` forbids the seam under `src/mcp/**`; `engines.test.ts` greps `src/` for a second importer and reads esbuild's metafile to prove the MCP bundle carries no package file.

Everything else crosses through `adapters.ts`, which imports the package's **types** only. `inspect.ts` needs the engines at runtime and is on the barrel, so it takes them as data (`io.engines`) — the same reasoning as the injected `fetch` in `github.ts`, and the reason a process with no engines simply cannot inspect rather than reporting a grade it computed with half a rulebook.

## Why we still keep our own parser

Decision **D-A**, and the fixtures make the case better than the prose does. `manifest.ts` refuses a foreign `spec_version` and keeps the tristate; the package's parser defaults an absent `never_merges` to `true` and answers an unreadable file with an empty manifest whose `skipped` count is **zero**, so a caller cannot tell it failed.

That is not hypothetical. `wtd fleet adopt` wraps a single-quoted scalar at column 80 and writes the continuation at column 0, outside the block's indentation:

```yaml
  purpose: 'Preferred Claude auth (house convention: OAuth first). Produced by
`claude setup-token`.'
```

**Four of the seven committed manifests in this fleet** — it-journey, zer0-mistakes, ai-world-view and this repository's own — are invalid YAML for exactly that reason. The `yaml` package throws; the package's parser returns nothing and says nothing; `parseYamlSubset` reads all four. `engines.test.ts` pins both halves: parity where the package can read, and the disagreement where it cannot.

## What the conversion loses, out loud

`toEngineLane` maps `neverMerges: null → never_merges: true`, because the package's shape has no third state — **and returns a `LaneLoss` saying so**. Three more things the engine lane cannot hold are recorded the same way: `writes_directly_to_default_branch` (no field), a `kind` outside the package's closed vocabulary (`fleet/v1` leaves `kind` free), and a schedule trigger whose cron the manifest omitted. At manifest level the token contract, the metering block and the agent/skill rosters have no home either.

The rule is: silence is never upgraded to a promise without a paper trail. A caller that ignores the losses gets the package's optimistic default; a caller that reads them can put "the manifest is silent" on screen next to the Dispatch button, which is a different sentence from "it never merges".

## Drift is shown, never written

`manifestDrift(lane, facts)` returns the axes on which a lane's committed description disagrees with the workflow file it names. The console **shows** those rows; it never edits the manifest to match, because this console never writes a manifest field it derived rather than read — that is `wtd`'s job (see `docs/ARCHITECTURE.md`, "The contract map").

Rows the real fixtures contain today, each pinned by a test:

- **lifehacker `content-factory`** declares `opens_pull_requests: false`; the workflow's observed sinks include `pr`. It opens pull requests. That is the lane's whole purpose.
- **ai-world-view `grow-lineage`** names `ORCHESTRATE_ENABLED`; the workflow reads no repository variable at all. The gate the manifest promises does not exist in the file that would enforce it.
- **it-journey `cms-daily-loop`** is recorded as ungated; the workflow reads two switches.
- **lifehacker `explore`** records a daily cron the workflow has **commented out**. The row says "commented out", not "no schedule", because the difference is the story.

One honest wart: `DriftKind` (in `shared/types.ts`) names five axes and none of them is `guardrails`, so a guardrail the workflow contradicts is filed under `implementation` with both sides quoted verbatim. A sixth kind would be the better answer.

## What is deliberately absent

No multi-repo roster and no write tool for the MCP server — slice 2 brings the first. `harnessHealth`, `readHub` and the metrics engines are re-exported by the seam and not yet called by anything in this directory; PR5's Monitor tab is where they land.

## Tests

`src/test/fleet.test.ts`, plain Node: the verbatim irony-works fixture parses (wrapped summary whole), a malformed manifest coerces without throwing, the blocker order in both modes, the surface guard (and that a members call fails it), and every request the client makes lands in the plan.

`src/test/engines.test.ts`, 19 tests over `src/test/fixtures/fleet/` — 33 verbatim files from seven repositories, each row of provenance in that directory's `FIXTURE-SOURCES.md`. The layering tests grep the tree and read esbuild's metafile; the reality tests run the engines over real sister-repo workflows. Goldens live beside their generator at `src/test/fixtures/golden/engines/` with an `ENGINES_VERSION` sidecar: regenerate with

```bash
node src/test/fixtures/golden/engines/generate.mjs
```

and read the diff. Never hand-edit a golden, and never edit a fixture to make one nicer — re-copy it from the origin named in `FIXTURE-SOURCES.md`.
