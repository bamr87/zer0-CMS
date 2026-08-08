---
type: concept
title: "Agent Bridge Plugins"
created: 2026-08-08
updated: 2026-08-08
tags:
  - concept
  - obsidian
  - agents
  - architecture
status: developing
confidence: medium
related:
  - "[[Obsidian CLI]]"
  - "[[claude-code-ide]]"
  - "[[Agent Client Protocol]]"
  - "[[Transport Selection]]"
---

# Agent Bridge Plugins

A plugin category that did not exist in 2025: in-vault plugins whose sole job is to connect an external coding agent to the editor, rather than to embed a chat panel or call a model API themselves.

## The Distinction

A **copilot plugin** brings the model into the vault — chat sidebar, inline completion, its own API key. An **agent bridge** does the reverse: it exposes the vault (or the editing session) to an agent that lives outside, in a terminal.

Examples in circulation as of 2026-08:
- [[claude-code-ide]] (petersolopov) — MCP server over WebSocket, read-only editor context, `/ide` handshake
- Agentic Copilot (Spencer Marx) — Claude Code, OpenCode, and Gemini CLI as an in-vault workspace copilot; Show HN late March 2026
- Agent Client plugin — multi-agent, built on [[Agent Client Protocol]]

## Why the Category Formed

Terminal agents became the primary interface for serious work, and they were blind to editor state. The bridge supplies the one thing a filesystem cannot: *which file the human is actually looking at*.

## The Squeeze

[[Obsidian CLI]] absorbs the vault-CRUD half of this category. Any bridge justified by "lets the agent read and write your notes" now competes with a first-party binary that needs no plugin (Source: [[obsidian-cli-documentation]]).

What survives the squeeze is what the CLI structurally cannot provide:

1. **Live editor context** — cursor position, selection, active pane. Session state, not file state.
2. **Agent-agnostic routing** — [[Agent Client Protocol]] bridges bet on outliving any single agent vendor.
3. **Synthesis** — link graphs, contradiction tracking, compounding structure. Above the transport layer entirely.

The pattern generalizes: when a platform ships a first-party interface, integrations differentiated only by *access* get commoditized, and integrations differentiated by *interpretation* do not.

> [!gap] Download and maintenance figures were verified for [[claude-code-ide]] only. Agentic Copilot and Agent Client are catalogued from search summaries, not primary sources.
