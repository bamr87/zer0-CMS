---
type: source
title: "GitHub Metrics Snapshot 2026-08-08"
source_type: primary-api
author: GitHub REST API
url: https://api.github.com/repos/kepano/obsidian-skills
date_published: 2026-08-08
date_accessed: 2026-08-08
created: 2026-08-08
updated: 2026-08-08
tags:
  - source
  - metrics
  - primary
status: current
confidence: high
related:
  - "[[kepano-obsidian-skills]]"
  - "[[claude-obsidian]]"
  - "[[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]"
---

# GitHub Metrics Snapshot 2026-08-08

Direct GitHub REST API reads, taken to settle star-count claims that secondary sources report inconsistently.

## Measurements

| Repository | Stars | Forks | Created | Last push | License |
|---|---|---|---|---|---|
| `kepano/obsidian-skills` | 44,450 | 3,176 | 2026-01-02 | 2026-06-08 | MIT |
| `AgriciDaniel/claude-obsidian` | 10,560 | 1,222 | 2026-04-07 | 2026-08-01 | MIT |
| `MarkusPfundstein/mcp-obsidian` | 4,276 | 494 | 2024-11-29 | 2026-05-15 | MIT |

All figures confidence: high — read from the API, not from prose.

## Key Claims

- `kepano/obsidian-skills` stands at **44,450 stars** on 2026-08-08, having been created 2026-01-02 — roughly seven months to reach that figure (confidence: high).
- The same repository's last push is **2026-06-08**, two months stale at snapshot time (confidence: high).
- `mcp-obsidian` is at 4,276 stars, not the "3,000 stars" reported by a 2026 ecosystem survey (confidence: high).

## What This Contributes

This page exists because circulating star counts for `obsidian-skills` disagree: one write-up says 13,900+ "within weeks", another 35.9k "mid-2026", another 44,228 as of 2026-06-08, and a widely shared X post claims "40,000 stars in a few weeks". The API settles the level (44,450) and the API's `created_at` settles the velocity claim — see the contradiction analysis in [[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]].

Star counts are a popularity signal, not a quality or maintenance signal. The `pushed_at` field is the more informative column here.

## Sources

GitHub REST API `/repos/{owner}/{repo}`, accessed 2026-08-08 via authenticated `gh api`.
