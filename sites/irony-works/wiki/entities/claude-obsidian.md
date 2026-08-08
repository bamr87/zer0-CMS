---
type: entity
entity_type: repository
title: "AgriciDaniel/claude-obsidian"
aliases:
  - claude-obsidian
created: 2026-08-08
updated: 2026-08-08
tags:
  - entity
  - obsidian
  - claude
  - plugin
status: current
confidence: high
related:
  - "[[github-metrics-snapshot-2026-08-08]]"
  - "[[Transport Selection]]"
  - "[[Agent Bridge Plugins]]"
---

# AgriciDaniel/claude-obsidian

The Claude Code plugin that scaffolded this vault and ran the research filed in it. Recorded here because a vault that documents an ecosystem while omitting its own tooling is describing everything except the instrument.

## Metrics (2026-08-08)

10,560 stars · 1,222 forks · created 2026-04-07 · last push 2026-08-01 · MIT (Source: [[github-metrics-snapshot-2026-08-08]]).

Four months old and actively maintained — last push one week before this snapshot, the freshest of the three repositories measured.

## What It Is

A skill collection rather than an Obsidian plugin: `wiki`, `wiki-ingest`, `wiki-query`, `wiki-lint`, `autoresearch`, `save`, `canvas`, and format references, invoked from Claude Code as slash commands. The vault is plain Markdown on disk, so the skills are instructions for how an agent should build and maintain a knowledge base — not a runtime.

Version 1.9.2 is installed on this machine. It defines a transport policy ([[Transport Selection]]) preferring the Obsidian CLI, then MCP, then filesystem.

## Position in the Ecosystem

It occupies the layer neither [[Obsidian CLI]] nor [[Agent Client Protocol]] addresses: what to *write*. The CLI moves bytes; ACP carries session state; this defines page schemas, link conventions, contradiction tracking, and hot-cache summarization.

That is the "synthesis" survival niche identified in [[Agent Bridge Plugins]] §The Squeeze — and it explains the growth curve. First-party absorption of transport does not threaten a tool whose product is structure.

## Resolved Elsewhere

A separate vault on this machine recorded an open question — claude-obsidian's own star count, last known ~8,633 on 2026-04-09. This snapshot answers it: **10,560 on 2026-08-08**, roughly +22% in four months.
