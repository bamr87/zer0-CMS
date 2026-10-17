---
title: "Notes Map"
type: page
description: "Map of Content for the notes collection — quick-reference cheatsheets and command snippets for developers."
---

# Notes Map

A Map of Content for the `_notes` collection: quick-reference cheatsheets, command snippets, and productivity tips. The lists below are generated live by Dataview, so this map stays current as notes are added.

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

## Browse by category

```dataview
TABLE rows.file.link AS Notes
FROM "_notes"
WHERE type = "note" AND draft != true
FLATTEN categories AS category
GROUP BY category
SORT category ASC
```

## By difficulty

```dataview
TABLE rows.file.link AS Notes
FROM "_notes"
WHERE type = "note" AND draft != true
FLATTEN difficulty AS level
GROUP BY level
SORT level ASC
```

## Related

- [[notes|Notes index]]
