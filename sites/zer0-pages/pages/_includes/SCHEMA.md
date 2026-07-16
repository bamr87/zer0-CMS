---
schema: "0.1"
coverage: listed
---

# SCHEMA — _includes

> Local Jekyll include overrides — the only includes kept out of the theme gem, each fixing or trimming a gem include of the same path.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `content/` | dir | Override of the theme's content/intro.html (share, edit, and Copilot agent buttons) | |
| `obsidian/` | dir | Override of the theme's obsidian/full-graph.html (interactive vault graph body) | |

## Placement

- New override → mirror the theme gem's `_includes/` path exactly; remove it once the fix lands upstream in zer0-mistakes.
