---
schema: "0.1"
coverage: listed
---

# SCHEMA — zer0-pages

> AI-powered knowledge site: an Obsidian vault (`pages/`) that doubles as the Jekyll source, published to GitHub Pages with the jekyll-theme-zer0 gem and build-time Obsidian bridge plugins.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `.github/` | dir | GitHub Actions workflows — Pages build/deploy (`pages.yml`) and the SCHEMA.md lint gate (`schema-check.yml`) | terminal |
| `claude-obsidian/` | dir | Git submodule of the external claude-obsidian content engine (AgriciDaniel/claude-obsidian) — consumed, never edited here | terminal |
| `pages/` | dir | The Obsidian vault and Jekyll source — all content collections, wiki, data files, bridge plugins, and assets | |
| `tests/` | dir | Stdlib-only Ruby unit tests for the Obsidian bridge plugin cores | |
| `tools/` | dir | Repo tooling — the vendored Pyramid Schema linter | |
| `_site/` | dir | Jekyll build output (gitignored) — never hand-edit | generated |
| `vendor/` | dir | Local bundler gem install path (BUNDLE_PATH; gitignored) | generated |
| `CLAUDE.md` | file | Claude Code guidance for working in this repo (architecture, workflows, conventions) | |
| `Gemfile` | file | Ruby dependencies — Jekyll 4.3 plus the jekyll-theme-zer0 gem and Jekyll plugins | |
| `Gemfile.lock` | file | Locked gem versions for reproducible builds | |
| `PRD.md` | file | Product requirements document — goals, architecture decisions, and roadmap for zer0-pages | |
| `README.md` | file | Project overview — author/build/serve architecture, quickstart, authoring workflow | |
| `_config.yml` | file | Jekyll configuration — `source: pages`, theme, collections, bridge and preview-image settings | |
| `docker-compose.yml` | file | Docker-first local dev server (serves at localhost:4000/zer0-pages/) | |

## Placement

- New blog post → `pages/_posts/<category>/YYYY-MM-DD-slug.md` (see `pages/_posts/SCHEMA.md`).
- New documentation page → `pages/_docs/<topic>/` (see `pages/_docs/SCHEMA.md`).
- New wiki knowledge (concept, entity, source) → `pages/wiki/` per type (see `pages/wiki/SCHEMA.md`).
- Bridge plugin code → `pages/_plugins/` with a matching unit test in `tests/`.
