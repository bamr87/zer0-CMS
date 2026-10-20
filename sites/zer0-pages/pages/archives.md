---
lastmod: 2026-04-18T19:30:21.000Z
title: "Archives"
description: "Post archives by year."
type: page
layout: default
permalink: /archives/
aliases:
  - /archives/
---

# Archives

Every post in the vault, grouped by the year it was published, newest first. The list below is generated automatically by Dataview, so it stays current as new posts are added.

```dataview
TABLE rows.file.link AS Posts, rows.date AS Date
FROM "_posts"
WHERE type = "post" AND draft != true
FLATTEN dateformat(date, "yyyy") AS year
GROUP BY year
SORT year DESC
```
