---
title: "zer0-mistakes"
type: entity
entity_type: product
description: "The Bootstrap 5 + Jekyll theme repository (github.com/bamr87/zer0-mistakes) that zer0-pages consumes as the published jekyll-theme-zer0 gem — the project this vault exists, in part, to serve as a second brain for."
role: "Upstream theme repository, consumed as a gem"
first_mentioned: "CLAUDE.md (root, 'Theme' section)"
created: 2026-07-06
updated: 2026-07-06
tags:
  - entity
  - product
  - zer0-mistakes
  - theme
status: seed
related:
  - "[[wiki/entities/zer0-pages]]"
  - "[[wiki/entities/claude-obsidian]]"
  - "[[wiki/concepts/jekyll-obsidian-dual-rendering]]"
sources:
  - "root CLAUDE.md"
  - "README.md"
  - "[[_docs/development/index]]"
---

# zer0-mistakes

## Overview

zer0-mistakes (`github.com/bamr87/zer0-mistakes`) is a Bootstrap 5 + Jekyll starter theme with Docker tooling, GitHub Pages deployment, and analytics, published to RubyGems as `jekyll-theme-zer0`. **This repository's declared purpose, beyond showcasing the theme, is to function as a second brain for zer0-mistakes** — a place where research, decisions, and usage knowledge about the theme accumulate and can feed back into its development, distinct from the theme's own repository.

[[wiki/entities/zer0-pages|zer0-pages]] is zer0-mistakes' primary (and, as far as this vault knows, first) real-world consumer: it pulls in `jekyll-theme-zer0 (~> 1.25)` as a normal RubyGems dependency and builds its entire published site on top of it.

## Key Facts

- **What zer0-pages gets from the gem**: nearly all layouts (`default`, `article`, `note`, `section`, ...), includes, and vendored Bootstrap 5 come straight from `jekyll-theme-zer0`. `pages/_layouts/` keeps only two local 3-line wrapper layouts (`post`, `tutorial`) over the gem's `article` layout.
- **What zer0-pages must supply itself**: Jekyll never loads `_data/` from a theme gem, so every data file the theme reads — `navigation/*.yml`, `ui-text.yml`, `authors.yml`, `theme_skins.yml`, `theme_backgrounds.yml`, `content_statistics.yml`, `features.yml` — lives in `pages/_data/` in this repo, not upstream.
- **A deliberate non-reuse**: zer0-mistakes ships its own `obsidian_links.rb` Obsidian bridge plugin, but zer0-pages does **not** use it — plugins never load from theme gems in Jekyll, and that plugin resolves wikilinks by title, while this vault's links are path-qualified (`[[path/from/vault-root|Display]]`). Copying it in would double-convert links. `pages/_plugins/` is zer0-pages' own, independent bridge.
- **Local theme development path**: the root CLAUDE.md documents a temporary Gemfile override — `gem "jekyll-theme-zer0", path: "../github/zer0-mistakes"` — for hacking on the theme against a local checkout, with the explicit rule that the *committed* Gemfile must always reference the published gem.
- **Existing contributor documentation**: `pages/_docs/development/index.md` ("Contributing to Zer0-Mistakes") is a **contributor-accessible overview** of the theme's build/release/testing/security workflow (release management, version bumping, CI/CD, testing, security scanning, dependency updates, scripting, its own PRD). It explicitly defers deep technical reference — architecture, script internals, release-automation internals — to the `docs/` directory inside the zer0-mistakes repo itself, rather than reproducing it here.

## Why It Matters

zer0-mistakes is the one dependency zer0-pages cannot function without: remove the gem and there is no theme, no layouts, no Bootstrap. The relationship runs the other direction too, per the stated second-brain goal — zer0-pages is meant to be where knowledge *about* zer0-mistakes accumulates (design rationale, usage patterns, gotchas discovered while consuming it) so that future theme work benefits from what this vault learns, not just the other way around.

## Gap (open, as of this ingestion)

As of 2026-07-06, that second-brain relationship is declared but not yet built out: this vault has no synthesized content about zer0-mistakes' own internals (its plugin architecture, release-automation design, or the reasoning behind its API) — only user-facing "how to consume this theme" docs that point outward to the zer0-mistakes repo for anything deeper. Closing this gap would mean running `/wiki-ingest` or `/autoresearch` against zer0-mistakes' own `docs/` directory and filing the results here, rather than leaving it as an external link.

## Connections

- [[wiki/entities/zer0-pages|zer0-pages]] — the consumer repo; the two together are meant to form the author/theme pair this second-brain relationship describes.
- [[wiki/entities/claude-obsidian|claude-obsidian]] — the engine that would do the actual ingesting if/when the gap above is closed.
- [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]] — the architecture zer0-pages layers on top of the zer0-mistakes gem.

## Sources

- Root `CLAUDE.md` — "Theme" section (gem version, local-dev override, why `obsidian_links.rb` isn't reused).
- `README.md` — architecture diagram and "Learn more" section.
- [[_docs/development/index|Contributing to Zer0-Mistakes]] — the vault's existing (surface-level) documentation of the theme's contribution workflow.
