---
type: concept
title: "ACP and MCP Layering"
created: 2026-08-08
updated: 2026-08-08
tags:
  - concept
  - protocol
  - acp
  - mcp
  - architecture
status: developing
confidence: high
related:
  - "[[Agent Client Protocol]]"
  - "[[agent-client-protocol-docs]]"
  - "[[Agent Bridge Plugins]]"
---

# ACP and MCP Layering

ACP and MCP are complementary layers of one stack, not competing standards. Confusing them produces bad integration architecture.

## The Split

```
Human ──▶ Editor ──[ ACP ]──▶ Agent ──[ MCP ]──▶ Tools / Data
          (outer layer)                (inner layer)
```

- **ACP** standardizes how an *editor* talks to an *agent*: session lifecycle, file context, diffs to render, permission prompts. The outer layer.
- **MCP** standardizes how an *agent* reaches *tools and data*: servers exposing callable functions and resources. The inner layer.

ACP re-uses MCP's JSON representations where it can, adding types for coding-UX elements MCP has no opinion about — diff display among them (Source: [[agent-client-protocol-docs]]).

## Why It Matters for a Vault

An Obsidian integration must choose which layer it occupies, and the choice determines what it is exposed to:

- **MCP server for the vault** — any MCP-speaking agent reads and writes notes. The vault is a *tool*.
- **ACP client in the editor** — any ACP-speaking agent drives the editing session. The vault is a *workspace*.

[[claude-code-ide]] is the interesting hybrid: it runs an MCP server over WebSocket inside Obsidian to serve editor context. It occupies the inner layer to deliver what is conceptually outer-layer information — a workaround for the era before ACP support in the vault was routine.

## Consequence

Betting on the inner layer means betting the vault is data. Betting on the outer layer means betting the vault is where work happens. A knowledge base that only ever gets read is well served by MCP; one that gets *written into* during a session wants the editor to be in the loop.

Neither layer models a link graph, contradiction tracking, or synthesis. Those remain application concerns — which is precisely the ground a wiki skill occupies (see [[Agent Bridge Plugins]] §The Squeeze).
