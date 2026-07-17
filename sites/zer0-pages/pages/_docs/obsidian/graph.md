---
title: "Graph View"
description: "Interactive force-directed map of every wiki-link between the vault's docs, posts, and notes."
layout: default
permalink: /docs/obsidian/graph/
categories: [Documentation, Obsidian]
tags: [obsidian, graph, navigation]
backlinks: false
sitemap: false
lastmod: "2026-07-05T12:00:00Z"
type: doc
# The include below is Liquid; this page is the single content-side exception
# to the site-wide render_with_liquid: false default.
render_with_liquid: true
aliases:
  - /docs/obsidian/graph/
---

# Graph View

A live, force-directed map of this vault — every doc, post, note, and page becomes a node, and every `[[wiki-link]]` between them becomes an edge. It is the rendered-site equivalent of Obsidian's graph view, built at Jekyll build time by the bridge's wikilink parser (the same one described in the
[[_docs/obsidian/syntax-reference|syntax reference]]) and drawn client-side
with cytoscape. Dangling links appear as dashed red nodes: fix the link, not the graph.

{% include obsidian/full-graph.html %}
