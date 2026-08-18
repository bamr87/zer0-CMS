# AGENTS.md — AI Agent Guide for Wargames

> Cross-tool entry point for AI coding agents (GitHub Copilot, Claude Code, Cursor, Aider, etc.)

## Project snapshot

- **What it is**: A content-only Jekyll site — a vendored markdown mirror of the [OverTheWire](https://overthewire.org/wargames/) challenges, published on GitHub Pages
- **Theme source**: remote (`remote_theme: bamr87/zer0-mistakes`) — this repo vendors **zero** theme files
- **Theme repo**: https://github.com/bamr87/zer0-mistakes
- **Content**: at the repo root — `index.md` (homepage) and `overthewire/**` (the challenge pages). There is no `pages/` directory and no populated Jekyll collections.

## Quick commands

```bash
# Install dependencies
bundle install

# Development (no Docker in this repo; the devcontainer runs this same command)
bundle exec jekyll serve --host 0.0.0.0 --port 4000 --livereload   # http://localhost:4000/wargames/

# Build
bundle exec jekyll build

# Lint (markdown prose must be one paragraph per line — CI enforces it)
python3 tools/unwrap-prose.py --check    # --write to fix
```

There is no test suite. CI is the safety net — see the workflow list in [`CLAUDE.md`](CLAUDE.md).

## Operating rules

1. Make minimal, surgical changes. Match existing style.
2. Validate before declaring done — run a Jekyll build and `python3 tools/unwrap-prose.py --check`.
3. Site content lives at the repo root (`index.md`, `overthewire/**`); site data lives in `_data/`.
4. **Don't hand-edit `overthewire/**`** — those pages are vendored and re-synced from upstream by `scripts/docs-aggregator/`.
5. **No theme overrides here.** This repo is a pure `remote_theme` consumer with no `_layouts/`, `_includes/`, `_sass/`, or `_plugins/` — keep it that way. Theme changes belong upstream in [zer0-mistakes](https://github.com/bamr87/zer0-mistakes).

See [`CLAUDE.md`](CLAUDE.md) for the fuller site-wiring reference and [`README.md`](README.md) for the reader-facing overview.
