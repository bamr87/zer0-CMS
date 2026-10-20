---
title: "Inside the zer0-pages Engine: Obsidian In, GitHub Pages Out"
description: "How this site works end to end: content authored in an Obsidian vault with claude-obsidian skills, converted by Jekyll bridge plugins, themed by zer0-mistakes, and deployed by GitHub Actions."
date: 2026-07-05T12:00:00.000Z
lastmod: 2026-07-05T12:00:00.000Z
author: default
layout: article
categories: [Development]
tags: [obsidian, jekyll, claude-obsidian, github-pages, static-sites, ai-tooling]
featured: false
estimated_reading_time: "6 min"
draft: false
type: post
---

Every page on this site — including the one you are reading — starts life as a Markdown note in an Obsidian vault. There is no CMS, no database, no admin panel. The entire publishing system is a directory of plain-text files plus three cooperating layers: an AI authoring layer, a syntax bridge, and a deployment pipeline. This post walks through each one.

## Layer 1: Authoring in the vault

The `pages/` directory of the repository is simultaneously the Jekyll source and an Obsidian vault. Open it in Obsidian and you get backlinks, graph view, and Dataview dashboards; point Jekyll at it and you get a website. That dual identity is the core design decision, documented in [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]].

Content does not get typed in by hand most of the time. It is produced by [[wiki/entities/claude-obsidian|claude-obsidian]], a Claude Code plugin vendored as a git submodule, whose skills are the content-creation path:

- `/wiki-ingest` reads a source dropped into the immutable `.raw/` folder and files structured pages — sources, entities, concepts — into `wiki/`.
- `/wiki-query` answers questions from the vault, reading the hot cache first, then the index, then individual notes.
- `/save` captures a conversation or insight as a note.
- `/autoresearch` runs a web-research loop and files its findings as wiki pages.
- `/wiki-lint` sweeps for orphan pages, dead wikilinks, and frontmatter gaps.

This is the practical realization of the [[wiki/concepts/ai-content-engine|AI Content Engine]] idea: an agent that reads sources and writes cross-linked knowledge directly into the same tree the website builds from. The first real workout was ingesting the project's own PRD ([[wiki/sources/zer0-pages-prd|zer0-pages PRD]]), which produced two entity pages, four concept pages, and one deliberately skeptical source summary.

> [!note] Files are the API
> The skills mutate nothing but Markdown. Every "write" is a file the git history records, Obsidian renders, and Jekyll publishes. There is no hidden state to migrate, back up, or reverse-engineer.

## Layer 2: The bridge plugins

Obsidian syntax is not Jekyll syntax. Wikilinks like `[[path/to/note|Display]]`, callout blocks, and Dataview query fences would all appear as literal text in a stock Jekyll build. The bridge plugins in `_plugins/` are the sole Obsidian-to-HTML converter, and they run at build time without ever rewriting source files:

- **Wikilinks** are path-qualified from the vault root (`[[wiki/concepts/ai-content-engine|AI Content Engine]]`), so duplicate basenames such as `index.md` resolve unambiguously. The bridge turns each into the target page's permalink.
- **Callouts** — the `> [!note]` block above — become styled admonitions.
- **Dataview** fences in the `_moc/` dashboards are evaluated into static listings, replacing the dynamic Liquid index pages the site used to have.

One deliberate constraint follows from this: content stays Liquid-free. The site defaults `render_with_liquid: false`, so template tags would print literally rather than execute. Anything dynamic belongs in layouts and includes, or in a Dataview query.

A second plugin, `obsidian_graph_index.rb`, reuses the bridge's wikilink parser to emit `assets/data/wiki-index.json` — every doc, post, and note as a node, every wikilink as an edge. The theme's Cytoscape UI fetches that JSON client-side and renders [[_docs/obsidian/graph|the graph view]] at `/docs/obsidian/graph/`. Dead links show up there as red "broken" nodes, which makes link rot visible instead of silent. The same JSON feeds the backlinks panel on note pages.

## Layer 3: Theme and deployment

Presentation comes from the **zer0-mistakes** theme, consumed as the published gem `jekyll-theme-zer0`. Layouts, includes, and Bootstrap assets ship in the gem; the site keeps only thin local wrappers plus `_data/` (Jekyll never loads data files from theme gems) and a CSS override hook. The vault stays almost purely content.

Deployment is a single path, described in [[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]]: push to `main`, and `.github/workflows/pages.yml` checks out the repo, builds with Jekyll plus the `_plugins/` bridge, and deploys the artifact to GitHub Pages. No servers, no runtime, no rollback procedure beyond `git revert`.

## Why this shape works

The [[wiki/concepts/prd-machine|PRD Machine]] concept imagined AI generating structured documents through an API-driven backend. The engine that actually runs here inverts that: the agent works *inside* the repository, on files, with git as the audit log and the static build as the only runtime. Three properties fall out of that inversion:

1. **Everything is reviewable.** An AI-authored post is a diff before it is a page.
2. **Everything is linked.** Wikilinks are cheap to write, verified by lint, and visualized by the graph.
3. **Everything is portable.** The vault opens in any Obsidian install; the site builds on any machine with Ruby.

Obsidian in, GitHub Pages out — with an agent doing the typing in between.
