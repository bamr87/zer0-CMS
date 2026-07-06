---
type: meta
title: "Conventions"
updated: 2026-07-05
---

# Vault Conventions

- **Wikilinks**: `[[path/from/vault-root/note|Display]]` — path-qualified (no extension) so duplicate basenames resolve.
- **Frontmatter**: flat YAML. Required-ish keys: `title`, `type`, `tags`, `description`. `aliases` carries the old Jekyll permalink.
- **`type`**: `post` · `doc` · `note` · `page` · `meta`.
- **MOCs** live in `_moc/` and are Dataview dashboards — one per collection plus `[[_moc/Home]]`.
- **`.raw/`** is immutable source input for `/wiki-ingest`; **`wiki/`** is generated knowledge.
- **`log.md`** is append-only (newest on top); **`hot.md`** is an overwritten ~500-word cache.
- Dynamic listings use **Dataview** (requires the community plugin).

See the plugin: [claude-obsidian](../../../claude-obsidian).
