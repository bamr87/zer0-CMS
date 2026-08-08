---
type: entity
entity_type: repository
title: "kepano/obsidian-skills"
created: 2026-08-08
updated: 2026-08-08
tags:
  - entity
  - obsidian
  - claude-skills
  - first-party
status: current
confidence: high
related:
  - "[[github-metrics-snapshot-2026-08-08]]"
  - "[[Obsidian CLI]]"
  - "[[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]"
---

# kepano/obsidian-skills

Agent Skills published by Steph Ango (kepano), Obsidian's CEO, teaching Claude Code to read and write Obsidian's file formats correctly.

## Metrics (2026-08-08)

44,450 stars · 3,176 forks · created 2026-01-02 · last push 2026-06-08 · MIT (Source: [[github-metrics-snapshot-2026-08-08]]).

## What It Is

Five skills covering the syntax of each Obsidian file type: Markdown with wikilinks, frontmatter properties, Bases database queries, JSON Canvas spatial maps, and the Obsidian CLI. A `defuddle` skill strips clutter from web content before ingestion.

The pitch is correctness, not capability: an agent that writes a `.canvas` file without corrupting it, and Bases queries that parse. This is the vendor encoding its own formats as agent instructions rather than leaving each integration to reverse-engineer them.

## Significance

The repository is the clearest signal that format-level agent support is now first-party. Combined with [[Obsidian CLI]], Obsidian ships both the interface agents call and the instructions telling agents how to call it.

Its MIT license and skill-based packaging mean downstream tools can vendor the skills directly rather than reimplementing format handling.

## Maintenance Signal

Last push 2026-06-08 — two months before this snapshot. Star count continues climbing while commits do not; popularity and maintenance have decoupled.

> [!gap] Whether the two-month gap reflects completion (the formats are stable, the skills are done) or drift is not established. Bases shipped changes in 1.13.2 and 1.13.4 *after* that last push (Source: [[obsidian-changelog-2026]]), so the Bases skill may lag the current syntax. Unverified.

## Contested Claims

Circulating star figures disagree sharply — 13,900+ "within weeks", 35.9k "mid-2026", 44,228 on 2026-06-08, and a viral X post claiming "40,000 stars in a few weeks". The API figure is 44,450 with a 2026-01-02 creation date, making the growth roughly seven months, not "a few weeks" (Source: [[github-metrics-snapshot-2026-08-08]]).
