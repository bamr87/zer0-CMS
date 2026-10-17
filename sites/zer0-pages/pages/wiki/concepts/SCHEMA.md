---
schema: "0.1"
coverage: listed
---

# SCHEMA — concepts

> Concept pages — one idea, methodology, or mechanism per page (type: concept).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `_index.md` | file | Section index listing the concepts pages | |
| `*.md` | pattern | One concept per page (kebab-case slug, e.g. radical-transparency, prd-machine) | |

## Placement

- New concept page → a kebab-case `.md` here from `pages/_templates/concept.md`; register it in `../index.md`.
