---
title: "GitHub Pages Deployment Model"
type: concept
complexity: beginner
domain: "static site deployment"
description: "The repo's actual, sole deployment target: a GitHub Actions workflow builds the Jekyll site on every push to main and publishes it to GitHub Pages — with no Azure component, unlike the PRD's dual-target vision."
aliases: []
created: 2026-07-05
updated: 2026-07-05
tags:
  - concept
  - deployment
  - github-pages
  - jekyll
status: seed
related:
  - "[[wiki/entities/zer0-pages]]"
  - "[[wiki/concepts/jekyll-obsidian-dual-rendering]]"
sources:
  - "[[wiki/sources/zer0-pages-prd]]"
---

# GitHub Pages Deployment Model

## Definition

The mechanism by which this repository's Jekyll site becomes a live website: on every push to `main` that touches `pages/**`, `_config.yml`, `Gemfile*`, or the workflow file itself, `.github/workflows/pages.yml` builds the site with Jekyll and deploys the result to GitHub Pages at `https://bamr87.github.io/zer0-pages/` (`baseurl: /zer0-pages`).

## How It Works

1. A push to `main` triggers the Actions workflow.
2. `bundle install` resolves the `jekyll-theme-zer0` gem (~> 1.25) and other Gemfile dependencies; CI runs on Ruby 3.3.
3. `jekyll build` runs, with `pages/_plugins/` (the bridge) converting wikilinks/Dataview/callouts to HTML and generating `/assets/data/wiki-index.json` for the vault graph — see [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]].
4. The built `_site` is uploaded and deployed to GitHub Pages.
5. One-time manual prerequisite per repo: **Settings → Pages → Build and deployment → Source: GitHub Actions** — without this, the very first deploy fails with a `Get Pages site failed` 404.

There is exactly one deployment target. `pages/.raw/` sources and `wiki/` pages that reference other targets (see below) are describing a vision, not this pipeline.

## Why It Matters

The [[wiki/sources/zer0-pages-prd|zer0-pages PRD]] (§4 tech-stack table, §7.1, §11 launch criteria) frames deployment as a choice between "GitHub Pages, Azure, or any hosting platform," implying a portable Django backend that could run anywhere. In reality, this repo has no backend to deploy elsewhere — it *is* a static site, and GitHub Pages is not one option among several but the only publishing mechanism that exists. That's a meaningfully simpler (and cheaper — literally free) deployment story than the PRD implies, and it's worth recording as ground truth so future ingestions don't reintroduce an "Azure" deployment target that was never built.

## Examples

- The PRD's installation flow (§6.1) shows `curl … install.sh`, `pip install zer0-pages`, and `docker-compose up -d` as user-facing setup paths — none of which exist in this repo; the only real "install" step for a *contributor* is `bundle install` (or `bundle exec jekyll build` locally) plus, for Obsidian authoring, opening `pages/` as a vault (see [[_docs/obsidian/getting-started|Getting Started with the Obsidian Vault]]).
- The PRD's §11 "Launch Criteria" checklist ("GitHub Pages deployment works with automatic CI/CD") is the one launch criterion that is actually true of this repo today.

## Connections

- [[wiki/entities/zer0-pages|zer0-pages]] — the repo/product this deployment model belongs to.
- [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]] — the build-time process that produces what gets deployed.
- [[_docs/obsidian/graph|Graph view]] — one of the artifacts (`wiki-index.json` + the Cytoscape graph UI) produced during this same build and shipped as part of the deploy.

## Sources

- [[wiki/sources/zer0-pages-prd|zer0-pages PRD]] §4, §7.1, §11 — describes GitHub Pages as one of several targets; contrasted here with the single-target reality.
- Root `CLAUDE.md` "Content flow" and "Build & test" sections — authoritative description of the actual pipeline.
