---
schema: "0.1"
coverage: listed
---

# SCHEMA — pages

> The Obsidian vault that IS the Jekyll source (`source: pages`) — content collections, the wiki, theme data, bridge plugins, and assets; layouts and includes come from the jekyll-theme-zer0 gem.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `.obsidian/` | dir | Obsidian app/vault configuration (plugins, appearance, CSS snippets) — managed by Obsidian | terminal |
| `.raw/` | dir | Drop zone for raw source material awaiting /wiki-ingest — excluded from the build | terminal |
| `.vault-meta/` | dir | claude-obsidian vault bookkeeping (locks, metadata) — machine-managed | terminal |
| `.jekyll-cache/` | dir | Jekyll incremental-build cache (gitignored) | generated |
| `_data/` | dir | Live site + theme data — navigation, authors, UI text, skins (Jekyll never loads _data from theme gems) | |
| `_docs/` | dir | Docs collection — topic-organized documentation published under /docs/ | |
| `_includes/` | dir | Local include overrides for bugs/behaviour still present in the theme gem | |
| `_moc/` | dir | Maps of Content collection — dashboard pages published under /moc/ | |
| `_notes/` | dir | Notes collection — quick-reference cheatsheets published under /notes/ | |
| `_plugins/` | dir | Obsidian→Jekyll bridge plugins (wikilinks, callouts, Dataview, graph index) | |
| `_posts/` | dir | Posts collection — dated articles organized into category subdirectories | |
| `_templates/` | dir | Obsidian Templater templates for wiki page types — excluded from the build | |
| `assets/` | dir | Site-owned static assets — CSS/JS override hooks, images, background textures | |
| `wiki/` | dir | The claude-obsidian knowledge base — concepts, entities, sources, plus index/log/hot-cache | |
| `CLAUDE.md` | file | Vault-scoped Claude guidance (authoring conventions) — excluded from the build | |
| `archives.md` | file | /archives/ page — post archives by year | |
| `categories.md` | file | /categories/ page — posts grouped by category | |
| `favicon.ico` | file | Site favicon | |
| `index.md` | file | Site landing page (/) | |
| `notes.md` | file | /notes/ landing page for the notes collection | |
| `posts.md` | file | /posts/ landing page for the posts collection | |
| `tags.md` | file | /tags/ page — content grouped by tag | |

## Placement

- New content routes by type: post → `_posts/<category>/`, doc → `_docs/<topic>/`, cheatsheet → `_notes/`, wiki page → `wiki/`.
- New top-level page → `<name>.md` here with `permalink:` frontmatter; add it to `_data/navigation/main.yml` if it belongs in the navbar.
- Navigation or theme data changes → `_data/` (this copy is live, not the theme gem's).
