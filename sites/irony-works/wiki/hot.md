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
  - "[[Research: Obsidian CLI Headless Viability (2026-08)]]"
  - "[[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]"
---

# Recent Context

Navigation: [[index]] | [[log]] | [[overview]]

## Last Updated

2026-08-08: Second autoresearch run — **Obsidian CLI headless viability**, the open question the first run flagged as highest-leverage. 3 rounds, 6 searches, 3 fetches, 6 GitHub API reads. 5 new pages + synthesis; 3 existing pages updated. **Question resolved.**

## Key Recent Facts

- **The Obsidian CLI cannot run headless. Every command requires the running desktop app.** It is a remote control, not a library: it finds Obsidian through an **IPC socket keyed to the display**, so without `DISPLAY` it reports "unable to find Obsidian."
- **Obsidian refuses to support it.** A maintainer closed a docs request with "Headless Obsidian CLI is not something we *officially* support"; a separate AI-agent headless question was closed with "not the right place to ask." The gap is deliberate.
- **Xvfb works but is unfit for CI**: needs `--disable-gpu --disable-software-rasterizer`, `DISPLAY=:99`, and manual `SingletonLock` cleanup after any ungraceful shutdown — an OOM-killed run poisons the next one. The reference implementation (`obsidianless`) was created and abandoned the same day, 11 stars.
- **[[obsidian-headless]] is a different product** — official, actively maintained (212★), but Sync/Publish only, with none of the CLI's note commands. It ships **no license file**.
- **Licensing gate**: the CLI is early-access behind a Catalyst license ($25 one-time), separate from Sync (medium-high confidence).
- **A false claim was corrected**, not overwritten: [[Obsidian CLI]] had said the CLI needs "no running Obsidian instance for many operations." Struck with a visible `[!warning]`.

## Recent Changes

- Created: [[obsidian-cli-official-page]], [[obsidian-official-headless-stance]], [[obsidianless-project]], [[obsidian-headless]], [[Headless Agent Automation]], [[Research: Obsidian CLI Headless Viability (2026-08)]]
- Updated: [[Obsidian CLI]], [[Transport Selection]], [[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]
- Vault: 19 pages, all wikilinks resolving, excluded from the Jekyll build

## Active Threads

- **Direct consequence for this repo**: `germinate.yml` and `alanis-gate.yml` run headless on `ubuntu-latest`. Filesystem is the only viable CI transport; never wire the Obsidian CLI into those workflows.
- Remaining leads: has the CLI left Catalyst early access? Does macOS need a `DISPLAY` equivalent? Why does the official headless repo ship unlicensed?
- Still unfetched from run 1: Agentic Copilot and Agent Client primary sources; which plugin implements ACP for Obsidian.
