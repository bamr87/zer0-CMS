# `src/core/harness` — one vocabulary for the editor agent and the fleet's CI

This extension runs an agent in the editor through the Claude Agent SDK. The fleet runs the same roles in CI through the hub's `claude-run` action, which reads the repository's `_data/ai.yml` and its `.claude/agents/<name>.md`. Before this package the two shared **no vocabulary at all**: the editor did not know the repository's agents, did not read its AI configuration, did not attach this extension's own MCP server, and defaulted to a model the fleet does not use. "Run this as the `grow-lifehacker` role" was possible in CI and impossible in the editor, and the two disagreed about which model would answer.

The fix is one resolved value and two projections. `resolveHarnessProfile` is the only place that decides; `toSdkOptions` is the editor's view of that decision and `toRunnerInvocation` / `toAiLaneWith` are CI's. Two projections of one value cannot drift the way two configurations can.

| File | What it is |
|---|---|
| `agents.ts` | `.claude/agents/<name>.md` → `AgentRecord`. Also `HarnessIo`, the two-method injected filesystem every reader here takes. |
| `skills.ts` | `.claude/skills/<name>/SKILL.md` → `SkillRecord`, plus the two skill counts that disagree about `_shared/`. |
| `aiConfig.ts` | `_data/ai.yml` → `AiConfig`. The path comes from `zer0Cms.cms.aiConfigPath`, never a literal. |
| `profile.ts` | The join, the model precedence, the permission-mode clamp, and the three projections. |
| `metering.ts` | One run's cost, as JSONL in the shape `scripts/ai/usage.rb` writes, outside the checkout by default. |
| `workflows.ts` | `.github/workflows/*.yml` → `WorkflowRecord`: the runner shape, the switch and where it lives, the crons that are live and the ones that are parked. |
| `derive.ts` | `wtd fleet adopt` ported to TypeScript, used only to AGREE with a committed manifest — never to overwrite one. |
| `joins.ts` | The six edges of the lane join, and every finding a broken one produces. |
| `ledger.ts` | `_data/ai_usage/` → `LedgerSummary`, or `null` for the five repositories that meter nothing. |
| `inventory.ts` | `readHarnessInventory` — all seven artefacts, joined, over the injected `HarnessIo`. |

Everything here is pure: no `fs`, no `vscode`, no network. The readers take their I/O as a parameter, which is why the same code serves the extension host, the bundled MCP server, and a test over a fixture directory. `src/commands/agent.ts` supplies the real filesystem (`workspaceHarnessIo`) and the MCP server spec; `src/agent/agentPanel.ts` resolves a profile per run.

## The model precedence, and why it mirrors the runner's

The hub's `run.sh` resolves a model as `--model` > `AI_MODEL` > `<repo>/_data/ai.yml` > a built-in default. Here that is **settings > `zer0.json` > `_data/ai.yml` > the built-in default**, and the profile records `modelSource` — *which layer answered* — so a panel can say "inherited from the repository" rather than showing a bare string.

The layer that matters is the third one. `cfg.agent.model` is already the merged three-layer answer, so it can only speak for `zer0.json` once the settings layer has been asked separately (through `inspect()`, which returns only what a person actually set) **and** the manifest default has been excluded. A merged value that equals the built-in default is the default — not a choice anybody made — so it does not shadow the repository's own file. That is what makes `zer0Cms.agent.model` mean *inherit* when it is left alone, and it is why a repository with an `_data/ai.yml` stops disagreeing with its own CI.

`zer0Cms.agent.model`'s manifest default should be `""` rather than a hard-coded model id, so that the intent is visible in the settings UI as well as in this behaviour. Until it is, one edge stays imprecise: a `zer0.json` that explicitly names the *same* id as the built-in default is attributed to `default` rather than `zer0.json`. Nothing resolves differently; only the label does.

## `settingSources` — the decision, and why it defaults to nothing

`settingSources` tells the SDK which settings files to load. `[]` means none at all. This package defaults to `[]`, and loads anything only when the workspace is **trusted** *and* the person **opted in for that run**.

The reason is `project`: `.claude/settings.json` arrives with the checkout, like `zer0.json` and `.mcp.json` do, and it can name **hooks** — command lines that run under the person's own credential. That is a fifth execution vector wearing a configuration file's clothes, and it is exactly the class of thing Workspace Trust exists to gate (decision D13). Nothing about cloning a repository and opening it is consent to run its hooks.

Two things it is *not* protecting against, both measured rather than assumed (see the table below): a project `permissions.allow` rule does not skip `canUseTool`, and a project `permissions.defaultMode: acceptEdits` is dropped by the CLI's own trust filter before it can escalate anything. The gate is about hooks.

When a person does opt in, all three sources load (`user`, `project`, `local`), because "run it the way my CLI would" is what the request means and the person's own two tiers are theirs already. The gate exists for the middle one. `AgentPanel.start()` re-asks modally before reading anything, because the composer in that panel reaches `start()` without passing through a command — the surface is a courtesy, the function is the gate.

## `permissionMode` is clamped, and that is an empirical finding

Measured against `@anthropic-ai/claude-agent-sdk` 0.3.220 on 2026-09-09, with a one-turn run in a temporary directory that asks for a `Write`:

| configuration | did `canUseTool` see the `Write`? | was the file written? |
|---|---|---|
| `permissionMode: 'default'` | **yes** | yes, after the allow |
| `permissionMode: 'acceptEdits'` | **no — never called at all** | yes |
| project `.claude/settings.json` with `permissions.allow: ['Write']`, `settingSources: ['project']` | yes | yes |
| project `.claude/settings.json` with `permissions.defaultMode: 'acceptEdits'`, `settingSources: ['project']` | yes | yes |

So exactly one configuration bypasses decision D10 — and it was a value this extension's own setting offered. `resolveHarnessProfile` therefore **clamps** any mode that can skip the card down to `default`, and `profileWarnings` returns a line the transcript prints before the first token, so a person is told that the mode they configured would have skipped the card and that this run does not. The manifest enum should be narrowed to `default` and `plan` for the same reason; the clamp lives here as well because a `zer0.json` arriving with a cloned repository can name a mode too, and a gate that exists only in the settings UI is not a gate.

The last two rows are worth keeping written down: they are the SDK behaving *better* than the pessimistic assumption, and re-deriving them later would cost another set of live runs.

## The MCP attachment, and which tools skip the card

A run gets this extension's own MCP server through `mcpServers`, spawned as `node dist/mcp-server.js` with an `env` carrying only which project file to read. Neither `ZER0_CMS_MCP_ALLOW_PUBLISH` nor `ZER0_CMS_MCP_ALLOW_EXEC` is set, so the writing tools refuse on their own terms.

`strictMcpConfig: true` is always emitted: the servers this profile names are the only ones the run gets, so a `.mcp.json` sitting in a cloned repository cannot add one.

`profile.readOnlyTools` is the list the approval gate consults, and it is the base six plus — **only when the server is actually attached** — the eight `mcp__zer0-cms__*` tools that cannot change anything: `zer0_status`, `zer0_list_content`, `zer0_get_content`, `zer0_preview`, `zer0_portfolio`, `zer0_media`, `zer0_fleet_status`, `zer0_audit`. The five that are absent all write, so they fail closed onto the card: `zer0_draft`, `zer0_publish`, `zer0_worklist`, `zer0_ingest`, `zer0_contract`. This is a **list, not an allow-rule** — it is never passed to the SDK as `allowedTools`, because a tool matched by an SDK-side allow rule never reaches `canUseTool`, and `canUseTool` is the gate (D10).

`toSdkOptions` also emits an explicit `env`. The SDK replaces the child environment wholesale when that field is set, so it starts from the host's and *deletes* `ZER0_CMS_MCP_ALLOW_PUBLISH` and `ZER0_CMS_MCP_ALLOW_SCAFFOLD`: an editor run must not be armed by whatever armed something else in this window.

## The CI projection differs in exactly one field, on purpose

`toRunnerInvocation` renders the same run as `scripts/ai/run.sh --prompt … --agent … --tools … --system … --max-turns …`, and `toAiLaneWith` renders the `with:` block of a caller of the hub's reusable `ai-lane.yml`. Both emit only what the profile actually knows: `lane`, `switch` and `prompt` are the author's to fill, because inventing them would be this console writing a workflow field it derived rather than read.

Two deliberate asymmetries:

- **`--model` is omitted when the model was inherited.** If it came from `_data/ai.yml` (or is the built-in default), CI reads the same file, and pinning the value into a workflow would freeze what the site can change in one place. It is emitted only for an editor-side override.
- **`system` is the role's sentence, not the editor's.** `systemAppend` says the user reviews every edit in an approval card and that the run must not open a pull request. Both are true in the editor and false in a lane, whose job is usually to open one. `ciSystemFor` emits the role's own description plus the fleet's universal "Never merge." instead — which is the shape every `system:` input in the fleet already has.

## Agent dialects — descriptive, never gating

`AgentRecord.dialect` says which house's conventions a file is written in. **Structure first, name second**: an agent that files bugs upstream mentions two sites and belongs to the one whose conventions it was written in. Ordered, first match wins:

1. `<example>` blocks in the description, or a `color:` key — **bash-365**. Six of six there, none anywhere else.
2. A bolded `**Guardrails:**` citation of the shared quarantine doc, a "USE WHEN … DO NOT USE FOR …" description, or a `model:` pin — **zer0-mistakes**. Sixteen of seventeen carry the bolded line.
3. An unbolded `Guardrails: …quarantine.md — all sections apply.` line — **it-journey**. Ten of ten.
4. `## Hard rules` or `## The shape of a good run`, with the quarantine rules restated in prose rather than cited — **lifehacker**.
5. Otherwise whichever house the file names most often; otherwise `unknown`, which is a real answer for the hub's own house-neutral template.

Measured over all fifty-two agent files in the four repositories: **51 of 52**. The one that classifies elsewhere is `zer0-mistakes/.claude/agents/agent-auditor.md`, which *is* the hub's template rendered into that repository and reads as it-journey's dialect — a fact about the fleet, not a defect in the reader.

## `_shared/` is not a skill, and the two counters disagree

`.claude/skills/_shared/` holds `quarantine.md`, the guardrails every agent cites for reading untrusted text. It has no `SKILL.md`, no name and no trigger, so it is not a skill. lifehacker's `scripts/ci/lint_agents.rb` excludes it from its skill count; `wtd fleet adopt`, which counts directories, includes it. For lifehacker.dev that is 16 against 17 — one repository, two numbers, both correct under their own definition.

`skillCountsFor` therefore reports **both**, and nothing in this console silently picks a winner. A scorecard showing one number would be telling a repository that its own lint is wrong.

## Metering

`usageRecordFrom` projects the SDK's `result` message onto the record shape `lifehacker.dev/scripts/ai/usage.rb` writes — `cost_usd`, `cost_source`, `num_turns`, `session_id`, `tokens.cache_read` — so one reader adds up an editor run and a lane run. Two fields are deliberately identifiable: `source` is `zer0-cms-agent` and `auth` is `sdk`, values the CI writer's vocabulary does not use, so a row from this console can never be mistaken for a lane's.

An absent cost is `null`, never `0`: a zero adds up and a `null` does not. Keys are sorted on the way out, which the Ruby writer does not do — an append-only file nobody diffs does not need it, and a file two windows may write does.

The default path is **outside the checkout**, under the extension's global storage (`defaultUsageLedgerPath`). An editor run is not the repository's business unless somebody says it is, and committing a personal token ledger into a content repository is a decision nobody makes by installing an extension.


## The inventory — the join nothing else in the fleet makes

An agent file, a skill, a workflow, a manifest lane, a repository variable, a token and a line in a spend ledger are **seven files describing one lane**. Nothing joins them. `lint_agents.rb` checks one edge (does `agent: X` resolve?), `audit.rb` checks another against a hard-coded table of one repository's filenames, `wtd fleet audit` checks the manifest against three spec rules — and a person holds the rest in their head. Which is fine until the head in question is somebody else's.

`readHarnessInventory` reads all seven and reports the joins. The more useful half of what it reports is where they **disagree**.

| File | What it is |
|---|---|
| `workflows.ts` | `.github/workflows/*.yml` → `WorkflowRecord`. Regex line scans over `parseYamlSubset`; engines-free by construction. |
| `derive.ts` | A TypeScript port of `wtd fleet adopt`, used **only to agree**. Never overwrites a committed manifest. |
| `joins.ts` | The six edges, and every `HarnessFinding` a broken one produces. Records in, records out — no I/O, no clock. |
| `ledger.ts` | `_data/ai_usage/{ledger.jsonl,summary.yml}` → `LedgerSummary`, or `null`. |
| `inventory.ts` | `readHarnessInventory(root, io, opts)` — the whole thing, over the injected `HarnessIo`. |

### Why a second workflow reader, when `fleet/inspect.ts` exists

`src/core/fleet/inspect.ts` already runs `@bamr87/fleet-engines`' `extractFacts` and its fifteen audit rules over a workspace's workflows, with the engines **injected as data** so the module stays type-only with respect to the package. That injection is what lets it live in the core barrel at all — and it is also why it cannot serve here. `dist/mcp-server.js` is built with an empty bare-import allow-list (decision D14), so a process that has no engines cannot inspect; `zer0_fleet_status` reads the local manifest and says the rest is unknown, which is the honest outcome.

The inventory has to work in that process. So `scanWorkflow` is a second **reader** — but not a second **answer**:

- Four of its fields have no counterpart in the engines at all: `runnerShape` (seven values where `fleet/v1`'s `harness` has five, because the hub composite and a bare `claude -p` are both `claude-cli` upstream), `switchHost`, `switchPolarity`, and `dispatchBypassesSwitch`.
- Where both speak — which lane a file is — the rule is written down **once**, in `joins.ts:laneForWorkflow`, as the same rule `attachLanes` applies (`implementation === path`, else `id === basename stem`). One rule, two implementations, and a test that pins it so they cannot become two answers.

If the layering ever changes and the MCP bundle can hold the engines, this reader should be retired rather than kept in sync.

### The nine finding kinds, and the guard on each

The rule about rules is: **a finding that fires on a healthy repository is a wrong rule, not a discovery.** Five of the guards below exist because an earlier draft fired on healthy wiring and had to be told why it was wrong; each of those five names the case that taught it.

| Finding | Fires when | Guard |
|---|---|---|
| `dangling-agent` (error) | a workflow names `agent: X` / `--agent X` / `X subagent` and `.claude/agents/X.md` is absent | `${{ }}` expressions are skipped (no reader can resolve a matrix role, and `lint_agents.rb` skips them too); **`--agent` on a metering line is skipped** — `usage.rb ingest-execution-log … --agent claude-mention` labels a ledger row, and a `claude-code-action` lane's role has no agent file by construction |
| `dangling-skill` (warning) | a prompt says `Use the X skill` / `**X** skill` and `.claude/skills/X/SKILL.md` is absent | only where the repository **has** a `.claude/skills/` directory; `X subagent` is read as an *agent* reference, not a skill; a stoplist rejects `the`, `a`, `this` … because "Follow the skill in order:" named `the` |
| `dangling-skill` (info) | a skill nothing anywhere names | the reference test is the **loosest** available — parsed refs plus a substring scan of every workflow's raw text — because `readWorkflowSkillRefs` deliberately ignores slash-command mentions and a strict test would call a dozen live skills orphans |
| `agent-name-mismatch` (error) | front-matter `name` ≠ filename | none needed; Claude Code resolves `--agent` against the *filename*, so the role silently no-ops |
| `switch-hosted-elsewhere` (info) | the manifest's `switch` is not a `vars.` the lane's own workflow reads | `info`, and the message names the host when the file names one. It is prose, not a broken gate |
| `lane-without-workflow` (warning) | a manifest lane names a file that is not there | none needed |
| `workflow-without-lane` | a model-calling workflow no lane claims | only for `runnerShape !== 'none'`, so a CI workflow never fires; `info` (not `warning`) when the repository commits no manifest at all, because that is a normal state and not a failure (decision D9) |
| `token-presence-chain` (warning) | `secrets.X \|\| …` | read from **comment-stripped** text: lifehacker's migrated `content-scout.yml` documents the idiom it was moved off, and its own `lint_tokens.rb` skips comment lines for the same reason |
| `unmetered-model-call` (warning) | a model call outside the hub runner with no usage-report step | only where the repository **meters at all** (a ledger exists). A repository with no ledger has not failed to meter a lane; it has not adopted metering |
| `manifest-drift` (warning) | the derived lane and the committed one disagree | a guardrail the manifest never claimed (`null`) is a **silence**, not a disagreement; `description` is excluded because prose renames would bury the rows that matter |

Measured over all six sister repositories on 2026-09-09: 13 findings on lifehacker.dev (12 `token-presence-chain` — **exactly** the twelve workflows in its own `lint_tokens.rb` `MIGRATING` list — plus one genuinely human-invoked skill), 23 on it-journey, 7 on zer0-mistakes, 4 on ai-world-view, 2 on irony-works, 12 on bash-365. Zero `dangling-agent`, zero `agent-name-mismatch`, zero `manifest-drift` anywhere.

### The derivation agrees, and where it does not is a finding

Every committed `fleet.manifest.yml` in this fleet is `provenance: derived` — a Python script read the workflows and wrote the file. That makes the manifest a **cache of a derivation**, and a cache can go stale. `deriveLaneFromWorkflow` recomputes it from the same bytes, and across all six repositories it agrees with the committed manifest on **45 of 45 lanes** (17 lifehacker, 15 it-journey, 6 zer0-mistakes, 5 ai-world-view, 2 irony-works) on `kind`, `harness`, `implementation`, `switch`, `uses_tokens`, `triggers`, and every guardrail either side claimed.

That parity is what makes a *dis*agreement mean something. It also cost three bug-for-bug reproductions:

- **Crons are read from raw text, comments included.** That is why lifehacker's manifest says the `explore` lane runs at `23 6 * * *` when that cron has been commented out for months. `scanWorkflow` records the same line as a `dormantCron` — a commented-out schedule is not a schedule — and the two fields disagreeing is the point.
- **`harness` collapses four runner shapes into one.** `claude-cli` covers the hub composite, a bare `claude -p`, and `scripts/ai/run.sh`, because `fleet/v1` has no name for the composite.
- **The switch is picked by name similarity** — the first switch in the *sorted* list whose squashed name starts with the first eight squashed characters of the filename stem, else the first mentioned anywhere including comments. Eight is upstream's number.

One divergence is deliberate: **`adopt.py` misses an `ai-lane.yml@` caller.** None of its four harness patterns matches `uses: bamr87/bamr87/.github/workflows/ai-lane.yml@main`, so such a lane gets `Harness.NONE` and is dropped from the manifest **entirely** — a lane that runs an agent every Monday, invisible to the fleet's own inventory. This port recognises the shape, and `upstreamWouldDropLane` reports the disagreement rather than hiding it.

Two more classes the derivation *cannot* see, both worth knowing before trusting a guardrail:

- **`opens_pull_requests: false` on lifehacker's `content-factory` lane is wrong, and both readers say so.** The lane opens one pull request per collection per day — but `gh pr create` is run by the *agent*, not by a command line in the file. Inference reads command lines; an agent's behaviour is not one. This is the single strongest argument for never writing a derived lane back over a committed one.
- **`adopt.py`'s raw-text fallback is not reproduced.** Its `_triggers` scans the whole file for `^\s*<event>:` when PyYAML cannot parse, and that pattern matches `issues: write` under `permissions:`. Copying it gave four lifehacker lanes a phantom `event issues` trigger — four drift rows against a manifest that was right. PyYAML parses every workflow in this fleet, so the fallback never ran upstream either; copying it would have been copying dead code and its bug.

### An empty manifest from a non-empty file is a finding, not an absence

Four of the seven committed manifests in this fleet are **not valid YAML**: `wtd fleet adopt` wraps a single-quoted scalar at column 80 and continues it at column 0, outside the block's indentation. The `yaml` package throws, and `@bamr87/fleet-engines`' parser answers with an **empty** manifest reporting **zero** skipped lanes — so a caller cannot tell it failed. This repository's own tolerant reader parses all seven, which is why `inventory.ts` uses it.

The posture outlives the parser: a manifest file that exists and yields no lanes carries its `reason` through. "This repository has no lanes" and "this repository's manifest would not parse" are different sentences, and nothing here may say the first when it means the second.

### The ledger: `null`, never zero

Exactly one repository in the fleet commits a usage ledger. `readLedger` returns `null` for the other five, and that is the whole design: a `0` adds up. A scorecard showing "spend: $0.00" for a repository with no ledger reports an absence as an achievement, and a fleet total that summed those zeros would be quietly wrong — the same rule decision D9 applies to a missing `.cms/`.

`byRole` and `byWorkflow` are computed from the ledger rows; the three window totals come from `summary.yml`, because those windows are relative to *its* `generated_at` and recomputing "the last seven days" against now would answer a different question than the site's own published page. `unit` is stated rather than assumed: these are API-equivalent dollars, and a subscription OAuth run has no marginal cost at all.

The join key that surprises: a ledger row's `workflow` is the workflow's **`name:`**, not its filename stem — the rows say `pipeline` and `Factory: Issue Factory 1`. A lane whose workflow was renamed loses its own history, which is a fact about the ledger rather than a defect in the reader.

## What this package will never do

It never calls a model, never opens a socket, and never spawns anything — it computes a description of a run, or of a repository, and hands it to something else. It never writes into the repository. It never emits `allowedTools`.

And it never repairs a mismatch it found. An agent whose `name` disagrees with its filename is *recorded* as a mismatch, because renaming it silently would hide the dangling reference `lint_agents.rb` exists to catch. A derived lane is never written over a committed one, because the committed file carries what inference cannot know. A `factory--*.yml` is never proposed for editing, because GitFactory compiles those from a blueprint and overwrites hand edits — which is why `generatedByGitFactory` is a field on the record rather than a warning in a comment.
