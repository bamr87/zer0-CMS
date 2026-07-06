---
lastmod: 2026-04-18T19:30:21.000Z
title: "Notes"
description: "Quick reference notes, cheatsheets, and command snippets for developers"
type: page
layout: default
permalink: /notes/
aliases:
  - /notes/
---

# Notes

Quick reference notes, cheatsheets, and command snippets for developers.

## All notes

```dataview
TABLE description AS Summary, difficulty AS Difficulty, date AS Date
FROM "_notes"
WHERE type = "note" AND draft != true
SORT date DESC
```

## Browse by tag

```dataview
TABLE rows.file.link AS Notes
FROM "_notes"
WHERE type = "note" AND draft != true
FLATTEN tags AS tag
GROUP BY tag
SORT tag ASC
```
