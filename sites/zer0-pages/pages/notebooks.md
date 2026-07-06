---
lastmod: 2026-04-18T19:30:20.000Z
title: "Notebooks"
type: page
description: "Interactive Jupyter notebooks with tutorials and data analysis examples"
layout: default
permalink: /notebooks/
aliases:
  - /notebooks/
---

# Notebooks

Interactive Jupyter notebooks with tutorials, data analysis, and code examples.

## All Notebooks

```dataview
TABLE difficulty AS Difficulty, date AS Date, description AS Summary
FROM "_notebooks"
WHERE type = "notebook" AND draft != true
SORT date DESC
```

## By Difficulty

```dataview
TABLE rows.file.link AS Notebooks
FROM "_notebooks"
WHERE type = "notebook" AND draft != true
FLATTEN default(difficulty, "intermediate") AS level
GROUP BY level
SORT level ASC
```

## By Tag

```dataview
TABLE rows.file.link AS Notebooks
FROM "_notebooks"
WHERE type = "notebook" AND draft != true
FLATTEN tags AS tag
GROUP BY tag
SORT tag ASC
```
