# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

**Irony Works** — a self-growing encyclopedia of irony, in two halves:

- `vault/` — an Obsidian vault of Markdown entries; the source of truth for all content
- `engine/` — a Node.js pipeline (five prompts, three scripts) that drafts new entries via the Claude API

The vault publishes as a Jekyll site through the `bamr87/zer0-mistakes` remote theme, with a thin **theme layer** of five local files over it (see [Theme layer](#theme-layer)). `2026-08-06-planting-irony-works-*.md` at the root is a draft design-notes post documenting the founding session (excluded from the site). The project's pre-rebrand state ("Ironicon") is preserved in the founding commit.

## Commands

There is no package.json, test suite, or linter. Scripts are plain Node ESM with one dependency installed ad hoc:

```sh
npm i js-yaml --no-save    # lib.mjs loads it via createRequire

# Full germination cycle: scout → alanis gate → scribe → nursery/compost
# (uses the local claude CLI's OAuth by default; ANTHROPIC_API_KEY only as fallback)
node engine/scripts/germinate.mjs [batch]

# Score specific entry files against the gate (the PR check)
node engine/scripts/gate.mjs vault/nursery/some-entry.md

# Convert vault → _entries/ Jekyll collection (wikilinks → permalinks); no credentials needed
node engine/scripts/transplant.mjs
```

`germinate.mjs` picks its domain by `GITHUB_RUN_NUMBER % domains.length` (unset locally, cycle 0 → first domain). All tunables — model, batch size, gate threshold, domain rotation, writable paths — live in `engine/seed.config.yml`.

## Architecture

**The schema is the classifier.** Irony is defined structurally, not in prose: every entry must state `expectation` and `reversal` as frontmatter fields. If a candidate can't fill both, it isn't irony and goes to compost. Entries also carry `status` (seed → sapling → canon → petrified), `veracity` (attested | contested | legend | speculative), and `alanis` (gate score, threshold 7/10). `vault/templates/` defines the exact shape; the Scribe prompt requires conformance to `entry.md`.

**Pipeline** (`engine/scripts/germinate.mjs`): the Scout prompt proposes candidates for the cycle's domain → the Alanis Gate (`engine/prompts/alanis-gate.md`) scores each 0–10 on five axes (reversal, commentary, inevitability, specificity, non-substitutability) → passes are drafted by the Scribe into `vault/nursery/`; failures are appended as rows to the ledger in `vault/compost/the-merely-unfortunate.md` with a verdict (MERELY-UNFORTUNATE, BAD-LUCK, COINCIDENCE, HYPOCRISY, NOT-EVEN-WRONG). Merging the nursery PR is the only path to canon — the machine proposes, the human disposes.

**Guardrails are enforced, not advisory.** `assertWritable()` in `engine/scripts/lib.mjs` restricts engine writes to exactly `vault/nursery/` and the compost ledger (`seed.config.yml → guardrails.writable`). The engine never modifies canon entries, its own prompts, workflows, or config; any automation you add must write through `writeVaultFile()`/`appendCompost()` so the whitelist applies. Edits made at the direct request of the human maintainer are a different channel — that's the "human hand" the governance requires.

**Harness swap point:** `harness()` in `lib.mjs` defaults to running prompts through the Claude Code CLI (`claude -p`), which authenticates via OAuth — keychain locally, `CLAUDE_CODE_OAUTH_TOKEN` in CI (`claude setup-token` generates one). If the CLI is missing or errors, it falls back to the Anthropic Messages API with `ANTHROPIC_API_KEY`; `harness.provider: anthropic` forces API-only. `harness.provider: lifehacker` hits a deliberate stub marked `// HARNESS ADAPTER` for routing through lifehacker.dev instead. Prompts are the contract; keep them wire-agnostic.

**Publishing:** `transplant.mjs` indexes every note's `title:` frontmatter (regex-matched — every note needs one), rewrites `[[wikilinks]]` (resolved case-insensitively by title or filename slug) into `/entries/<slug>/` permalinks, and emits everything except `vault/templates/` into `_entries/`. Jekyll builds that collection with the remote theme; `vault/`, `engine/`, and the root docs are excluded from the site.

## Theme layer

The site is a `remote_theme` consumer of `bamr87/zer0-mistakes`, unpinned. Five local files sit over it. Three **shadow** a theme file (declared in `.theme-overrides.yml` at the repo root, which is what keeps the theme's `scripts/bin/audit-consumer` honest — without it all three read as unjustified drift); two shadow nothing.

| File | Kind | Why it exists |
|---|---|---|
| `_layouts/section.html` | override (43 lines vs the theme's ~618) | The theme's `section` layout is a news/magazine view built entirely on `site.posts`, tags, and categories. This site has **zero posts** — its content is the custom `entries` collection — so the theme's version renders nothing. Ours filters `site.entries | where: "section", page.section` and shows each entry's `expectation` / `reversal` / `alanis` / `veracity` / `status`. Consumed by the eight branch pages: `forms`, `works`, `figures`, `instances`, `mirrors`, `futures`, `nursery`, `compost`. |
| `_includes/components/cookie-consent.html` | override (deliberately empty) | The theme's banner claims the site "analyzes traffic" and "provides personalized content" via cookies. This site sets no analytics and no cookies, so the banner would be a false statement occupying a third of the mobile viewport. **If analytics are ever added, delete this file** — the theme's banner returns on its own, and it should. |
| `_includes/custom/head.html` | override (extension point) | The theme ships this file as an intentionally **empty stub** whose own header comment tells consumers to shadow it. Ours adds one `<link>` to `/assets/css/sections.css` — the branch palette Jekyll generates at build time from `_data/sections.yml`. This is the hook working as designed, not drift. |
| `_includes/home/card.html` | ours (shadows nothing) | Magazine card for `index.md`; teases with the entry's `reversal`, not a generic excerpt. |
| `_includes/home/cover.html` | ours (shadows nothing) | Cover art for that card, falling back to a branch-coloured gradient. |

The theme has no `_includes/home/` directory at all, so the last two are net-new — **not** overrides, and deliberately absent from `.theme-overrides.yml`.

**Theme data contract (known gap, currently inert).** `remote_theme` does not ship `_data`, so consumers supply their own; this repo has only `_data/navigation/main.yml` and `_data/sections.yml`, and lacks `ui-text.yml`, `theme_skins.yml`, `theme_backgrounds.yml`, and `authors.yml` — with no visible effect today, because every one of the theme's ~43 `ui.*` reads carries an inline English `| default:`, `site.data.authors` is only indexed when a page sets `author:` (no entry or page does), `theme_skins`/`theme_backgrounds` are read only by `theme-controls-bar.html` / `theme-customizer.html` which no layout in this site's chain includes, and breadcrumbs are gated on an unset `site.breadcrumbs`. Add a data file when a component actually renders degraded without it — not preemptively.

**The Obsidian plugin is a non-issue.** The theme's `_plugins/obsidian_links.rb` is not needed here and must not be vendored in: `transplant.mjs` (`link()`) resolves every `[[wikilink]]` into a plain markdown link `[label](/entries/<slug>/)` — or into plain text plus a reported dead link — *before* Jekyll ever runs (`publish.yml` runs transplant, then `actions/jekyll-build-pages`). By build time there are no wikilinks left to convert. The theme's auditor lists it as an informational `OPTIONAL_PLUGIN`; earlier versions flagged it as missing. Either way, ignore it.

**Local preview.** There is none, by design-so-far: no `Gemfile`, no `docker-compose.yml`, no local bundle. CI builds with `actions/jekyll-build-pages` (the github-pages image, which bundles `jekyll-remote-theme`), so the only current way to see a themed change rendered is to push and let `publish.yml` run. Content and engine work does not need it — `node engine/scripts/transplant.mjs` runs with no credentials and shows exactly what Jekyll will be handed. Adding a local preview stack is a maintainer decision, not a papercut to patch around.

## Content conventions

- One entry per file, kebab-case filename; the filename is the permalink slug.
- Wikilink generously, but only to targets that exist — a broken wikilink is a promise the vault must keep or delete.
- Prefer one verified irony to five plausible ones. Thin sources → downgrade `veracity` and say so in the body; never sharpen a story past its evidence.
- Rejected candidates are logged in compost, never deleted; history occasionally files an appeal.
- `vault/mirrors/` documents this repository's own ironies — self-exemption would fail the vault's own gate.

## Workflows

- `.github/workflows/germinate.yml` — weekly cron (Mon 06:00 UTC) + manual dispatch with a `count` input; runs the engine and opens a PR from `vault/nursery/` changes. Needs the `CLAUDE_CODE_OAUTH_TOKEN` repo secret (or `ANTHROPIC_API_KEY` as fallback).
- `.github/workflows/alanis-gate.yml` — advisory PR check on `vault/**` changes; scores changed entries (excluding templates and compost) and posts the report as a PR comment and step summary. Never blocks — the gate scores, humans merge.
- `.github/workflows/publish.yml` — on push to main: transplant → Jekyll build (github-pages image bundles `jekyll-remote-theme`) → deploy to GitHub Pages.
