---
type: source
title: "Agent Client Protocol Documentation"
source_type: official-documentation
author: Zed Industries and ACP contributors
url: https://agentclientprotocol.com/get-started/introduction
date_published: 2026
date_accessed: 2026-08-08
created: 2026-08-08
updated: 2026-08-08
tags:
  - source
  - acp
  - protocol
status: current
confidence: high
related:
  - "[[Agent Client Protocol]]"
  - "[[ACP and MCP Layering]]"
  - "[[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]"
---

# Agent Client Protocol Documentation

Combined primary reading of the ACP specification site and Zed's ACP landing page.

## Key Claims

- ACP standardizes communication between editors and coding agents, explicitly modeled on how LSP standardized language servers (confidence: high).
- Transport is **JSON-RPC over stdio** for local agents run as subprocesses; HTTP and WebSocket support for remote agents is work in progress (confidence: high).
- ACP "re-uses the JSON representations used in MCP where possible" while adding custom types for agentic coding UX such as diff display (confidence: high).
- Named agents include Claude Agent, Gemini CLI, Codex CLI, GitHub Copilot, Cursor, Devin, OpenHands, and Cline, among 50+ listed integrations (confidence: medium — count is from Zed's marketing page, not an audited registry).
- Supporting editors include Zed, Visual Studio Code, JetBrains IDEs, Neovim, Emacs, and **Obsidian** (confidence: medium — same caveat).
- Zed's timeline: ACP announced 2025-08-27 with Gemini CLI; Claude Code via ACP 2025-09-03; JetBrains collaboration 2025-10-06; Codex 2025-10-16 (confidence: high).
- The protocol is open source under Apache license; Zed states "nothing touches our servers" when running third-party agents (confidence: medium — vendor claim about its own product).

## What This Contributes

ACP is the answer to a question the Obsidian ecosystem was asking independently: how does an editor talk to *any* agent rather than to Claude specifically. Obsidian appearing on the supported-editor list means the vault is being treated as an editor surface by a protocol that predates the Obsidian CLI.

The MCP relationship is the load-bearing detail — ACP and MCP are complementary layers, not competitors. See [[ACP and MCP Layering]].

> [!gap] The specification site itself lists no maintainer, version number, or date. The timeline and adoption list come from Zed's page, which is a vendor source for a protocol Zed originated.

## Sources

agentclientprotocol.com introduction and zed.dev/acp, both accessed 2026-08-08.
