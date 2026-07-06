---
title: Home
layout: home
type: page
---

This is the landing page for the vault. Start at the hub: [[_moc/Home|Home MOC]].

## Recent Posts

```dataview
TABLE date AS Date, description AS Summary
FROM "_posts"
WHERE type = "post" AND draft != true
SORT date DESC
```
