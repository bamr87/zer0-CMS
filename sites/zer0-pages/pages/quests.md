---
lastmod: 2026-04-18T19:30:22.000Z
title: "Quests"
description: "Browse quests and tutorials."
layout: default
permalink: /quests/
type: page
aliases:
  - /quests/
---

# Quests

Browse the guided learning paths and tutorials available in this vault. Each quest walks you through a hands-on setup or workflow from start to finish.

```dataview
TABLE description AS Summary
FROM "_quickstart"
WHERE type = "quickstart" AND draft != true
SORT file.name ASC
```
