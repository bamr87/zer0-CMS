# `src/core/fleet` — the Fleet console's pure half

A fleet of repositories' AI lanes, read from each one's `fleet.manifest.yml`, and the gate in front of the five things a person can do to one: flip its `*_ENABLED` switch, dispatch it once, re-run its newest failure, cancel what is in flight, or register its workflow enabled or disabled. Pure Node, like everything under `src/core/` — no `vscode`, no filesystem in the gate, and the network behind an injected `fetch`.

| File | What it owns |
|---|---|
| `manifest.ts` | `readFleetManifest` / `parseFleetManifest` / `coerceFleetManifest`: `fleet.manifest.yml` (spec `fleet/v1`, from bamr87/wtd `docs/FLEET-SPEC.md`) → the `FleetManifest` shape declared in `shared/types.ts`. Plus the small readers: `laneById`, `isDispatchable`, `workflowFileOf`, `describeTriggers`, `describeGuardrails`. |
| `fleet.ts` | The domain. `FleetLaneState` (a lane plus what the repository says about it), `switchValueOf`, `nextSwitchValue`, `buildLaneStates`, and **`evaluateFleetGates`** — the gate, six modes and sixteen blocker kinds. |
| `github.ts` | The GitHub surface **as data** (`FLEET_READS` 8, `FLEET_WRITES` 7, `FLEET_PLAN` 15), the two guards `fleetSurfaceIsRepoScopedOnly` and `fleetPlanHasNoMergeVerbs`, `describeFleetPlan`, and `githubFleetClient` — a fourteen-member `FleetClient` over an injected `fetch` that refuses any request not in the plan. |
| `roster.ts` | Which repositories the console is operating: `parseProjectsRegistry` (the hub's `_data/projects.yml`), `parseRosterSetting` (`zer0Cms.fleet.roster`, with its rejects named), `rosterSlugOf`, and `mergeFleetRoster` — `workspace` > `settings` > `hub`, deduped case-insensitively. |
| `pulls.ts` | `coercePull`, `prStage` (transcribed from the two auto-merge workflows running in production today) and `attributePulls` — pull requests joined to the lanes that opened them, with whatever cannot be attributed kept **visible** rather than guessed onto a plausible lane. |
| `cost.ts` | `parseUsageSummary` / `costByLane` over each repository's committed `_data/ai_usage/summary.yml`. Absent is `null` and a lane with no ledger row is **absent from the result**, never a `LaneCost` full of zeroes. |
| `policy.ts` | `mergePolicyOf` / `describeMergePolicy` — the three variables that decide what merges without a human, reported and never written. There is no writer here or anywhere else. |
| `client.ts` | `engineClientOver` — the console's `FleetClient` presented as the engines' `GithubClient`: twelve members realised, ten (every write to a repository, both secret calls, `preflight`, `listRunJobs`, `createIssue`) throwing `405` before any fetch happens. |
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
laneUnknown, laneHasNoSwitch (toggle), laneNotDispatchable (dispatch),
noRetryableRun (rerun), noRunInProgress (cancel), workflowUnknown (toggleWorkflow),
guardrailViolation
```

Sixteen kinds exist; the eight original ones keep their positions, and the five scaffold kinds and the three run kinds were **appended** rather than inserted, because the order is a contract a test pins and a person reading a refusal should see the same first reason they saw yesterday. Scaffolding runs its own list — four of the checks above are actively wrong for it, since writing a lane's files needs no GitHub credential and a repository with no manifest is precisely where a first lane gets written.

The three run checks read `input.live`, which is what one Refresh actually read. **An absent `live` is not the same as an empty one**: nobody has refreshed, which is a different answer from "there is nothing to re-run", and the shell appends a sentence naming Refresh so the refusal cannot be misread as "this lane has never failed". `workflowUnknown` exists for the same reason — a file can sit in `.github/workflows/` and be unknown to the Actions API until its first run, and saying so beats a 404.

`dispatchDisabled` is `zer0Cms.fleet.enabled` AND `zer0Cms.fleet.dispatchAllow`. There is no `force` flag anywhere in this directory; the manifest cannot set either; and `dispatchAllow` is read from the VS Code **settings** layer alone (`settingsFleetDispatchAllow()` in `src/config.ts`), so a `zer0.json` arriving with a cloned repository cannot arm it — the same reasoning that keeps `zer0.json` from arming the MCP publish flag.

`guardrailViolation` refuses to arm or dispatch a lane whose own manifest says `never_merges: false` or `writes_directly_to_default_branch: true`. Those are the two things the fleet doctrine says an agent never does; a lane admitting to either is for a person to run by hand with their eyes open, not from a button. A guardrail left `null` is an absence, not a violation.

`FleetBlocker` is its own type rather than `Blocker` because `kind` is a different closed union. The shape is the same `{ kind, message }`, the webview's `BlockerView` renders both, and declaring a second `Blocker` would make the core barrel ambiguous.

## The network, declared before it is used

`FLEET_READS` (eight `GET`s: one variable, every variable, a workflow's newest run, every workflow with its state, a bounded page of recent runs, a bounded page of open pull requests, a file's contents, the default branch) and `FLEET_WRITES` (`PATCH`/`POST` a variable, `POST` a dispatch, `POST` a re-run, `POST` a cancel, `PUT` enable, `PUT` disable) are the whole surface, in the style of `analytics/analytics.ts`'s `MEMBER_READS`. Every call carries a `returns` sentence saying what comes back, and the page sizes are written into the path templates rather than passed as parameters — which is what makes `requestIsInPlan` refuse a request for a bigger page before a socket opens, instead of a comment asking politely for restraint.

**Two guards, because the plan grew and a prefix check is not a boundary.** `fleetSurfaceIsRepoScopedOnly` matches each path against an explicit `FLEET_SUBROOTS` allow-list, **whole segment**: `/repos/{owner}/{repo}` is also the prefix of `/issues`, `/releases`, `/collaborators`, `/hooks`, `/keys` and `/actions/secrets`, so the old `startsWith` read like a fence and was not one. It additionally refuses any person-shaped path and requires every `returns` to say "the repository's own" — somebody adding a member call has to write a sentence that cannot honestly be written. `fleetPlanHasNoMergeVerbs` refuses `/merge`, `/reviews`, `/update-branch`, `/actions/secrets`, `/collaborators`, every `DELETE`, and every non-`GET` touching `/labels`: reading the labels on a pull request is how `prStage` works, writing one is how a review decision gets made, and that belongs to a person. Path traversal is refused before a URL is built — `{+path}` spans separators, so a `.`/`..` segment would otherwise be normalized by `fetch` into an endpoint the plan never declared.

The client stores nothing. `token()` is called per request and its result goes straight into one `Authorization` header. There is no retry and no cache, and pagination is one bounded page per list — a screenful, because the console shows a person a screen.

**`listVariables()` returns `null`, not `[]`, on 403/404, and that tristate is load-bearing.** An empty list means the repository really has no variables, so every switch is genuinely `unset` and every lane is genuinely off. `null` means nobody could ask. A console that rendered the second as the first would draw a running lane as a stopped one, which is the single most expensive lie this surface could tell.

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

## What this console will never do

It never merges a pull request, approves one, requests changes on one, closes one, or adds or removes a label. It never reads or writes an Actions secret. It never deletes anything. It never asks what a person's credential is allowed to do (`preflight` is refused, and `login` is `''`, because `/user` is a question about a person and this plan is about a repository). It never writes a file into a repository, opens a branch or a pull request, or files an issue — filing is triage's job, in its own lane, under its own review. It never edits a workflow file GitFactory compiled, and it never writes a manifest field it derived rather than read.

None of those is an omission waiting to be filled in. `fleetPlanHasNoMergeVerbs` and `ENGINE_CLIENT_REFUSED` are how they stay a boundary, and `fleet.test.ts` asserts both from the outside.

## What is deliberately absent

No write tool for the MCP server, and no per-run drill-down: `listRunJobs` is refused because a job list is one more request per row on a screen whose whole budget is four per repository. `mergeable` is never computed — GitHub's list endpoint omits it and asking per pull request would cost a call each, so `FleetPull` carries no merge state at all and the console renders it as unknown. A grey cell that says "unknown" is honest; a green one that guessed is not.

## Tests

`src/test/fleet.test.ts`, plain Node: the verbatim irony-works fixture parses (wrapped summary whole), a malformed manifest coerces without throwing, the blocker order in both modes, the surface guard (and that a members call fails it), and every request the client makes lands in the plan.

`src/test/engines.test.ts`, 19 tests over `src/test/fixtures/fleet/` — 33 verbatim files from seven repositories, each row of provenance in that directory's `FIXTURE-SOURCES.md`. The layering tests grep the tree and read esbuild's metafile; the reality tests run the engines over real sister-repo workflows. Goldens live beside their generator at `src/test/fixtures/golden/engines/` with an `ENGINES_VERSION` sidecar: regenerate with

```bash
node src/test/fixtures/golden/engines/generate.mjs
```

and read the diff. Never hand-edit a golden, and never edit a fixture to make one nicer — re-copy it from the origin named in `FIXTURE-SOURCES.md`.
