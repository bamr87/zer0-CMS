---
title: "claude-obsidian Cheatsheet"
description: "Quick reference for working in this vault: the claude-obsidian skills, dual-compatibility rules, folder layout, and how publishing works"
layout: note
date: 2026-07-05T12:00:00.000Z
lastmod: 2026-07-05T12:00:00.000Z
categories: [Notes, Reference]
tags: [claude-obsidian, obsidian, jekyll, cheatsheet, reference]
author: "Zer0-Mistakes Team"
difficulty: beginner
comments: true
permalink: /notes/claude-obsidian-cheatsheet/
type: note
aliases:
  - /notes/claude-obsidian-cheatsheet/
---

Quick reference for creating and maintaining content in this vault with the [[wiki/entities/claude-obsidian|claude-obsidian]] plugin. Full background: [[_posts/development/2026-07-05-inside-the-zer0-pages-engine|Inside the zer0-pages Engine]].

## The Skills

| Skill | What it does | Trigger phrase |
|---|---|---|
| `/wiki-ingest` | Reads a source from `.raw/`, extracts entities and concepts, files cross-linked pages into `wiki/` | "ingest [filename]" |
| `/wiki-query` | Answers questions from the vault — hot cache first, then index, then pages | "what do you know about X" |
| `/save` | Captures the current conversation or insight as a structured note | "save this" |
| `/wiki-lint` | Finds orphan pages, dead wikilinks, frontmatter gaps, empty sections | "lint the wiki" |
| `/autoresearch` | Runs a web-research loop on a topic and files findings as wiki pages | "research X" |

Run `/wiki-lint` every 10-15 ingests to keep the graph clean.

## Dual-Compatibility Rules

Every file must render correctly in both Obsidian and Jekyll:

- **Frontmatter** is flat YAML with at least `title`, `type`, `description`, `tags`. Collection content follows its siblings' conventions — read one first.
- **Wikilinks** are path-qualified from the vault root, no extension: `[[wiki/concepts/ai-content-engine|AI Content Engine]]`. Bare `[[Note Title]]` links break when basenames collide.
- **No Liquid.** `render_with_liquid: false` is the site default, so Liquid tag and output delimiters would print literally instead of executing. Liquid lives only in `_layouts/` and `_includes/`.
- **Dataview** blocks belong in `_moc/` dashboards; do not add new ones elsewhere.
- **Callouts** (`> [!note]`) work in both renderers via the bridge plugins.

Canonical rules: [[wiki/meta/conventions|Vault Conventions]]. Syntax details: [[_docs/obsidian/syntax-reference|Obsidian Syntax Reference]].

## Where Things Live

| Path | Purpose |
|---|---|
| `_docs/` `_posts/` `_notes/` | The only three content collections |
| `_moc/` | Maps of Content — Dataview dashboards, start at [[_moc/Home]] |
| `wiki/` | Generated knowledge base: sources, entities, concepts, meta |
| `wiki/index.md` | Master catalog — [[wiki/index|Wiki Index]] |
| `wiki/log.md` | Append-only operations log, newest on top |
| `wiki/hot.md` | Overwritten ~500-word recent-context cache |
| `.raw/` | Immutable drop-zone for `/wiki-ingest` — never edit |
| `_templates/` | Obsidian note templates (concept, entity, source, ...) |
| `_plugins/` `_layouts/` `_includes/` `assets/` | Jekyll machinery — the only place Liquid is allowed |

Example wiki pages to model new ones on: [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]], [[wiki/entities/zer0-pages|zer0-pages]], [[wiki/sources/zer0-pages-prd|zer0-pages PRD]].

## How Publishing Works

1. Write or generate Markdown anywhere under `pages/` (this vault **is** the Jekyll source).
2. The bridge plugins in `_plugins/` convert wikilinks, callouts, and Dataview at build time — source files are never rewritten.
3. Push to `main`; `.github/workflows/pages.yml` builds with Jekyll + the bridge and deploys to GitHub Pages. See [[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]].
4. Check [[_docs/obsidian/graph|the graph view]] after publishing — dead wikilinks appear as red broken nodes. Fix the link, not the graph.

## Quick Sanity Checklist

- [ ] Frontmatter has `title`, `type`, `description`, `tags`
- [ ] All wikilinks path-qualified and pointing at files that exist
- [ ] Zero Liquid tags outside code fences
- [ ] New wiki pages linked from [[wiki/index|the index]]; `wiki/log.md` appended; `wiki/hot.md` refreshed
