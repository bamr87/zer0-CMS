---
type: meta
title: "Log"
updated: 2026-07-05
---

# Log

Append-only. Newest entries on top.

## 2026-07-05 — Authored engine-showcase content
- Created post [[_posts/development/2026-07-05-inside-the-zer0-pages-engine|Inside the zer0-pages Engine: Obsidian In, GitHub Pages Out]] — end-to-end walkthrough of the pipeline: claude-obsidian skills author into the vault → `_plugins/` bridge converts wikilinks/Dataview/callouts → `jekyll-theme-zer0` themes → Actions deploys to Pages. Wikilinked to the four ingested concept pages, both entity pages, the PRD source page, and [[_docs/obsidian/graph|the graph view]].
- Created note [[_notes/claude-obsidian-cheatsheet|claude-obsidian Cheatsheet]] — quick reference covering the skills (`/wiki-ingest`, `/wiki-query`, `/save`, `/wiki-lint`, `/autoresearch`), dual-compatibility rules, folder layout, and the publish flow. Wikilinked to [[wiki/index|the wiki index]], [[wiki/meta/conventions|conventions]], and the ingested wiki pages.
- Updated `wiki/index.md` (collection counts 38 posts / 6 notes + showcase links), this log, and `wiki/hot.md`.
- First published content authored *about* the engine *by* the engine — both pieces double as backlink anchors pulling the `wiki/` layer into the site graph.

## 2026-07-05 — Ingested zer0-pages PRD
- Ingested `pages/.raw/zer0-pages-prd.md` (v1.0.0, dated 2025-12-01) via `/wiki-ingest`.
- Created source [[wiki/sources/zer0-pages-prd|zer0-pages PRD]].
- Created entities [[wiki/entities/zer0-pages|zer0-pages]] and [[wiki/entities/claude-obsidian|claude-obsidian]].
- Created concepts [[wiki/concepts/ai-content-engine|AI Content Engine]], [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]], [[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]], [[wiki/concepts/prd-machine|PRD Machine]].
- Updated `wiki/index.md`, `wiki/entities/_index.md`, `wiki/concepts/_index.md`, `wiki/sources/_index.md`.
- Flagged a `[!contradiction]` in the source page and cross-referenced it from both entity pages: the PRD describes a Django+React+PostgreSQL+Redis "shipped" product; this repo has none of that — the real system is `claude-obsidian` authoring an Obsidian vault that Jekyll bridge plugins publish to GitHub Pages. Every PRD "✅ Shipped" marker should be read as marketing copy, not verified status.
- `bash claude-obsidian/scripts/wiki-lock.sh` was tested but is inoperable on this machine (`flock: command not found`); pages were written directly since this was a solo ingestion pass, not a parallel batch.

## 2026-07-05 — Slim-down to docs / posts / notes
- Narrowed the vault to three content collections (`_docs/`, `_posts/`, `_notes/`) per project directive; everything else removed (committed history keeps it recoverable).
- Deleted collections: `_quests/` (3), `_quickstart/` (5), `_about/` (~30), `_notebooks/` (10 incl. `.ipynb`).
- Deleted MOCs: `_moc/Quests`, `_moc/Quickstart`, `_moc/About`, `_moc/Notebooks`.
- Deleted 13 loose root pages: quests, notebooks, contact, faq, features, glossary, hobbies, privacy-policy, roadmap, services, setup, sitemap, terms-of-service.
- Swept kept content for dead references: trimmed [[_moc/Home]] collections/find-your-way lists, fixed Dataview `FROM` clauses in `tags`/`categories`, retargeted or dropped wikilinks and prose mentions across `_docs/` and `_notes/`, updated [[wiki/index|wiki index]], [[overview]], [[hot]], and `wiki/meta/conventions`.
- Rationale: focus the site + graph on the docs/posts/notes knowledge base ahead of enabling the Obsidian graph UI and the claude-obsidian content engine.

## 2026-07-05 — Vault conversion
- Converted `pages/` (zer0-mistakes Jekyll content) into an Obsidian vault with claude-obsidian.
- Backed up pristine Jekyll tree to `../.backups/pages-jekyll-20260705-200505/` (197 files).
- Rewrote 302 permalink links → wikilinks across 173 notes (fence-aware; assets/external links left intact).
- Rewrote 241 pre-existing bare concept links (`[[Jekyll]]`…) → path-qualified via a title map.
- Augmented frontmatter on 173 notes with `type` + `aliases`.
- Re-authored 18 dynamic Liquid listing pages as Dataview pages; converted 3 `.html` → `.md`.
- Cleaned unfenced Liquid from 24 pages (`{% raw %}`, `{% include %}` widgets, `{{ site.* }}`).
- Built 7 MOCs (`_moc/Home` + one per collection).
- Scaffolded `.obsidian/`, `.raw/`, `wiki/`, `_moc/`, `_templates/`.
- Final lint: 662 wikilinks, 4 intentional unresolved (template placeholders + 2 future-page stubs), 0 stray Liquid, 0 `.html`.
