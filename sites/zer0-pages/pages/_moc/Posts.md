---
title: "Posts Map"
type: page
description: "Map of Content for the _posts collection — every article, newest first, plus a breakdown by category."
---

# Posts Map

A Map of Content for the `_posts` collection. The tables below are generated automatically by Dataview, so this page always reflects the current set of posts. The first table lists every published post newest-first with its tags; the second groups posts by category.

## All Posts (newest first)

```dataview
TABLE date AS Date, tags AS Tags
FROM "_posts"
WHERE type = "post" AND draft != true
SORT date DESC
```

## Posts by Category

```dataview
TABLE rows.file.link AS Notes, length(rows) AS Count
FROM "_posts"
WHERE type = "post" AND draft != true
FLATTEN categories AS category
GROUP BY category
SORT category ASC
```
