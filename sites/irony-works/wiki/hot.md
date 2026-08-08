---
type: meta
title: "Hot Cache"
created: 2026-08-08
updated: 2026-08-08T00:00:00
tags:
  - meta
  - hot-cache
status: evergreen
related:
  - "[[index]]"
  - "[[log]]"
  - "[[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]"
---

# Recent Context

Navigation: [[index]] | [[log]] | [[overview]]

## Last Updated

2026-08-08: Vault scaffolded and first autoresearch run completed — **Claude + Obsidian ecosystem refresh**. 2 rounds, 5 searches, 4 fetches, 3 GitHub API reads. 11 pages + synthesis filed.

## Key Recent Facts

- **First-party absorption is the story.** Obsidian ships the CLI agents call (introduced 1.12, standalone binary 1.12.7 on 2026-03-23) *and* kepano's skills teaching agents its formats. Third-party integrations differentiated only by vault access are being commoditized.
- **What survives**: live editor context (cursor, selection — a CLI structurally cannot know this) and synthesis (link graphs, contradiction tracking). Not file access.
- **`kepano/obsidian-skills`: 44,450★ but last pushed 2026-06-08** — two months stale while Bases shipped changes in 1.13.2 and 1.13.4. Popularity decoupled from maintenance.
- **ACP ≠ MCP rivalry.** ACP is the editor↔agent outer layer, MCP the agent↔tools inner layer; ACP re-uses MCP JSON where it can. Obsidian is listed as an ACP-supported editor.
- **Three secondary-source claims corrected against primary APIs/docs** — see the Contradictions section of the synthesis.

## Recent Changes

- Created: 4 source pages, 4 entity pages, 3 concept pages, 1 synthesis, plus index/log/hot/overview
- Vault location: `wiki/` inside the irony-works repo; excluded from the Jekyll site build so research never publishes to bamr87.github.io/irony-works
- Transport: filesystem (Obsidian CLI not installed on this machine)

## Active Threads

- Open question with the most leverage: **does the Obsidian CLI need the GUI running for non-GUI commands?** That decides headless-CI viability — convenience vs automation substrate.
- Unfetched leads for a next pass: Agentic Copilot and Agent Client plugins (catalogued from search summaries only); which Obsidian plugin actually implements ACP.
- This vault is new — 12 pages, no orphan/lint history yet.
