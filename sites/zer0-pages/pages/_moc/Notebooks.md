---
title: "Notebooks Map"
type: page
---

# Notebooks Map

A map of the runnable, exploratory notebooks in the vault. Each note in `_notebooks` is paired with a Jupyter `.ipynb` of the same name — the Markdown is the readable, linkable rendering; the notebook is the executable original.

Return to [[_moc/Home|Home]].

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

## By Category

```dataview
TABLE rows.file.link AS Notebooks
FROM "_notebooks"
WHERE type = "notebook" AND draft != true
FLATTEN categories AS category
GROUP BY category
SORT category ASC
```
