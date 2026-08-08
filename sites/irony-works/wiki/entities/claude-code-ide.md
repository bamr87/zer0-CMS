---
type: entity
entity_type: plugin
title: "Claude Code IDE (Obsidian plugin)"
created: 2026-08-08
updated: 2026-08-08
tags:
  - entity
  - obsidian
  - plugin
  - agent-bridge
status: current
confidence: high
related:
  - "[[Agent Bridge Plugins]]"
  - "[[Transport Selection]]"
  - "[[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]"
---

# Claude Code IDE (Obsidian plugin)

Community plugin by **petersolopov** that shares live editor context from Obsidian to Claude Code.

## Facts

- Version 0.2.5 · ~13,000 downloads · created ~5 months before 2026-08-08, last updated ~2 months before · MIT · desktop only.
- Runs an **MCP server over WebSocket inside Obsidian**. Claude Code connects via the `/ide` command, then selects Obsidian.
- Shares the active file, open files, and selected text in real time.
- Access is **read-only** on selections and file names; the connection is local-only with no external network exposure; zero configuration beyond install.

## Significance

This is the clean example of the [[Agent Bridge Plugins]] category: it does not try to be a vault CRUD layer. It solves a narrower problem — the agent knowing *what you are looking at* — which no amount of filesystem access provides.

That framing is why it survives the arrival of [[Obsidian CLI]]. A CLI can read any file; it cannot know which file has your cursor in it. Editor context is the durable niche for in-vault plugins once first-party tooling absorbs file operations.

The read-only posture is a deliberate security boundary: the plugin exposes attention, not authority.
