---
title: "Obsidian Vault Integration"
description: "Edit Zer0-Mistakes content as an Obsidian vault and have it render identically on GitHub Pages."
preview: /images/previews/obsidian-vault-integration.png
layout: default
permalink: /docs/obsidian/
categories: [Documentation, Obsidian]
tags: [obsidian, authoring, workflow]
backlinks: true
lastmod: "2026-04-24T15:06:30Z"
type: doc
aliases:
  - /docs/obsidian/
---

# Obsidian Vault Integration

The Zer0-Mistakes repository is a fully-functional [Obsidian](https://obsidian.md) vault. Open the repo root (or any subfolder containing notes) as a vault and every Markdown file is editable with Obsidian's wiki-links, embeds, callouts, graph view, and backlinks. The same files render on GitHub Pages with the equivalent presentation — no duplication, no separate sync step.

## In this section

| Page | What it covers |
| --- | --- |
| [[_docs/obsidian/getting-started|Getting started]] | Open the repo as a vault, recommended plugins, frontmatter rules. |
| [[_docs/obsidian/syntax-reference|Syntax reference]] | Every Obsidian feature and how it renders on the site. |
| [[_docs/obsidian/graph|Graph view]] | Interactive force-directed map of every page and wiki-link. |
| [[_docs/obsidian/authoring-workflow|Authoring workflow]] | Daily note → commit → publish loop. |
| [[_docs/obsidian/troubleshooting]] | Broken links, missing embeds, conflicts. |

## How it works

The integration has two pieces:

1. **Server-side data emission.** A Liquid template emits
`assets/data/wiki-index.json` at every Jekyll build, listing every collection document and standalone page (title, basename, permalink, tags, aliases, excerpt). This works on the default GitHub Pages `remote_theme` build with no custom plugins required.
2. **Client-side resolver.** `assets/js/obsidian-wiki-links.js` loads the
index in the browser and rewrites `[[wiki-links]]`, `![[embeds]]`, inline `#tags`, and Obsidian callout blockquotes into Bootstrap-styled HTML. The result is indistinguishable from server-rendered output for readers, and lets the integration ship on plain GH Pages without a custom CI workflow.

For users who self-build with vanilla Jekyll (no `github-pages` gem), an opt-in Ruby plugin (`_plugins/obsidian_links.rb`) performs the same transformations server-side for slightly better SEO. See the
[[_docs/obsidian/syntax-reference|syntax reference]]
for the complete feature matrix.

## See also

- [[_docs/obsidian/getting-started|Getting Started with the Obsidian Vault]]
- [[_docs/obsidian/syntax-reference|Obsidian Syntax Reference]]
- [[_docs/obsidian/graph|Obsidian Graph View]]
- [[_docs/obsidian/authoring-workflow|Obsidian Authoring Workflow]]
- [[_docs/obsidian/troubleshooting|Obsidian Integration Troubleshooting]]
- [[front-matter]]
- [[_docs/installation|Installation]]
