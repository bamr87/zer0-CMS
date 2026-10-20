---
title: "zer0-pages"
type: entity
entity_type: product
description: "A GitHub repository/product name carrying two very different meanings: an aspirational Django+React AI-CMS described in a PRD, and the actual repo — a Jekyll site whose source is authored as an Obsidian vault via claude-obsidian."
role: "Repository name / product brand"
first_mentioned: "[[wiki/sources/zer0-pages-prd]]"
created: 2026-07-05
updated: 2026-07-05
tags:
  - entity
  - product
  - zer0-pages
status: seed
related:
  - "[[wiki/entities/claude-obsidian]]"
  - "[[wiki/entities/zer0-mistakes]]"
  - "[[wiki/concepts/jekyll-obsidian-dual-rendering]]"
  - "[[wiki/concepts/github-pages-deployment]]"
  - "[[wiki/concepts/ai-content-engine]]"
  - "[[wiki/concepts/prd-machine]]"
sources:
  - "[[wiki/sources/zer0-pages-prd]]"
---

# zer0-pages

## Overview

zer0-pages is the name of the GitHub repository this vault lives in (`github.com/bamr87/zer0-pages`), and this vault's [[wiki/sources/zer0-pages-prd|PRD]] gives that name to a much larger imagined product: an "AI-Powered Content Management System" pairing a Django REST backend, a React admin SPA, and Jekyll static-site generation. **The two are not the same thing.** The repository as it actually exists (2026-07-05) is a single Jekyll site: `pages/` is both the Jekyll source (`_docs/`, `_posts/`, `_notes/`, theme scaffolding) and an Obsidian vault, authored with the [[wiki/entities/claude-obsidian|claude-obsidian]] Claude Code plugin, and published straight to [[wiki/concepts/github-pages-deployment|GitHub Pages]] by one GitHub Actions workflow. There is no Django project, no React app, no PostgreSQL/Redis, and no `/api/` surface anywhere in the repo.

## Key Facts

- **Vision (per PRD)**: Django 4.2+ backend + DRF REST API + React 18 admin dashboard + Bootstrap public site + PostgreSQL + Redis + multi-provider AI (OpenAI/Anthropic/xAI), deployable to GitHub Pages or Azure. Every Phase-1 feature is marked "✅ Shipped." See [[wiki/sources/zer0-pages-prd|the PRD]].
- **Reality (per root `CLAUDE.md` and `pages/CLAUDE.md`)**: a Jekyll 4 site using the published `jekyll-theme-zer0` gem, with content authored inside `pages/` as an Obsidian vault. Content creation runs through [[wiki/entities/claude-obsidian|claude-obsidian]]'s skills (`/wiki-ingest`, `/save`, `/autoresearch`, `/wiki-query`), not a Django admin or React SPA.
- Actual deployment path: push to `main` → `.github/workflows/pages.yml` runs `jekyll build` (with the `pages/_plugins/` bridge converting wikilinks/Dataview/callouts to HTML) → publish to GitHub Pages at `https://bamr87.github.io/zer0-pages/`. No Azure component exists.
- The PRD's `combined_from` frontmatter lists four sibling PRDs (`githubai`, `barodybroject`, `zer0-mistakes`, `prd-machine`) — `zer0-mistakes` is real (it's the Jekyll theme this site actually uses, `jekyll-theme-zer0`); the other three describe subsystems (GitHub automation, a Django "parody generator" CMS, and PRD lifecycle tooling) not found in this repo.
- The PRD's own footer claims it is "maintained by zer0-pages and auto-updated via PRD Machine" (see [[wiki/concepts/prd-machine|PRD Machine]]) — no such automation exists in this repo; the file was ingested as a static, immutable source under `pages/.raw/`.

## Connections

- [[wiki/entities/claude-obsidian|claude-obsidian]] — the real engine doing the work the PRD assigns to Django + the React admin + the "AI Layer."
- [[wiki/entities/zer0-mistakes|zer0-mistakes]] — the upstream theme repo zer0-pages consumes as `jekyll-theme-zer0`; the stated purpose of this whole vault, beyond showcasing that theme, is to act as a second brain feeding knowledge back into zer0-mistakes' development.
- [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]] — the actual architecture of this repo, in place of the PRD's Django+Jekyll hybrid.
- [[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]] — the real, single deployment target.
- [[wiki/concepts/ai-content-engine|AI Content Engine]] — the PRD's name for AI content generation; realized here through claude-obsidian's skills instead of a Django AI service.
- [[wiki/concepts/prd-machine|PRD Machine]] — the PRD's self-described (but unimplemented, in this repo) authoring tool.
- [[_docs/obsidian/index|Obsidian Vault Integration]] — the vault-content-side doc describing (an earlier version of) how Obsidian and Jekyll coexist here.

## Sources

- [[wiki/sources/zer0-pages-prd|zer0-pages PRD]] (2025-12-01) — vision document; treat claims as aspirational, not verified.
