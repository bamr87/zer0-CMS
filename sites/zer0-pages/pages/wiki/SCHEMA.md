---
schema: "0.1"
coverage: listed
---

# SCHEMA — wiki

> The claude-obsidian knowledge base — typed knowledge pages (concepts, entities, sources) plus the vault's operating meta pages.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `concepts/` | dir | Concept pages — one idea, methodology, or mechanism per page | |
| `entities/` | dir | Entity pages — organizations, tools, projects, and standards | |
| `meta/` | dir | Vault conventions and governance notes | |
| `sources/` | dir | Source-summary pages for ingested material | |
| `hot.md` | file | Hot cache — recent context the wiki skills read first | |
| `index.md` | file | Master catalog of every wiki page | |
| `log.md` | file | Append-only operation log of vault changes | |
| `overview.md` | file | Narrative overview of the wiki's scope and shape | |

## Placement

- New knowledge routes by type: concept → `concepts/`, entity → `entities/`, source summary → `sources/` (kebab-case, from `pages/_templates/`).
- Update `index.md` and append to `log.md` in the same change.
