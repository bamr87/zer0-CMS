---
type: concept
title: "Transport Selection"
created: 2026-08-08
updated: 2026-08-08
tags:
  - concept
  - architecture
  - transport
status: developing
confidence: medium
related:
  - "[[Obsidian CLI]]"
  - "[[ACP and MCP Layering]]"
  - "[[Agent Bridge Plugins]]"
---

# Transport Selection

The question every Claude + Obsidian setup answers, explicitly or by accident: *how does the agent actually touch the vault?* As of 2026-08 there are four live answers with materially different trade-offs.

## The Four Transports

| Transport | Needs Obsidian running | Needs a plugin | Notes |
|---|---|---|---|
| **Filesystem** (Read/Write/Edit) | No | No | Ultimate fallback. No vault semantics — an agent can write a broken wikilink and nothing objects. |
| **Obsidian CLI** | Partially | No (core feature, opt-in) | First-party. Vault-aware: backlinks, orphans, tags, Bases queries. Requires 1.12.7+ (Source: [[obsidian-cli-documentation]]). |
| **MCP server** (mcp-obsidian, MCPVault, obsidian-mcp) | Varies | Local REST API for some | Ecosystem-standard. Local-REST-API-based servers require a running Obsidian; direct-filesystem servers like MCPVault do not. |
| **Editor bridge** (WebSocket/ACP) | Yes | Yes | The only transport carrying live session state — selection, active file (Source: [[claude-code-ide]]). |

## The Selection Rule

Prefer the most vault-aware transport that the environment actually supports, and degrade explicitly rather than silently.

The CLI's arrival changes the default. Before 1.12.7, choosing between filesystem and an MCP server was a real trade between semantics and setup cost; a vault-aware transport meant installing a plugin and keeping Obsidian open. Now the semantic option is first-party and plugin-free, which makes "filesystem plus hand-rolled wikilink parsing" harder to justify.

## Why Degrade Explicitly

A transport that silently falls back changes correctness guarantees without telling anyone. Filesystem writes bypass every vault invariant the CLI would enforce — link resolution, alias handling, property typing. An agent that thinks it wrote a valid backlink and did not will corrupt the graph slowly and invisibly.

Detection belongs at setup time, recorded in config, not re-derived per call.

> [!gap] Whether the Obsidian CLI requires the GUI process for non-GUI commands is unresolved (see [[Obsidian CLI]] §Open Questions). That answer determines whether the CLI is viable in headless CI, which is the difference between a developer convenience and an automation substrate.
