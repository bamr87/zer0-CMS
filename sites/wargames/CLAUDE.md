# CLAUDE.md

Guidance for AI coding agents (Claude Code, Copilot, Cursor) working in **wargames**.

Wargames is a **content-only Jekyll site**: a vendored markdown mirror of the [OverTheWire](https://overthewire.org/wargames/) challenges, published on GitHub Pages with the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme loaded via `remote_theme`. "Done" means the content renders under the theme and the Pages build stays green. The challenge pages under `overthewire/**` are **vendored** — re-sync them from upstream via `scripts/docs-aggregator/`, don't hand-edit.

## Stack & commands

```bash
# install dependencies:  bundle install
# run the dev server:     bundle exec jekyll serve     # http://localhost:4000/wargames/
# build:                  bundle exec jekyll build
# re-sync content:        ./scripts/docs-aggregator/aggregate_docs.sh
# lint:                   python3 tools/unwrap-prose.py --check
```

## Site wiring

- `_config.yml` — `remote_theme: bamr87/zer0-mistakes`; `defaults` attach theme layouts to the root-level content (no Jekyll collections); `exclude` keeps tooling out of the build.
- `index.md` — homepage (`layout: home`, `permalink: /`).
- `overthewire/**` — vendored challenge pages at `/docs/wargames/…` (`layout: default` + auto games sidebar). Each level page carries `nav_order` + `sidebar_label` front matter (stamped by the aggregator) that the sidebar sorts/labels by; don't hand-edit — re-sync instead.
- `_data/navigation/` — `main.yml` (navbar) only. The games→levels sidebar is **auto-built** by the theme's `nav: pages` mode (set on the `overthewire` scope in `_config.yml`) from the page URLs under `/docs/wargames/` — there is no sidebar data file to generate or maintain.
- `zer0.install.yml` — declarative installer config; re-scaffold with the theme's `scripts/bin/install --config zer0.install.yml`.

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`).
- Default branch is `main` — branch from it and open a PR; never push to it directly.
- README-First, README-Last: read the nearest `README.md` before changing a
  directory, and update it after.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or
  leave empty exception handlers.

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents.
