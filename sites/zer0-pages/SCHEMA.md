---
schema: "0.1"
coverage: listed
---

# SCHEMA — zer0-pages

> AI-powered knowledge site: an Obsidian vault (`pages/`) that doubles as the Jekyll source, built by zer0-CMS's Jekyll-theme option — the zer0-mistakes theme pinned by tag, the vault's Obsidian syntax resolved in Python before a plugin-less Jekyll build.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `.github/` | dir | The Pages build/deploy (`pages.yml`), kept for reference: in the zer0-CMS monorepo only the root `.github/workflows/` runs, where `zer0-pages.yml` gates this site (the bridge's Python tests, SCHEMA lint, the option's build) | terminal |
| `claude-obsidian/` | dir | Git submodule of the external claude-obsidian content engine (AgriciDaniel/claude-obsidian) — consumed, never edited here | terminal |
| `pages/` | dir | The Obsidian vault and Jekyll source — all content collections, wiki, data files, bridge plugins, and assets | |
| `tools/` | dir | Repo tooling — the vendored Pyramid Schema linter | |
| `_site/` | dir | Jekyll build output (gitignored) — never hand-edit | generated |
| `AGENTS.md` | file | Agent guidance for working in this repo (architecture, workflows, conventions) — the one file every coding agent reads | |
| `CLAUDE.md` | file | A one-line pointer that imports `AGENTS.md` for Claude Code | |
| `PRD.md` | file | Product requirements document — goals, architecture decisions, and roadmap for zer0-pages | |
| `README.md` | file | Project overview — author/build/serve architecture, quickstart, authoring workflow | |
| `_config.yml` | file | Jekyll configuration — `source: pages`, collections, Obsidian and preview-image settings | |
| `LICENSE` | file | The MIT licence | |
| `.theme-overrides.yml` | file | Declares the theme partials this site intentionally forks, with the reason each is kept — read by the theme repo's `scripts/bin/audit-consumer` | |

## Placement

- New blog post → `pages/_posts/<category>/YYYY-MM-DD-slug.md` (see `pages/_posts/SCHEMA.md`).
- New documentation page → `pages/_docs/<topic>/` (see `pages/_docs/SCHEMA.md`).
- New wiki knowledge (concept, entity, source) → `pages/wiki/` per type (see `pages/wiki/SCHEMA.md`).
- Bridge code → zer0-CMS's `tools/obsidian/`, with its tests in `tools/tests/` (the site's Ruby plugins and their tests were deleted when it moved to the Jekyll-theme option, PLAN P-D7).
