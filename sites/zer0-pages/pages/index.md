---
title: Home
layout: home
type: page
description: "Landing page for the zer0-pages vault — the Obsidian-authored knowledge base and Jekyll source behind the zer0-mistakes theme."
permalink: /
aliases:
  - /
---

This is the landing page for the vault. Start at the hub: [[_moc/Home|Home MOC]].

## Recent Posts

```dataview
TABLE date AS Date, description AS Summary
FROM "_posts"
WHERE type = "post" AND draft != true
SORT date DESC
```
