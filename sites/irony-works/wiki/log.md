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

## [2026-08-08] autoresearch | Obsidian CLI Headless Viability

- Topic selection: DragonScale Mechanism 4 unavailable (`scripts/boundary-score.py` absent → BOUNDARY_MODE=0); fell through to user choice, offered from the prior session's filed open questions
- Rounds: 3 (broad sweep, primary-source verification, licensing-claim check)
- Searches: 6 WebSearch · Fetches: 3 WebFetch + 6 GitHub API reads (2 issues, 2 issue-comment threads, 3 repos)
- Pages created: [[obsidian-cli-official-page]], [[obsidian-official-headless-stance]], [[obsidianless-project]], [[obsidian-headless]], [[Headless Agent Automation]]
- Synthesis: [[Research: Obsidian CLI Headless Viability (2026-08)]]
- Pages updated: [[Obsidian CLI]] (corrected a false claim), [[Transport Selection]] (environment qualifier added), [[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]] (open question struck through as resolved)
- Key finding: the Obsidian CLI is a remote control over a display-keyed IPC socket, not a library — every command needs the running desktop app, and Obsidian states headless CLI is explicitly unsupported
- Correction filed: [[Obsidian CLI]] previously claimed the CLI needs "no running Obsidian instance for many operations". False. Corrected in place with a visible `[!warning]` rather than a silent edit
- Consequence for this repo: filesystem is the only viable CI transport; `germinate.yml` and `alanis-gate.yml` run headless on ubuntu-latest and would fail at the IPC socket
- Open questions filed: 4 (Catalyst status, macOS IPC behavior, roadmap for a real headless CLI, missing license on obsidian-headless)

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
