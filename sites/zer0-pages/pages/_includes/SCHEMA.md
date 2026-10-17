---
schema: "0.1"
coverage: listed
---

# SCHEMA — _includes

> Local Jekyll include overrides — the only includes kept out of the theme gem, each a deliberate fork of a gem include of the same path, declared with its reason in the repo-root `.theme-overrides.yml`.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `content/` | dir | Override of the theme's content/intro.html (share, edit, and Copilot agent buttons) | |
| `obsidian/` | dir | Override of the theme's obsidian/full-graph.html (interactive vault graph body) | |

## Placement

- New override → mirror the theme gem's `_includes/` path exactly, and add an entry (with `reason` and `upstream`) to the repo-root `.theme-overrides.yml`; an undeclared fork is flagged as drift by the theme's `scripts/bin/audit-consumer`. Retire the fork when its declared reason no longer holds — for a bug fork that means the fix landing upstream, but neither current fork is a bug fork.
