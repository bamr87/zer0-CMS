---
type: meta
title: "Wiki Index"
updated: 2026-07-05
---

# Wiki Index — master catalog

The `wiki/` folder is the [claude-obsidian](../../claude-obsidian) knowledge base: LLM-generated pages that summarize and cross-link sources dropped into `.raw/`. It starts nearly empty — the existing Jekyll content under `_docs/`, `_posts/`, and `_notes/` is *already* the vault's primary knowledge and is browsed via [[_moc/Home|the Home MOC]], not duplicated here.

## Vault content (Jekyll collections)

| Collection | Notes | MOC |
|---|---|---|
| Docs | 89 | [[_moc/Docs]] |
| Posts | 38 | [[_moc/Posts]] |
| Notes | 6 | [[_moc/Notes]] |

Engine showcase content (published, cross-linked into this wiki):
- [[_posts/development/2026-07-05-inside-the-zer0-pages-engine|Inside the zer0-pages Engine]] — post walking through the authoring → bridge → deploy pipeline.
- [[_notes/claude-obsidian-cheatsheet|claude-obsidian Cheatsheet]] — quick reference for the skills, dual-compat rules, and publishing flow.

## Wiki pages (generated)

- **Sources** — `wiki/sources/` — one summary per ingested `.raw/` document.
  - [[wiki/sources/zer0-pages-prd|zer0-pages PRD]]
- **Concepts** — `wiki/concepts/` — ideas, patterns, frameworks.
  - [[wiki/concepts/ai-content-engine|AI Content Engine]]
  - [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]]
  - [[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]]
  - [[wiki/concepts/prd-machine|PRD Machine]]
- **Entities** — `wiki/entities/` — people, orgs, products, repos.
  - [[wiki/entities/zer0-pages|zer0-pages]]
  - [[wiki/entities/claude-obsidian|claude-obsidian]]
- **Meta** — `wiki/meta/` — dashboards, lint reports, conventions.

See also: [[overview]] · [[hot]] · [[log]]
