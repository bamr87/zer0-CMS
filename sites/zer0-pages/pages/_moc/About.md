---
title: "About Map"
type: page
description: "Map of Content for the _about collection — authors, features, settings, stats, and theme."
tags:
  - moc
  - about
---

# About Map

A Map of Content for the **_about** collection: the people behind the project ([[_about/authors/index|Authors]]), the [[_about/features/index|feature guides]], the site [[_about/settings/config|settings]], the live [[_about/stats|statistics portal]], and the [[_about/theme|Bootstrap theme examples]]. Start with the [[_about/index|About page]], then use the dashboards below to browse everything in the collection.

---

## Everything, by Section

Every note in the About collection, grouped by its subfolder.

```dataview
TABLE rows.file.link AS Notes, length(rows) AS Count
FROM "_about"
WHERE file.name != "index" AND file.name != "README"
GROUP BY file.folder AS Section
SORT Section ASC
```

---

## All About Notes

```dataview
TABLE type AS Type, description AS Summary
FROM "_about"
WHERE file.name != "index" AND file.name != "README"
SORT file.folder ASC, title ASC
```

---

## By Tag

```dataview
TABLE rows.file.link AS Notes
FROM "_about"
WHERE file.name != "index" AND file.name != "README"
FLATTEN tags AS tag
GROUP BY tag
SORT tag ASC
```
