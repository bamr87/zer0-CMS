---
type: meta
title: "Hot Cache"
updated: 2026-07-05
---

# Recent Context

## Last Updated
2026-07-05. Authored two published showcase pieces about the content engine itself: a development post and a reference note, both cross-linked into the wiki layer.

## Key Recent Facts
- New post [[_posts/development/2026-07-05-inside-the-zer0-pages-engine|Inside the zer0-pages Engine]] documents the real pipeline end to end: [[wiki/entities/claude-obsidian|claude-obsidian]] skills author Markdown into the vault → `_plugins/` bridge converts wikilinks/callouts/Dataview at build time ([[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]]) → `jekyll-theme-zer0` themes → push to `main` deploys via Actions ([[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]]).
- New note [[_notes/claude-obsidian-cheatsheet|claude-obsidian Cheatsheet]] is the quick reference for working here: the five skills (`/wiki-ingest`, `/wiki-query`, `/save`, `/wiki-lint`, `/autoresearch`), dual-compat rules (flat frontmatter, path-qualified wikilinks, no Liquid, no new Dataview outside `_moc/`), folder map, publish flow.
- Both pieces link into the PRD-ingestion pages ([[wiki/sources/zer0-pages-prd|zer0-pages PRD]], [[wiki/concepts/ai-content-engine|AI Content Engine]], [[wiki/concepts/prd-machine|PRD Machine]], [[wiki/entities/zer0-pages|zer0-pages]]) and [[_docs/obsidian/graph|the graph view]], so the `wiki/` layer now has published backlinks from `_posts/` and `_notes/`.
- Standing caveat from the PRD ingestion: the PRD's Django+React+PostgreSQL stack is aspirational; the shipped system is the vault + bridge + Actions pipeline described in the new post.
- Content scope remains docs / posts / notes only — now 89 / 38 / 6 ([[_moc/Home]]).

## Recent Changes
- Created `_posts/development/2026-07-05-inside-the-zer0-pages-engine.md` and `_notes/claude-obsidian-cheatsheet.md`.
- Updated `wiki/index.md` (counts + showcase links) and appended `wiki/log.md`.

## Active Threads
- `.raw/` still holds `README.md` un-ingested; drop further sources and say "ingest [filename]".
- `scripts/wiki-lock.sh` remains inoperable here (`flock` missing) — solo passes only.
- Next `/wiki-lint` pass should confirm the two new pieces' wikilinks resolve in the published graph.
