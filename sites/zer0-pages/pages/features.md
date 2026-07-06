---
title: "Features"
subtitle: "Complete Feature List"
description: "Comprehensive list of zer0-mistakes Jekyll theme features with documentation links and implementation details"
layout: default
permalink: /features/
date: 2025-12-16
lastmod: 2026-05-05
tags: [features, documentation, reference]
categories: [Documentation]
comments: false
toc: true
type: page
aliases:
  - /features/
---

# Features

Complete feature registry for the zer0-mistakes Jekyll theme. Each feature is documented with references, links, and implementation details. The gallery below is generated live from the feature notes in the vault, so it always reflects what is actually documented.

---

## Feature Gallery

Every documented theme feature, sorted by title.

```dataview
TABLE
  description AS Description,
  difficulty AS Difficulty,
  estimated_reading_time AS "Read Time"
FROM "_docs/features"
WHERE type = "doc" AND file.name != "index"
SORT title ASC
```

---

## Features by Tag

Browse features grouped by their tags — the equivalent of the Core Infrastructure, AI, Analytics & Privacy, Navigation, Content, and Developer Experience sections of the original registry.

```dataview
TABLE rows.file.link AS Features
FROM "_docs/features"
WHERE file.name != "index"
FLATTEN tags AS tag
GROUP BY tag
SORT tag ASC
```

---

## Features by Difficulty

```dataview
TABLE rows.file.link AS Features
FROM "_docs/features"
WHERE type = "doc" AND file.name != "index" AND difficulty
GROUP BY difficulty
SORT difficulty ASC
```

---

## Guides & How-Tos

Longer-form feature guides and how-to articles from the About collection.

```dataview
TABLE description AS Description, tags AS Tags
FROM "_about/features"
WHERE file.name != "index" AND draft != true
SORT title ASC
```

---

> [!info] Source
> This gallery is generated automatically from the feature notes under `_docs/features/` and `_about/features/` via Dataview. For the upstream machine-readable registry, see the [features registry on GitHub](https://github.com/bamr87/zer0-mistakes/blob/main/features/features.yml).
