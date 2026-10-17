---
schema: "0.1"
coverage: listed
---

# SCHEMA — sources

> Source-summary pages — one per ingested document or article (type: source).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `_index.md` | file | Section index listing the sources pages | |
| `*.md` | pattern | One source summary per ingested document (kebab-case slug) | |

## Placement

- New source page → a kebab-case `.md` here from `pages/_templates/source.md`; register it in `../index.md`.
