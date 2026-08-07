# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Irony Works** (formerly "Ironicon") — a self-growing encyclopedia of irony, in two halves:

- `vault/` — an Obsidian vault of Markdown entries; the source of truth for all content
- `engine/` — a Node.js pipeline (five prompts, three scripts) that drafts new entries via the Claude API

The vault publishes as a Jekyll site through the `bamr87/zer0-mistakes` remote theme. `ironicon-README.md` and `2026-08-06-planting-ironicon-*.md` at the root are historical snapshots from before the rebrand — leave them as they are.

## Commands

There is no package.json, test suite, or linter. Scripts are plain Node ESM with one dependency installed ad hoc:

```sh
npm i js-yaml --no-save    # lib.mjs loads it via createRequire

# Full germination cycle: scout → alanis gate → scribe → nursery/compost
ANTHROPIC_API_KEY=... node engine/scripts/germinate.mjs [batch]

# Score specific entry files against the gate (the PR check)
ANTHROPIC_API_KEY=... node engine/scripts/gate.mjs vault/nursery/some-entry.md

# Convert vault → _entries/ Jekyll collection (wikilinks → permalinks); no API key needed
node engine/scripts/transplant.mjs
```

`germinate.mjs` picks its domain by `GITHUB_RUN_NUMBER % domains.length` (unset locally, cycle 0 → first domain). All tunables — model, batch size, gate threshold, domain rotation, writable paths — live in `engine/seed.config.yml`.

## Architecture

**The schema is the classifier.** Irony is defined structurally, not in prose: every entry must state `expectation` and `reversal` as frontmatter fields. If a candidate can't fill both, it isn't irony and goes to compost. Entries also carry `status` (seed → sapling → canon → petrified), `veracity` (attested | contested | legend | speculative), and `alanis` (gate score, threshold 7/10). `vault/templates/` defines the exact shape; the Scribe prompt requires conformance to `entry.md`.

**Pipeline** (`engine/scripts/germinate.mjs`): the Scout prompt proposes candidates for the cycle's domain → the Alanis Gate (`engine/prompts/alanis-gate.md`) scores each 0–10 on five axes (reversal, commentary, inevitability, specificity, non-substitutability) → passes are drafted by the Scribe into `vault/nursery/`; failures are appended as rows to the ledger in `vault/compost/the-merely-unfortunate.md` with a verdict (MERELY-UNFORTUNATE, BAD-LUCK, COINCIDENCE, HYPOCRISY, NOT-EVEN-WRONG). Merging the nursery PR is the only path to canon — the machine proposes, the human disposes.

**Guardrails are enforced, not advisory.** `assertWritable()` in `engine/scripts/lib.mjs` restricts engine writes to exactly `vault/nursery/` and the compost ledger (`seed.config.yml → guardrails.writable`). The engine never modifies canon entries, its own prompts, workflows, or config; any automation you add must write through `writeVaultFile()`/`appendCompost()` so the whitelist applies. Edits made at the direct request of the human maintainer are a different channel — that's the "human hand" the governance requires.

**Harness swap point:** `harness()` in `lib.mjs` calls the Anthropic Messages API directly (model from `seed.config.yml`). Setting `harness.provider: lifehacker` hits a deliberate stub marked `// HARNESS ADAPTER` for routing through lifehacker.dev instead. Prompts are the contract; keep them wire-agnostic.

**Publishing:** `transplant.mjs` indexes every note's `title:` frontmatter (regex-matched — every note needs one), rewrites `[[wikilinks]]` (resolved case-insensitively by title or filename slug) into `/entries/<slug>/` permalinks, and emits everything except `vault/templates/` into `_entries/`. Jekyll builds that collection with the remote theme; `vault/`, `engine/`, and the root docs are excluded from the site.

## Content conventions

- One entry per file, kebab-case filename; the filename is the permalink slug.
- Wikilink generously, but only to targets that exist — a broken wikilink is a promise the vault must keep or delete.
- Prefer one verified irony to five plausible ones. Thin sources → downgrade `veracity` and say so in the body; never sharpen a story past its evidence.
- Rejected candidates are logged in compost, never deleted; history occasionally files an appeal.
- `vault/mirrors/` documents this repository's own ironies — self-exemption would fail the vault's own gate.

## Current state (2026-08)

Not yet a git repository. The README references GitHub Actions workflows (`.github/workflows/germinate.yml`, the gate PR check, Pages publishing) that do not exist in this copy — they need to be recreated before the germination cycle can run on a schedule.
