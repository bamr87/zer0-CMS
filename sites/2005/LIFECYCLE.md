# LIFECYCLE — grow → replant → consolidate

How a single seeded repository becomes a self-rotating **lineage** of knowledge bases, and how a
finished lineage collapses back into one consolidated repository. This document is the design
reference for the lifecycle layer; the machine-readable state lives in
[`lifecycle.yml`](lifecycle.yml), and the executable procedures live in
`.github/prompts/{replant,consolidate}.prompt.md` and `.github/skills/check-lifecycle/`.

## The full cycle

```
                ┌──────────────────────────── one repo, one generation ───────────────────────────┐
/genesis ──▶ grow tick 1 ──▶ grow tick 2 ──▶ grow tick 3 ──▶ /replant ─┬─▶ this repo: mature 🌳
                                                                       └─▶ successor repo: planted 🌱 ──▶ /genesis ──▶ grow …
                                                                                        (repeat)

2005 🌳 ─▶ 2006 🌳 ─▶ 2007 🌳 ─▶ 2008 🌳 ─▶ 2009 🌳 ─▶ 2010 🌳 ─▶ 2011 (7th member) ──▶ /consolidate ──▶ 2005-2011 📦
                                                                                          members archived, logs preserved
```

Three phases, each already a single command:

| Phase | Command | Trigger | What it does |
|---|---|---|---|
| **Grow** | `/grow` | every scheduled run while `generation_ticks < replant_after_ticks` | One normal growth tick (plan → content/structure → verify → record → publish). |
| **Replant** | `/replant` | `generation_ticks ≥ replant_after_ticks` (default **3**) | Finalizes + compacts this repo (mature), then spawns the successor repo for the next concept with **only the necessary context and files**. |
| **Consolidate** | `/consolidate` | lineage reaches `consolidate_at_members` (default **7**) | Merges all member repos into one repo named for the range (e.g. `2005-2011`), preserves every Evolution Log, archives the members. |
| **Distill** | `/distill` | lineage reaches `distill_at_members` (default **3**), once (`state.distilled_at` null) | One-time meta-review on the frontier model (`policy.models.distill`, default Fable 5): analyzes every member end-to-end, improves the cycle, and writes the **`seed-package/`** bootstrap kit — the bare minimum (seed template, lifecycle template, manifest of load-bearing framework files, configure-and-launch README) needed to spawn a similar-or-better lineage for **any** starting concept, e.g. "the year 1776" or "an organization". Improvements fan out via `pollinate`. |

## The pieces

### 1. `lifecycle.yml` — lifecycle state (per repo, carried down the lineage)

Splits into a hand-tunable `policy` block (`replant_after_ticks: 3`, `consolidate_at_members: 7`,
the natural-language `succession.rule`, the consolidation `naming_rule`/`layout`) and a
machine-maintained `state` block (`status`, `generation_ticks`, `origin`, and the full `lineage`
list). The lineage list is **append-and-carry-forward**: every spawn copies it into the successor
and appends the new member, so the newest repo always knows when the family hits 7. Subject-specific
values (years) live only here and in `seed.md` §1 — the framework itself stays concept-agnostic.

### 2. `check-lifecycle` skill — the gate

Step 0 of every tick. Counts `Tick N` entries in `seed.md` §8 since the last `Genesis`/`Replant`
entry (the Evolution Log is the source of truth; the YAML counter is reconciled to it), then
reports the phase: `grow`, `replant`, `consolidate`, or `dormant`. The Architect pipeline and the
scheduled workflow both obey this decision, so growth, rotation, and consolidation all flow through
the same entry point: another `/grow` invocation.

### 3. `/replant` — rotate the lineage

- **Part A — finalize in place**: settle structure, compact the roadmap (unfinished → Ideas),
  `sync-seed`, set `status: mature`, append a `### Replant` entry to the Evolution Log, publish.
  The repo keeps all its content — "compact" means *reducible to its seed*, not deleted.
- **Part B — spawn the successor**: derive the next subject from `succession.rule`
  (year + 1 for this family), create the repo, and plant **only**: `.github/` + `.claude/`
  (verbatim — concept-agnostic), `CLAUDE.md`, `.gitignore`, the grow workflow, and the
  carried-forward `lifecycle.yml` (ticks reset to 0). No content, no README, no seed inventories —
  the successor's first scheduled run detects the missing seed and runs `/genesis` itself.

### 4. `/consolidate` — close the family

Runs in the **newest** member (the only one whose lineage list is complete) once the family has 7.
Creates the range-named repo, moves each member under a top-level `<member-slug>/` directory with
its `seed.md` (Evolution Log verbatim) and `README.md`, writes a root seed/README spanning the
range, regenerates root structure (master INDEX/TIMELINE), publishes, then marks each member
`consolidated`, adds a pointer banner, and **archives** (never deletes) them. The consolidated repo
keeps the full framework, so it can continue growing cross-member content if scheduled.

### 5. `.github/workflows/grow.yml` — the heartbeat

A scheduled GitHub Action (daily cron + `workflow_dispatch`, concurrency-guarded) that runs
`anthropics/claude-code-action` with one instruction: *germinate if there's no seed, otherwise obey
check-lifecycle*. Because the workflow file is planted verbatim into every successor, the entire
lineage shares one autonomous heartbeat — no external orchestrator tracks the repos; each repo
carries its own state.

**Shepherd fallback** — pushing workflow files into a successor requires the PAT to have the
`workflow` scope (classic) / Workflows: write (fine-grained). If a successor was planted without
`grow.yml`, the lineage still runs: a **mature** repo's workflow does not stop at `dormant` — it
walks the lineage chain (each member's `lifecycle.yml` names its successor), clones the newest
growing member with `LIFECYCLE_PAT`, and executes that repo's tick inside the runner. The oldest
repo's heartbeat thereby drives the whole family until members carry their own.

**Framework propagation (pollination)** — workflow-level logic (tick model, auth fallback, tool
config) applies lineage-wide automatically because every shepherd-driven tick executes through the
driving repo's workflow and policy. For the planted framework files, the `pollinate` skill keeps
the lineage convergent **in both directions** with Claude-authored, auto-merged pull requests:

- **forward** — before each tick, any lineage member whose `.github/`/`.claude/`/`CLAUDE.md`/
  `LIFECYCLE.md` drifted from the driver gets a `pollinate/from-<driver>-<date>` PR, squash-merged
  automatically;
- **backward** — after each tick, framework changes the member made (e.g. `/evolve` learnings)
  come back to the driver as a `pollinate/from-<member>-<date>` PR; the next forward pass fans
  them out to every other member.

Content, `seed.md`, `README.md`, `ROADMAP.md`, and `lifecycle.yml` are never pollinated — they are
per-instance. Conflicting both-sides edits are left as open PRs for human review, never
force-merged. The PR trail is the lineage's learning ledger.

## Model policy (cost)

The tick model is a lifecycle policy knob: `lifecycle.policy.models.tick` (read by the workflow at
the start of every run; default `claude-sonnet-4-6`). Growth ticks are research, writing, and
mechanical structure work — squarely Sonnet-tier ($3/$15 per MTok vs Opus 4.8's $5/$25, a ~40%
per-token saving with no quality loss for this workload). Subagents (Curator/Architect) declare
`model: sonnet` in their `.claude/agents/` frontmatter and otherwise inherit the tick model; the
harness already routes its own trivial internal calls to Haiku 4.5 ($1/$5). Raise the knob to
`claude-opus-4-8` only for one-off hard interventions (e.g. untangling a botched consolidation),
then lower it back.

## Setup (once per owner account)

1. **Secrets** — in each repo (or as organization secrets so successors inherit them automatically):
   - `ANTHROPIC_API_KEY` — Claude API key used by `claude-code-action`.
   - `CLAUDE_CODE_OAUTH_TOKEN` — *optional fallback*: a Claude subscription OAuth token (run
     `claude setup-token` locally and paste the result). If the API-key run fails — credits
     exhausted, auth error — the workflow retries the tick once on the subscription. Ticks are
     lifecycle-gated, so a retried tick cannot double-apply.
   - `LIFECYCLE_PAT` — a PAT with `contents: write` on the family's repos **plus repository
     creation and archive** rights on the owner org (classic PAT: `repo` scope; fine-grained:
     Contents write + Administration write, org-authorized). Plain grow ticks work without it;
     replant/consolidate require it. Prefer org-level secrets — a successor repo created by
     `/replant` cannot set its own secrets. Note: `claude-code-action` overrides
     `GH_TOKEN`/`GITHUB_TOKEN` in the agent environment with its own repo-scoped app token, so
     the workflow passes the PAT as the dedicated `LIFECYCLE_PAT` env var and the replant /
     consolidate prompts invoke `GH_TOKEN="$LIFECYCLE_PAT" gh …` explicitly.
2. **Enable the workflow** — merge `.github/workflows/grow.yml`; adjust the cron to taste
   (daily ⇒ a 3-tick generation replants roughly twice a week; a 7-member year family consolidates
   in ~5 weeks).
3. **Tune the policy** — edit `lifecycle.policy` in `lifecycle.yml` (`replant_after_ticks`,
   `consolidate_at_members`, succession and naming rules). State (`status`, ticks, lineage) is
   machine-maintained; don't hand-edit it.
4. **Interactive alternative** — without Actions, run the same loop from Claude Code:
   `/grow` manually or under `/loop`; the lifecycle gate fires identically and will tell you when
   to run `/replant` or `/consolidate`.

## Invariants

- **The Evolution Log is the clock.** Tick counting derives from `seed.md` §8, never from a counter
  alone; `check-lifecycle` reconciles `lifecycle.yml` to it every run.
- **Replant never destroys.** A mature repo keeps all content and stays rebuildable from its seed;
  consolidation archives members read-only and preserves every member's seed + Evolution Log
  verbatim under `<member-slug>/seed.md`.
- **Only the newest member consolidates.** It alone holds the complete lineage list.
- **The framework stays concept-agnostic.** Years appear only in `lifecycle.yml` and `seed.md` §1;
  prompts/skills read the succession and naming rules, never hardcode them.
- **One heartbeat, no overlap.** The workflow's concurrency group guarantees at most one
  tick/replant/consolidation runs at a time per repo.
