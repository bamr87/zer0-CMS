---
title: "zer0-pages Product Requirements Document (PRD)"
type: source
source_type: prd
description: "Aspirational PRD (v1.0.0, dated 2025-12-01) describing zer0-pages as a Django+React AI-powered CMS with a Jekyll static-site layer — a vision that does not match the vault's actual claude-obsidian + Jekyll bridge implementation."
author: "zer0-pages (auto-updated via PRD Machine, per document footer)"
date_published: 2025-12-01
url: "pages/.raw/zer0-pages-prd.md"
confidence: low
key_claims:
  - "Backend is Django 4.2+ with PostgreSQL, Redis, and a React 18 admin SPA"
  - "AI Content Engine, GitHub Integration Hub, and PRD Machine are all '✅ Shipped'"
  - "Static output is deployed via Jekyll to GitHub Pages or Azure"
created: 2026-07-05
updated: 2026-07-05
tags:
  - source
  - prd
  - zer0-pages
status: seed
related:
  - "[[wiki/entities/zer0-pages]]"
  - "[[wiki/entities/claude-obsidian]]"
  - "[[wiki/concepts/ai-content-engine]]"
  - "[[wiki/concepts/jekyll-obsidian-dual-rendering]]"
  - "[[wiki/concepts/github-pages-deployment]]"
  - "[[wiki/concepts/prd-machine]]"
sources: []
---

# zer0-pages Product Requirements Document (PRD)

## Summary

`pages/.raw/zer0-pages-prd.md` is a combined PRD (v1.0.0, dated 2025-12-01, "Active" status) for a product called **zer0-pages**, pitched as an "AI-Powered Content Management System" that merges a Django REST backend, a React admin SPA, and Jekyll static-site generation, with AI (OpenAI/Anthropic/xAI) woven through content generation, GitHub automation, and PRD lifecycle management. Its frontmatter says it was `combined_from` four sibling PRDs: `githubai`, `barodybroject`, `zer0-mistakes`, and `prd-machine`. The document marks every Phase-1 feature (§5: AI Content Engine, GitHub Integration Hub, PRD Machine, Jekyll Site Builder, CMS Backend & React Admin, Privacy-First Analytics) as "✅ Shipped," but no Django app, React app, PostgreSQL/Redis config, or `manage.py` exists anywhere in this repository — the actual system is the **claude-obsidian** Claude Code plugin operating on this **pages/** directory as an Obsidian vault that doubles as the Jekyll source, bridged to static HTML by Ruby plugins in `pages/_plugins/` and deployed to GitHub Pages by a single GitHub Actions workflow. Treat this PRD as **product vision / marketing narrative**, not as a description of the current system — see [[wiki/entities/zer0-pages|zer0-pages]] and the root `CLAUDE.md` architecture contract for the reality check.

## Key Claims

- Vision: "next-generation CMS that combines the power of Django's robust backend with Jekyll's lightning-fast static site generation," AI-first throughout (§1).
- Architecture (§4): React admin SPA + Bootstrap public site, both fronting a Django backend (REST API via DRF, a "Jekyll Generator," and an "AI Layer") backed by PostgreSQL, Redis, and the GitHub API.
- Tech stack table (§4): Django 4.2+, Jekyll 4.3+, Bootstrap 5.3, React 18+, PostgreSQL 14+, Redis, OpenAI/Anthropic/xAI, Docker, deployed to "GitHub Pages / Azure."
- Core features (§5), all marked Shipped: AI Content Engine (blog/doc/PRD generation, code analysis, multi-provider fallback), GitHub Integration Hub (auto-issue generation, code-quality scans, webhook processing), PRD Machine (generate/enhance/version/export PRDs), Jekyll Site Builder (zero-config GitHub Pages deploy, AI-assisted install), CMS Backend & React Admin (full REST API under `/api/`, Monaco-based content editor), Privacy-First Analytics (PostHog, GDPR/CCPA consent).
- Roadmap (§9): Phase 1 (v1.0) marked complete; Phase 2 (v1.1, Q1 2026) adds WYSIWYG editing, GraphQL headless CMS, i18n, team collaboration; Phase 3 (v1.2, Q2 2026) adds multi-tenancy, enterprise SSO, custom AI fine-tuning.
- Installation instructions (§6.1) describe `curl … install.sh`, `pip install zer0-pages`, and `docker-compose up -d` — none of which correspond to any script or Dockerfile actually present in this repo.

## Entities Mentioned

- [[wiki/entities/zer0-pages|zer0-pages]] — the product this PRD describes; the actual repo/vault operating under that name today is a very different (much simpler) system than the PRD's vision.
- [[wiki/entities/claude-obsidian|claude-obsidian]] — not named in the PRD at all, but is the real engine that plays the role the PRD assigns to the Django backend + AI layer + React admin (content authoring, AI generation, ingestion).

## Concepts Introduced

- [[wiki/concepts/ai-content-engine|AI Content Engine]] — the PRD's name (§5.1) for AI-driven content generation; the real vault achieves the same *goal* (AI-authored docs/posts/notes) via claude-obsidian's skills, not a Django "AI Layer" service.
- [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]] — not in the PRD (which describes a Django+Jekyll hybrid instead); this is the concept that actually governs this repo and is the load-bearing architectural idea worth preserving from this ingestion pass.
- [[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]] — the PRD mentions GitHub Pages as one of two deployment targets (§4 tech stack, §11 launch criteria); the real repo deploys exclusively to GitHub Pages via a single Actions workflow, with no Azure/Django component.
- [[wiki/concepts/prd-machine|PRD Machine]] — the PRD's own name (§5.3) for automated PRD generation/enhancement/versioning/export; ironically this document is itself an artifact ostensibly produced by that system ("maintained by zer0-pages and auto-updated via PRD Machine," per its footer), yet no such tooling exists in this repo.

## Notes

> [!contradiction] Vision vs. reality
> This PRD describes zer0-pages as a shipped Django + React + PostgreSQL + Redis product with a REST API under `/api/`. The actual repository at the time of this ingestion (2026-07-05) contains no Django project, no React app, no database, and no `/api/` surface of any kind — see `find . -iname "*django*"` and `find . -iname "package.json"`, both empty. The real, working system is documented in the root `CLAUDE.md` (architecture contract) and `pages/CLAUDE.md` (vault conventions): a Ruby/Jekyll static site whose content is authored as an Obsidian vault via the `claude-obsidian` Claude Code plugin, with `pages/_plugins/` bridging Obsidian syntax to HTML at build time. Every "✅ Shipped" marker in §5 of this PRD should be read as aspirational copy, not verified status, until corroborating implementation is found.

See also: [[wiki/entities/zer0-pages|zer0-pages]] · [[wiki/entities/claude-obsidian|claude-obsidian]] · [[_docs/obsidian/index|Obsidian Vault Integration]] · [[_docs/obsidian/getting-started|Getting Started with the Obsidian Vault]]
