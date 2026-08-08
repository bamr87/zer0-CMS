---
type: entity
entity_type: protocol
title: "Agent Client Protocol"
aliases:
  - ACP
created: 2026-08-08
updated: 2026-08-08
tags:
  - entity
  - protocol
  - acp
status: current
confidence: medium
related:
  - "[[agent-client-protocol-docs]]"
  - "[[ACP and MCP Layering]]"
  - "[[Agent Bridge Plugins]]"
---

# Agent Client Protocol

An open JSON-RPC standard connecting code editors to coding agents, originated by Zed Industries and licensed Apache. ACP is to agent integration what LSP is to language tooling: a shared contract replacing bespoke per-editor work (Source: [[agent-client-protocol-docs]]).

## Mechanics

Local agents run as subprocesses over **JSON-RPC on stdio**. Remote-agent support over HTTP and WebSocket is explicitly work in progress. The wire format re-uses MCP's JSON representations where possible, adding types for agentic coding UX — diff display among them (Source: [[agent-client-protocol-docs]]).

## Adoption

Named agents: Claude Agent, Gemini CLI, Codex CLI, GitHub Copilot, Cursor, Devin, OpenHands, Cline — 50+ integrations claimed. Editors: Zed, VS Code, JetBrains, Neovim, Emacs, and **Obsidian** (Source: [[agent-client-protocol-docs]]).

Timeline from Zed: announced 2025-08-27 with Gemini CLI, Claude Code 2025-09-03, JetBrains 2025-10-06, Codex 2025-10-16.

## Why It Matters Here

Obsidian appearing as a supported editor means the vault is being addressed as an *editor surface* by a protocol that treats agents as interchangeable. That is the opposite bet from a Claude-specific plugin: ACP integrations survive a change of agent vendor.

For a knowledge vault the trade is real. ACP is designed around coding-agent UX — diffs, file context, multi-file edits. A wiki cares about link graphs and synthesis, which the protocol does not model. See [[ACP and MCP Layering]].

## Confidence Note

The adoption list and timeline come from Zed's own marketing page for a protocol Zed created. The specification site itself carries no maintainer, version, or date (Source: [[agent-client-protocol-docs]]).

> [!gap] The "50+ integrations" figure and Obsidian's listed support are unverified against an independent registry. Which Obsidian plugin provides ACP support, and whether it is current, was not established.
