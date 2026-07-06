---
lastmod: 2026-04-18T19:30:22.000Z
title: "Categories"
type: page
description: "Browse all categories and discover content by topic"
layout: default
permalink: /categories/
aliases:
  - /categories/
---

# Browse by Category

Explore content organized by category. Each category below lists the related articles from posts and notebooks. Click any note to open it.

## All Categories

```dataview
TABLE rows.file.link AS Notes, length(rows) AS Count
FROM "_posts" OR "_notebooks"
FLATTEN categories AS category
GROUP BY category
SORT category ASC
```

---

[[archives|Browse the Archive]]
