# Seed Package — bootstrap a self-growing knowledge-base lineage for any concept

This package is the distilled, portable form of the framework in this repository. With it, a
GitHub org, and two secrets, you can launch a lineage of self-growing knowledge-base repos for
**any** starting concept — a year, an organization, a technology, a person. The lineage grows,
replants successors, meta-reviews itself, and eventually consolidates, with no orchestrator
outside the repos themselves.

The package does **not** duplicate the framework — the framework *is* the `.github/` and
`.claude/` layers of the repo this package lives in. [`MANIFEST.md`](MANIFEST.md) names exactly
which files are load-bearing (copy them) and which are regenerable (don't). The two templates
here are the only files you fill in by hand.

## What you need

| Requirement | Why |
|---|---|
| A GitHub **organization** (or user account) to own the lineage | Successor repos are created here by `/replant`. |
| `ANTHROPIC_API_KEY` (org secret) | Auth for `claude-code-action`, which runs every tick. |
| `LIFECYCLE_PAT` (org secret) | PAT for cross-repo work: classic `repo` **+ `workflow`** scope (fine-grained: Contents write + Administration write + Workflows write, org-authorized). Without `workflow` scope, successors can't receive `grow.yml` and run on the shepherd fallback alone. |
| `CLAUDE_CODE_OAUTH_TOKEN` (org secret, *optional*) | Subscription fallback when API credits run out (`claude setup-token`). Strongly recommended — credit exhaustion is the most common way an unattended lineage stalls. |
| The **Claude GitHub App** installed on the org | Required by `claude-code-action`. |

Use **org-level** secrets: a successor repo created by `/replant` cannot set its own secrets, so
repo-level secrets break the lineage at the first replant.

## Configure and launch (≈10 minutes)

1. **Create the org** (or pick an existing one) and install the Claude GitHub App on it.
2. **Set the three org secrets** above (`ANTHROPIC_API_KEY`, `LIFECYCLE_PAT`, optionally
   `CLAUDE_CODE_OAUTH_TOKEN`).
3. **Create the first repo**, named for the starting concept's slug (e.g. `1776`), public.
4. **Copy the package contents** into it:
   - every file listed under *Load-bearing* in [`MANIFEST.md`](MANIFEST.md), verbatim
     (`.github/`, `.claude/`, `CLAUDE.md`, `LIFECYCLE.md`, `.gitignore`);
   - `lifecycle.template.yml` → `lifecycle.yml`, with the placeholders filled in (see below);
   - **nothing else** — no seed.md, no README, no content. The first scheduled run detects the
     missing seed and germinates the repo itself via `/genesis`.
5. **Push to `main`.** The `grow.yml` cron (daily by default) takes it from there:
   germination → 3 growth ticks → replant into the next concept → … → distillation at 3 members
   → consolidation at 7. Trigger the first run immediately with
   `gh workflow run grow.yml` if you don't want to wait for the cron.

`seed.template.md` is a reference, not a required file: `/genesis` writes the real `seed.md`
itself. Pre-filling one (template → `seed.md`, placeholders replaced) is only useful when you
want to dictate the taxonomy instead of letting genesis derive it.

## Worked example — starting concept "the year 1776"

1. Org `year-of-revolution`, App installed, three org secrets set.
2. Create `year-of-revolution/1776` (public).
3. Copy in the load-bearing framework files per the manifest.
4. Create `lifecycle.yml` from `lifecycle.template.yml` with:
   - `succession.rule`: `"Increment the calendar year of the newest lineage member by one (the year 1776 -> the year 1777)."`
   - `consolidation.naming_rule`: `"Hyphenated range of the lineage's years, oldest-newest (e.g. 1776-1782)."`
   - `consolidation.layout`: `"One top-level directory per lineage member, named by its subject slug (e.g. 1776/, 1777/)."`
   - first lineage member: `subject: "the year 1776"`, `repo: "year-of-revolution/1776"`,
     `status: growing`, `spawned_from: "<this package's source repo>"`.
5. Push. The first run finds no `seed.md`, runs `/genesis` (deriving "the year 1776" from the
   newest lineage member), and publishes a 12-row starter knowledge table — Declaration of
   Independence, *Common Sense*, the Wealth of Nations, the crossing of the Delaware, and so on,
   each verified against two authoritative sources. Subsequent daily ticks deep-dive topics,
   build TIMELINE/INDEX/cross-references, replant into `1777` after 3 ticks, and the lineage is
   running.

For a non-year concept (e.g. "the history of containerization"), the only thing that changes is
the `succession.rule` — write it in natural language ("move to the next major technology era…")
and `/replant` follows it.

## How it runs unattended (one paragraph)

Every repo carries `.github/workflows/grow.yml` — a daily, concurrency-guarded cron that runs one
lifecycle-gated tick: germinate if there's no seed; otherwise `check-lifecycle` decides
grow / replant / consolidate; mature repos don't stop — they *shepherd*, walking the lineage to
the newest growing member, pollinating framework updates forward, and executing that member's
tick in their own runner. At `distill_at_members` the run is promoted to a one-time
frontier-model meta-review (`/distill`); at `consolidate_at_members` the lineage merges into one
range-named repo and the members are archived. Details: `LIFECYCLE.md` in the repo root.

## Known sharp edges (already handled by the planted `grow.yml` — don't regress them)

- `claude-code-action` **overrides `GH_TOKEN`/`GITHUB_TOKEN`** in the agent environment; the PAT
  must travel as the dedicated `LIFECYCLE_PAT` env var.
- The action **exits 0 on "Credit balance is too low"**; the workflow greps the execution output
  to fire the subscription fallback.
- The job needs `id-token: write` permission and an explicit `--allowedTools` list (Bash/git/gh
  are denied by default in agent mode).
- The driver repo's `lifecycle.yml` lineage is the **registry** its phase resolver reads —
  replanting members must register their successors back into it (the replant prompt does this).
