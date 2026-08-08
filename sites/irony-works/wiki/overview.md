---
type: meta
title: "Overview"
created: 2026-08-08
updated: 2026-08-08
tags:
  - meta
  - overview
status: evergreen
related:
  - "[[index]]"
  - "[[log]]"
  - "[[hot]]"
---

# Overview

A research vault living inside the [Irony Works](../README.md) repository. It is separate from `vault/` — that one is the encyclopedia of irony this project publishes; this one is the knowledge base *about the tooling* used to build it.

## What's Here

One research thread so far: the **Claude + Obsidian ecosystem** as of August 2026 — how agents actually connect to Obsidian vaults, and what changed when Obsidian shipped first-party agent tooling. Start at [[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]].

## Structure

```
wiki/
├── index.md        # master catalog
├── log.md          # append-only operation record, newest first
├── hot.md          # ~500-word recent-context cache
├── overview.md     # this file
├── sources/        # one page per reference, with confidence ratings
├── entities/       # products, repos, protocols, plugins
├── concepts/       # patterns and frameworks
├── questions/      # research syntheses
├── comparisons/    # side-by-side analyses (empty)
└── meta/           # dashboards and lint reports (empty)
```

## Not Published

`wiki/` is excluded from the Jekyll build in `_config.yml`. Research notes stay local; only `vault/` becomes the public site. Keeping them in the same repo means the research that informs the project travels with it in git history, without leaking drafts to the web.

## Reading Order for a New Session

1. [[hot]] — recent context, ~500 words
2. [[index]] — full catalog
3. Individual pages only as needed
