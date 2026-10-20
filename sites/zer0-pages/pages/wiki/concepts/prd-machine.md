---
title: "PRD Machine"
type: concept
complexity: beginner
domain: "product documentation tooling"
description: "The PRD's own name for automated PRD generation, enhancement, versioning, and export — including a claim that the PRD itself is 'auto-updated' by this system, which does not exist anywhere in this repository."
aliases: []
created: 2026-07-05
updated: 2026-07-05
tags:
  - concept
  - prd
  - automation
status: seed
related:
  - "[[wiki/entities/zer0-pages]]"
  - "[[wiki/concepts/ai-content-engine]]"
sources:
  - "[[wiki/sources/zer0-pages-prd]]"
---

# PRD Machine

## Definition

PRD Machine is the [[wiki/sources/zer0-pages-prd|zer0-pages PRD]]'s (§5.3) name for a feature that automates the product-requirements-document lifecycle: generating PRDs from GitHub repository analysis, downloading/extracting existing PRDs, enhancing them with AI, merging multiple PRDs into one, versioning changes, and exporting to GitHub Issues or Jira. The PRD's own frontmatter (`combined_from: … prd-machine`) and closing line ("*This document is maintained by zer0-pages and auto-updated via PRD Machine.*") claim the very document describing this feature was itself produced by it.

## How It Works

Per the PRD, this is a `Generate → Enhance → Version → Export` pipeline with a feedback loop back to "Generate," implemented as part of the Django backend and exposed through the PRD Workspace in the React admin dashboard (visual editor, version diff, export options). No such pipeline exists in this repository: there is no PRD data model, no versioning store, and no export-to-Issues/Jira integration. The PRD file itself was received as a single static Markdown file dropped into `pages/.raw/` and ingested manually via claude-obsidian's `/wiki-ingest` skill — the opposite of an automated, self-updating pipeline.

## Why It Matters

This is a small but sharp illustration of the vision/reality gap running through the whole PRD: the document asserts its own provenance is machine-automated, and that assertion is itself unverifiable/false in this repo's context. It's a caution for future ingestions — a source claiming to be "auto-generated" or "auto-updated" by a named subsystem should not be taken as proof that subsystem exists; check for corroborating implementation (as was done here: no PRD data model, no export integration, no Django project at all).

## Examples

- PRD §5.3 workflow diagram: `Generate from Repo → Enhance with AI → Version Control → Export to Tools`, with a feedback loop.
- PRD §12 "Related Documents" lists sibling PRDs (`githubai-prd.md`, `zer0-mistakes-prd.md`, `barodybroject-prd.md`) as if cross-referenced by this same machine — none of those files exist in `pages/.raw/` at time of ingestion (only `zer0-pages-prd.md` and a `README.md` are present).

## Connections

- [[wiki/concepts/ai-content-engine|AI Content Engine]] — PRD Machine is presented as a specialized application of the same underlying AI-generation capability.
- [[wiki/entities/zer0-pages|zer0-pages]] — the product this feature is attributed to.
- [[wiki/sources/zer0-pages-prd|zer0-pages PRD]] — the document that both describes and (unverifiably) claims to be a product of this feature.

## Sources

- [[wiki/sources/zer0-pages-prd|zer0-pages PRD]], §5.3 "PRD Machine" and closing attribution line.
