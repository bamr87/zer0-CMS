---
type: entity
entity_type: product
title: "obsidian-headless"
created: 2026-08-08
updated: 2026-08-08
tags:
  - entity
  - obsidian
  - headless
  - first-party
status: current
confidence: high
related:
  - "[[Obsidian CLI]]"
  - "[[obsidian-official-headless-stance]]"
  - "[[Headless Agent Automation]]"
---

# obsidian-headless

Obsidian's official CLI-only client for **Sync and Publish**. Routinely confused with [[Obsidian CLI]]; the two are different products with non-overlapping scope.

## Facts

`obsidianmd/obsidian-headless` · 212 stars · 22 forks · created 2026-02-27 · last push 2026-07-30 · 10 open issues · **no license file detected** (Source: [[obsidian-official-headless-stance]]).

Requires Node.js 22+. Commands are `ob`-prefixed: `ob login`, `ob sync-list-remote`, `ob sync-setup`, `ob sync`, `ob sync --continuous`.

## Scope — and Its Limits

It syncs and publishes vaults from a server with no desktop app and no Xvfb. It does **not** control the Obsidian application and does **not** expose the CLI's note-manipulation surface — no `create`, `search`, `daily`, backlinks, tags, or Bases queries.

This is the distinction that makes vendor marketing misleading. The [[obsidian-cli-official-page]] lists "Give agentic tools access to a vault without access to your full computer" among headless benefits; that capability belongs here, and here it means *the files arrive on the server*. What the agent does next is plain filesystem work, with no Obsidian semantics available.

## The Practical Pattern

`obsidian-headless` is a **transport for bytes, not a transport for vault operations**. The workable server architecture it enables:

```
Desktop Obsidian ──Sync──▶ obsidian-headless on server ──▶ plain .md files ──▶ agent (filesystem)
```

The agent gets current files without the desktop app. It does not get link resolution, alias handling, or property typing — those live in the app the CLI talks to. See [[Transport Selection]].

## Signals

Last push 2026-07-30 — actively maintained, unlike the community workarounds around it. Ten open issues on a five-month-old repo. The missing license is a genuine adoption risk for commercial use: no license means no granted rights by default.
