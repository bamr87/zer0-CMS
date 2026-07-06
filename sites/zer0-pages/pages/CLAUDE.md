# pages — Obsidian Vault (claude-obsidian)

This directory is **both** the content source for the *zer0-mistakes* Jekyll theme (consumed as the published gem `jekyll-theme-zer0`, ~> 1.25) **and** an Obsidian vault, converted with the [claude-obsidian](../claude-obsidian) plugin (LLM Wiki pattern).

**Vault path:** this directory (open it directly in Obsidian).
**Plugin:** `../claude-obsidian` — skills `/wiki`, `/wiki-ingest`, `/wiki-query`, `/wiki-lint`, `/save`, `/autoresearch`, `/canvas`. These skills are **the** content-creation path for docs, posts, and notes.

## What changed in the Obsidian conversion

- Internal links were rewritten from Jekyll permalinks (`[x](/docs/…/)`) to Obsidian **wikilinks** (`[[_docs/…|x]]`), path-qualified so duplicate basenames (`index.md`, `README.md`) resolve unambiguously.
- Every note gained `type:` (post/doc/note/page) and an `aliases:` entry carrying its old permalink, so historic URLs still resolve inside the vault.
- Dynamic Liquid listing pages (`tags`, `categories`, `archives`, `notes`, the post indexes) were re-authored as **Dataview** queries in `_moc/` and at the vault root.
- `.html` pages were converted to Markdown.
- Documentation that *teaches* Liquid (e.g. `_docs/liquid/`, `_docs/jekyll/`) keeps its Liquid intact inside code fences — those are examples, not directives.
- The vault was later **slimmed to three collections** — `_docs/`, `_posts/`, `_notes/` — everything else (quests, quickstart, about, notebooks, misc loose pages) was removed; see `wiki/log.md`.

> **Jekyll note:** this vault **is** the Jekyll source (`../_config.yml` sets `source: pages`). Wikilinks, Dataview fences, and callouts are converted to HTML at build time by the bridge plugins in `_plugins/` — the **sole** Obsidian→HTML converter (the theme repo ships its own `obsidian_links.rb`, but plugins never load from theme gems and it resolves links by title, so copying it in would double-convert this vault's path-qualified links) — and source files are never rewritten. Content must stay **Liquid-free** (`render_with_liquid: false` is defaulted; `{% %}`/`{{ }}` would appear literally) — the one exception is `_docs/obsidian/graph.md`, which sets `render_with_liquid: true` for its single `{% include %}` line. Liquid otherwise lives only in `_layouts/` and `_includes/`; nearly all layouts come from the `jekyll-theme-zer0` gem, with `_layouts/` holding just the local `post`/`tutorial` wrappers. The pre-conversion Jekyll tree is backed up under `../.backups/pages-jekyll-*`. See the root `../CLAUDE.md` for the full dual-compatibility contract and theme details.

## Vault structure

```
_docs/  _posts/  _notes/    content — the ONLY three collections
_moc/          Maps of Content — Dataview dashboards: Home, Docs, Posts, Notes
_templates/    Obsidian note templates (concept/entity/source/question/comparison)
.raw/          immutable source drop-zone for /wiki-ingest — never modified
wiki/          claude-obsidian knowledge base (index, hot cache, log, overview)
.obsidian/     vault config (graph colored by collection, Dataview + snippets enabled)
_data/         theme data — navigation/, ui-text, authors, skins, ... (Jekyll never
               loads _data from theme gems, so the site supplies it here)
_layouts/  _includes/  _plugins/  assets/    Jekyll render machinery (hidden from
               Obsidian via app.json ignore filters; the only place Liquid is allowed).
               Layouts/includes/Bootstrap come from the jekyll-theme-zer0 gem —
               _layouts/ keeps only the post/tutorial wrappers,
               _includes/obsidian/full-graph.html overrides the theme's graph include,
               _plugins/ holds the bridge + the wiki-index.json graph generator, and
               assets/css/user-overrides.css is the theme's custom-CSS hook
```

Loose pages at the vault root are limited to the indexes: `index.md`, `posts.md`,
`notes.md`, `archives.md`, `categories.md`, `tags.md`.

## Conventions

- **Wikilinks** `[[path/to/note|Display]]` for all internal references; path is vault-relative, no extension.
- **Frontmatter** is flat YAML: `title`, `type`, `tags`, `categories`, `description`, `aliases`, plus theme keys.
- **`.raw/` is immutable.** Drop a source there and say "ingest [filename]".
- **`wiki/index.md`** is the master catalog; **`wiki/log.md`** is append-only (newest on top); **`wiki/hot.md`** is an overwritten ~500-word cache.
- Requires the **Dataview** community plugin (Settings → Community plugins → install "Dataview"). MOCs are empty without it.

## Graph view (published site)

The site renders an interactive vault graph at `/docs/obsidian/graph/`
(`_docs/obsidian/graph.md`, which includes `obsidian/full-graph.html`). At build time
`_plugins/obsidian_graph_index.rb` reuses the bridge's wikilink parser to emit
`/assets/data/wiki-index.json` (nodes = docs/posts/notes, edges = wikilinks); the
theme's Cytoscape UI (on by default; `../_config.yml` pins `obsidian: enabled: true`)
fetches it client-side. Dead wikilinks appear as red "broken" nodes — fix the link,
not the graph. The theme's `note` layout also shows a backlinks panel fed by the same
JSON.

## Operations

- Browse: open `_moc/Home.md` — the vault hub.
- Query: ask any question (`/wiki-query`); read `wiki/hot.md` → `wiki/index.md` → the relevant note.
- Ingest: drop a file in `.raw/`, say "ingest [filename]" (`/wiki-ingest`).
- Research: "research X" (`/autoresearch`) runs a web-research loop and files structured pages into the wiki.
- Save: "save this" (`/save`) captures the current conversation or insight as a note.
- Lint: "lint the wiki" (`/wiki-lint`) every 10–15 ingests.
- Publish: push to `main` — `.github/workflows/pages.yml` builds with Jekyll + the `_plugins/` bridge and deploys to GitHub Pages.
