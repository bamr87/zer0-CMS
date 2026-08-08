---
type: synthesis
title: "Research: Claude + Obsidian Ecosystem Refresh (2026-08)"
created: 2026-08-08
updated: 2026-08-08
tags:
  - research
  - synthesis
  - obsidian
  - claude
  - ecosystem
status: developing
confidence: medium
related:
  - "[[Obsidian CLI]]"
  - "[[kepano-obsidian-skills]]"
  - "[[Agent Client Protocol]]"
  - "[[claude-code-ide]]"
  - "[[Agent Bridge Plugins]]"
  - "[[ACP and MCP Layering]]"
  - "[[Transport Selection]]"
sources:
  - "[[obsidian-cli-documentation]]"
  - "[[obsidian-changelog-2026]]"
  - "[[agent-client-protocol-docs]]"
  - "[[github-metrics-snapshot-2026-08-08]]"
---

# Research: Claude + Obsidian Ecosystem Refresh (2026-08)

## Overview

The Claude + Obsidian integration layer is being absorbed by first-party tooling. Obsidian now ships both the interface agents call ([[Obsidian CLI]]) and the instructions telling agents how to call it ([[kepano-obsidian-skills]]), while an agent-agnostic protocol ([[Agent Client Protocol]]) claims the editor-to-agent seam. Third-party integrations differentiated purely by vault access are being commoditized; those differentiated by session context or synthesis are not.

## Key Findings

1. **The CLI is first-party and agent-aimed.** Obsidian's documentation names "agentic coding tools" as an intended consumer, covering file operations, backlinks, orphan detection, tags, and Bases queries (Source: [[obsidian-cli-documentation]]). This is vendor courtship, not tolerance.

2. **The CLI's ship date is two dates.** Introduced in 1.12; standalone binary at **1.12.7, 2026-03-23** (Source: [[obsidian-changelog-2026]]). Secondary write-ups collapse these into "1.12, February 2026", which is the origin of conflicting claims in circulation.

3. **`kepano/obsidian-skills` is at 44,450 stars but two months without a push** (last 2026-06-08, snapshot 2026-08-08) (Source: [[github-metrics-snapshot-2026-08-08]]). Popularity and maintenance have decoupled. Bases shipped changes in 1.13.2 and 1.13.4 *after* that last push, so the Bases skill may lag current syntax.

4. **A new plugin category has formed: [[Agent Bridge Plugins]].** These expose the vault or editing session to an agent living in a terminal, rather than embedding a model in the vault. [[claude-code-ide]] (v0.2.5, ~13k downloads, read-only, local WebSocket) is the clean specimen.

5. **ACP and MCP are complementary layers, not rivals** — ACP for editor↔agent, MCP for agent↔tools, with ACP re-using MCP's JSON where possible (Source: [[agent-client-protocol-docs]]). See [[ACP and MCP Layering]].

6. **Obsidian is listed as an ACP-supported editor** alongside Zed, VS Code, JetBrains, Neovim, and Emacs, among 50+ claimed agent integrations (Source: [[agent-client-protocol-docs]]) — the vault treated as an editor surface by a protocol indifferent to which agent connects.

7. **Bases is still moving.** Three releases in the 1.13 line touch it (Source: [[obsidian-changelog-2026]]). Any skill generating `.base` files targets a syntax under active revision.

## Key Entities

- [[Obsidian CLI]]: first-party vault scripting; the structural change of 2026
- [[kepano-obsidian-skills]]: vendor-authored agent skills, 44,450★, MIT
- [[Agent Client Protocol]]: Apache-licensed JSON-RPC editor↔agent standard from Zed
- [[claude-code-ide]]: read-only editor-context bridge, MCP over local WebSocket

## Key Concepts

- [[Agent Bridge Plugins]]: plugins connecting external agents to the vault, and what survives first-party absorption
- [[ACP and MCP Layering]]: outer editor layer vs inner tool layer
- [[Transport Selection]]: four live ways to touch a vault, and why silent fallback corrupts graphs

## Contradictions

- **Star counts for `obsidian-skills`.** Secondary sources report 13,900+ "within weeks", 35.9k "mid-2026", 44,228 on 2026-06-08, and a viral X post claiming "40,000 stars in a few weeks". The API reads **44,450** with `created_at` 2026-01-02 (Source: [[github-metrics-snapshot-2026-08-08]]). The level claims are stale-but-directionally-right; the *velocity* claim is wrong — roughly seven months, not a few weeks. Primary API wins.
- **CLI ship date.** "1.12, February 2026" (secondary, widely repeated) vs "standalone binary in 1.12.7, 2026-03-23" (primary changelog). Resolved in finding 2: both describe different milestones. Official docs confirm 1.12 introduction with 1.12.7+ required for full functionality (Source: [[obsidian-cli-documentation]]).
- **`mcp-obsidian` stars.** A 2026 survey reports "3,000 stars"; the API reads 4,276 (Source: [[github-metrics-snapshot-2026-08-08]]). Survey is stale.

## Open Questions

- Does the Obsidian CLI need the GUI process running for non-GUI commands? This decides whether it works headless in CI — the difference between a convenience and an automation substrate.
- Is `kepano/obsidian-skills`'s two-month push gap completion or drift? Specifically, does its Bases skill still match post-1.13.2 syntax?
- Which Obsidian plugin actually provides ACP support, and is it current? Obsidian's listing on Zed's page was not traced to a specific implementation.
- The "50+ ACP integrations" figure rests on a single vendor page for a Zed-originated protocol. No independent registry audit was performed.
- Agentic Copilot and Agent Client are catalogued from search summaries only; no primary source (repo, plugin page) was fetched for either. Budget-limited.
- Cards/List/Map Bases view versions were not confirmed against a primary 2025 changelog.

## Sources

- [[obsidian-cli-documentation]]: Obsidian, official help, accessed 2026-08-08
- [[obsidian-changelog-2026]]: Obsidian, official changelog, accessed 2026-08-08
- [[agent-client-protocol-docs]]: agentclientprotocol.com + zed.dev/acp, accessed 2026-08-08
- [[github-metrics-snapshot-2026-08-08]]: GitHub REST API, accessed 2026-08-08
