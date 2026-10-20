---
title: "Home"
type: page
---

# Welcome Home

This is the front door to the vault — a living map of everything inside. Start wherever you're curious and follow the links. Each collection has its own map of content (MOC) that gathers its notes, and the quick-reference pages below help you slice the whole vault by tag, category, or date.

## Collections

- [[_moc/Docs|Docs]] — reference material, guides, and how-tos.
- [[_moc/Posts|Posts]] — articles, essays, and dispatches.
- [[_moc/Notes|Notes]] — shorter thoughts and working notes.

## Find Your Way

- [[tags|Tags]] — browse everything by topic.
- [[categories|Categories]] — browse by category.
- [[archives|Archives]] — everything, ordered by date.

## Fresh Off the Press

The eight most recent posts:

```dataview
TABLE date AS Date, description AS Summary
FROM "_posts"
WHERE type = "post" AND draft != true
SORT date DESC
LIMIT 8
```
