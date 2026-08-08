---
type: meta
title: "Wiki Index"
created: 2026-08-08
updated: 2026-08-08
tags:
  - meta
  - index
status: evergreen
related:
  - "[[overview]]"
  - "[[log]]"
  - "[[hot]]"
---

# Wiki Index

Last updated: 2026-08-08 | Total pages: 13 | Research sessions: 1

Navigation: [[overview]] | [[log]] | [[hot]]

---

## Concepts

- [[Agent Bridge Plugins]] — plugins connecting external terminal agents to the vault; what survives first-party absorption (status: developing)
- [[ACP and MCP Layering]] — ACP is the editor↔agent outer layer, MCP the agent↔tools inner layer; complementary, not rival (status: developing)
- [[Transport Selection]] — the four live ways an agent touches a vault, and why silent fallback corrupts link graphs (status: developing)

## Entities

- [[Obsidian CLI]] — first-party vault scripting, 1.12.7+; the structural change of 2026 (product)
- [[kepano-obsidian-skills]] — Obsidian CEO's agent skills, 44,450★, MIT, two months unpushed (repository)
- [[Agent Client Protocol]] — Apache-licensed JSON-RPC editor↔agent standard from Zed (protocol)
- [[claude-code-ide]] — read-only editor-context bridge over local WebSocket, ~13k downloads (plugin)
- [[claude-obsidian]] — the skill collection that built this vault, 10,560★, actively maintained (repository)

## Sources

- [[obsidian-cli-documentation]] — official Obsidian CLI help (confidence: high)
- [[obsidian-changelog-2026]] — official 2026 release record (confidence: high)
- [[agent-client-protocol-docs]] — ACP spec site + Zed's ACP page (confidence: high/medium)
- [[github-metrics-snapshot-2026-08-08]] — primary GitHub API metrics (confidence: high)

## Research Syntheses

- [[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]] — the ecosystem's first-party absorption of the integration layer; 3 contradictions resolved, 6 open questions

---

## Conventions

- All notes carry YAML frontmatter: `type`, `status`, `created`, `updated`, `tags`
- Wikilinks use `[[Note Name]]`; filenames are unique, no paths needed
- `log.md` is append-only, newest entry at the TOP
- Claims cite their source inline: `(Source: [[Page]])`
- Unverified claims are flagged `> [!gap]`, never quietly smoothed over
