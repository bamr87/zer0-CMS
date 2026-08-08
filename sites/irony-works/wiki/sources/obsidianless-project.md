---
type: source
title: "obsidianless (community headless workaround)"
source_type: repository
author: lucastraba
url: https://github.com/lucastraba/obsidianless
date_accessed: 2026-08-08
created: 2026-08-08
updated: 2026-08-08
tags:
  - source
  - obsidian
  - headless
  - workaround
status: current
confidence: medium
related:
  - "[[Headless Agent Automation]]"
  - "[[obsidian-headless]]"
  - "[[Research: Obsidian CLI Headless Viability (2026-08)]]"
---

# obsidianless (community headless workaround)

The community answer to the gap Obsidian declined to document: run the full desktop app under a virtual display so the CLI has something to talk to.

## Metrics

11 stars · created 2026-03-11 · **last push 2026-03-11** · MIT (read from GitHub API, confidence: high).

Created and abandoned the same day. Five months stale at time of reading.

## Technique

- **Xvfb `:99`** supplies a virtual framebuffer so Obsidian believes it has a monitor.
- **Docker** packages the stack with volume mounts for vault files and config.
- **Config injection**: writes `"cli": true` into `~/.config/obsidian/obsidian.json` before startup, bypassing the GUI toggle that normally enables the CLI. The author identified this flag by reverse-engineering Obsidian's Electron source.

Claims 80+ commands across file operations, full-text search with context, tasks, daily notes, frontmatter, plugin management, and vault queries (confidence: medium — author's own README).

## Requirements

- **Obsidian Catalyst license ($25 one-time) required** — the CLI is early-access-gated (confidence: medium, corroborated elsewhere; see synthesis §Licensing Gate).
- **No Obsidian Sync subscription needed** — this is the distinction from [[obsidian-headless]]. Catalyst ≠ Sync; both claims hold simultaneously.
- Community plugins work normally.

## Assessment

The technique is sound and matches the requirements independently documented in obsidian-help issue #1070 (Source: [[obsidian-official-headless-stance]]) — Xvfb, GPU flags, DISPLAY-keyed IPC socket. Two parties reverse-engineered the same answer.

The maintenance signal is the problem. A single-day repository with 11 stars, unmaintained for five months, is not a dependency for production CI. It is a proof of concept that the approach works, and a specification of what you would have to maintain yourself.

> [!gap] The 80+ command claim and the Catalyst requirement were not verified by running the project. Star and push dates are API-verified; feature claims are not.
