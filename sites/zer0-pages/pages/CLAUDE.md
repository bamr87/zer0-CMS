# pages — Obsidian Vault (claude-obsidian)

This directory is **both** the content source for the *zer0-mistakes* Jekyll theme **and** an Obsidian vault, converted with the [claude-obsidian](../claude-obsidian) plugin (LLM Wiki pattern).

**Vault path:** this directory (open it directly in Obsidian).
**Plugin:** `../claude-obsidian` — skills `/wiki`, `/wiki-ingest`, `/wiki-query`, `/wiki-lint`, `/save`, `/autoresearch`, `/canvas`.

## What changed in the Obsidian conversion

- Internal links were rewritten from Jekyll permalinks (`[x](/docs/…/)`) to Obsidian **wikilinks** (`[[_docs/…|x]]`), path-qualified so duplicate basenames (`index.md`, `README.md`) resolve unambiguously.
- Every note gained `type:` (post/doc/note/notebook/quickstart/about/page) and an `aliases:` entry carrying its old permalink, so historic URLs still resolve inside the vault.
- Dynamic Liquid listing pages (`tags`, `categories`, `archives`, `sitemap`, `features`, `notes`, `notebooks`, the post indexes) were re-authored as **Dataview** queries in `_moc/` and at the vault root.
- `.html` pages were converted to Markdown.
- Documentation that *teaches* Liquid (e.g. `_docs/liquid/`, `_docs/jekyll/`) keeps its Liquid intact inside code fences — those are examples, not directives.

> **Jekyll note:** this is now Obsidian-native. Wikilinks and Dataview do **not** render in Jekyll. The pristine Jekyll tree is backed up under `../.backups/pages-jekyll-*`. To publish with Jekyll again you'd re-introduce Liquid/permalink links.

## Vault structure

```
_about/  _docs/  _notes/  _notebooks/  _posts/  _quickstart/   content (notes)
_moc/          Maps of Content — Dataview dashboards, one per collection + Home
_templates/    Obsidian note templates (concept/entity/source/question/comparison)
.raw/          immutable source drop-zone for /wiki-ingest — never modified
wiki/          claude-obsidian knowledge base (index, hot cache, log, overview)
.obsidian/     vault config (graph colored by collection, Dataview + snippets enabled)
```

## Conventions

- **Wikilinks** `[[path/to/note|Display]]` for all internal references; path is vault-relative, no extension.
- **Frontmatter** is flat YAML: `title`, `type`, `tags`, `categories`, `description`, `aliases`, plus theme keys.
- **`.raw/` is immutable.** Drop a source there and say "ingest [filename]".
- **`wiki/index.md`** is the master catalog; **`wiki/log.md`** is append-only (newest on top); **`wiki/hot.md`** is an overwritten ~500-word cache.
- Requires the **Dataview** community plugin (Settings → Community plugins → install "Dataview"). MOCs are empty without it.

## Operations

- Browse: open `_moc/Home.md` — the vault hub.
- Query: ask any question; read `wiki/hot.md` → `wiki/index.md` → the relevant note.
- Ingest: drop a file in `.raw/`, say "ingest [filename]" (`/wiki-ingest`).
- Lint: "lint the wiki" (`/wiki-lint`) every 10–15 ingests.
