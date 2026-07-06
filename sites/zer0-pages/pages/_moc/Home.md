---
title: "Home"
type: page
---

# Welcome Home

This is the front door to the vault — a living map of everything inside. Start wherever you're curious and follow the links. Each collection has its own map of content (MOC) that gathers its notes, and the quick-reference pages below help you slice the whole vault by tag, category, or date.

## Collections

- [[_moc/Quickstart|Quickstart]] — the fastest path from zero to running.
- [[_moc/Docs|Docs]] — reference material, guides, and how-tos.
- [[_moc/Posts|Posts]] — articles, essays, and dispatches.
- [[_moc/Notebooks|Notebooks]] — runnable, exploratory notebooks.
- [[_moc/Notes|Notes]] — shorter thoughts and working notes.
- [[_moc/About|About]] — who and what this project is.

## Find Your Way

- [[tags|Tags]] — browse everything by topic.
- [[categories|Categories]] — browse by category.
- [[archives|Archives]] — everything, ordered by date.
- [[sitemap|Sitemap]] — the full lay of the land.
- [[glossary|Glossary]] — terms and definitions.
- [[roadmap|Roadmap]] — where things are headed.
- [[faq|FAQ]] — answers to the common questions.

## Fresh Off the Press

The eight most recent posts:

```dataview
TABLE date AS Date, description AS Summary
FROM "_posts"
WHERE type = "post" AND draft != true
SORT date DESC
LIMIT 8
```
