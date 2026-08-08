---
type: meta
title: "Operation Log"
created: 2026-08-08
updated: 2026-08-08
tags:
  - meta
  - log
status: evergreen
related:
  - "[[index]]"
  - "[[hot]]"
---

# Operation Log

Append-only. Newest entries at the top.

---

## [2026-08-08] autoresearch | Claude + Obsidian Ecosystem Refresh

- Vault scaffolded this session (first operation in this vault)
- Rounds: 2 (broad sweep across 5 angles, then primary-source gap fill)
- Searches: 5 WebSearch · Fetches: 4 WebFetch + 1 redirect retry + 3 GitHub API reads
- Sources found: 4 filed
- Pages created: [[obsidian-cli-documentation]], [[obsidian-changelog-2026]], [[agent-client-protocol-docs]], [[github-metrics-snapshot-2026-08-08]], [[Obsidian CLI]], [[kepano-obsidian-skills]], [[Agent Client Protocol]], [[claude-code-ide]], [[claude-obsidian]], [[Agent Bridge Plugins]], [[ACP and MCP Layering]], [[Transport Selection]]
- Link integrity: all wikilinks resolve; [[claude-obsidian]] was created to close the one dead link the check found
- Synthesis: [[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]
- Key finding: Obsidian ships both the interface agents call (CLI, 1.12.7+) and the instructions telling them how (kepano's skills), absorbing the third-party integration layer; what survives is session context and synthesis, not vault access
- Contradictions resolved: 3 (obsidian-skills star level and velocity, CLI ship date, mcp-obsidian stars) — all settled against primary sources over secondary write-ups
- Open questions filed: 6
- Fetch failures: 1 recoverable (`help.obsidian.md/cli` → 301 to `obsidian.md/help/cli`, retried successfully)
