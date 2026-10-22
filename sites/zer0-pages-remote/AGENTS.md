# AGENTS.md

Guidance for AI coding agents (Claude Code, Copilot, Cursor) working in **zer0-pages-remote**.

This is the **minimal reference consumer** of the [bamr87/zer0-mistakes](https://github.com/bamr87/zer0-mistakes) remote theme — a demo proving how few files a working GitHub Pages site needs: `_config.yml` and `index.md`. Its value is being small, so "done" here means the site still builds and the file count did not grow. Do not turn it into a real content site.

## Stack & commands

```bash
# build:                  python3 ../../tools/jekyll_theme.py build zer0-pages-remote   # → _site/ (Docker, no Ruby)
# run tests:              none — there is no test suite; CI is the safety net
# lint:                   python3 ../../tools/unwrap-prose.py --check   # --write to fix
```

This repo now lives in the zer0-CMS monorepo at `sites/zer0-pages-remote/`, where it renders with the Jekyll-theme option: the root `sites.yml` and `pages.yml` build it on any pull request touching it with GitHub Pages' own builder (the `github-pages` gem in **safe mode**, Jekyll 3.10.0 — what GitHub Pages publishes) in a container, with the theme at the tag the root `workspace.yml` pins, and the root `markdown-oneline.yml` and `claude.yml` cover prose and `@claude` mentions. There is no Gemfile and no `docker-compose.yml` any more: the builder's image carries Jekyll and its plugins, so nothing Ruby lives here.

## What is deliberately absent

- **No theme overrides.** There is no `_layouts/`, `_includes/`, `_sass/`, or `_plugins/` here, and none should be added — the whole point is that the remote theme supplies all of it. Theme bugs go upstream to `bamr87/zer0-mistakes`, never patched around locally.
- **No `_data/`.** The theme's data contract (`navigation/`, `ui-text.yml`, `theme_skins.yml`, `theme_backgrounds.yml`, `authors.yml`) is unmet on purpose. This does not break the build: Liquid `assign` over a missing `site.data` key yields nil, and the theme guards every read (`_includes/navigation/navbar.html` does `assign nav_main = site.data.navigation.main` then `if nav_main and nav_main.size > 0`, falling back to collection-derived nav; `_includes/core/header.html` guards `site.data.navigation.home` the same way). The trade-off is real, though — with no `_data/`, this demo **cannot** show off the theme's navigation, skins, or background features. Adding `_data/` is the first step if that ever becomes the goal.
- **`site_configured: false`.** Kept false on purpose so the theme's onboarding wizard stays visible on the `welcome` layout — that wizard is what the demo demonstrates. Flipping it to `true` hides the thing this repo exists to show.

## The safe-mode plugin invariant

Every plugin the theme needs must be listed under `plugins:` in `_config.yml`. GitHub Pages builds in safe mode and registers only whitelisted plugins named there, so a plugin missing from that list is a build failure — that is exactly how the `Unknown tag 'include_cached'` outage happened (PR #8, commit `c4666ff`). The builder's image has every whitelisted plugin installed; the list is what turns one on.

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`).
- Default branch is `main` — branch from it and open a PR; never push to it directly.
- Markdown prose is one paragraph per line (CI-enforced); run `python3 ../../tools/unwrap-prose.py --write` after authoring.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or leave empty exception handlers.

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents.
