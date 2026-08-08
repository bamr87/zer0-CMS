---
type: source
title: "Obsidian CLI Product Page"
source_type: official-documentation
author: Obsidian
url: https://obsidian.md/cli
date_accessed: 2026-08-08
created: 2026-08-08
updated: 2026-08-08
tags:
  - source
  - obsidian
  - cli
  - headless
status: current
confidence: high
related:
  - "[[Obsidian CLI]]"
  - "[[obsidian-headless]]"
  - "[[Headless Agent Automation]]"
  - "[[Research: Obsidian CLI Headless Viability (2026-08)]]"
---

# Obsidian CLI Product Page

The vendor's own CLI page. Settles the running-app question in one sentence and, on the same page, markets headless agent use cases that the CLI does not deliver.

## Key Claims

- **"Note that the Obsidian app must be running."** Stated explicitly (confidence: high). This is the answer to whether the CLI works headless: it does not, natively.
- Available on macOS, Windows, and Linux; no mobile CLI (confidence: high).
- Command examples span daily notes, search, tasks, file creation, tag viewing, file comparison, DevTools access, plugin reloading, JavaScript execution, and DOM querying (confidence: high).
- The page promotes headless use cases: "Run Obsidian Sync without a GUI", "Automate remote backups", **"Give agentic tools access to a vault without access to your full computer"**, and "Sync a shared team vault to a server that feeds other tools" (confidence: high).

## What This Contributes

The page conflates two products. The headless bullets describe [[obsidian-headless]] — a separate Sync/Publish client — while the command surface above them belongs to the CLI, which requires the GUI. A reader scanning for "can agents drive my vault from a server" finds an encouraging answer next to a disqualifying one.

The agentic-tools bullet is the sharpest instance. Giving "agentic tools access to a vault without access to your full computer" is precisely the CI use case that the CLI's running-app requirement forecloses; what the bullet actually describes is syncing a vault to a server, after which the agent works on plain files with no CLI involved.

> [!gap] The page does not state what happens when the app is not running. A secondary source reports the first command auto-launches Obsidian; unverified against primary documentation.

> [!gap] The page does not mention the Catalyst early-access requirement. See [[Research: Obsidian CLI Headless Viability (2026-08)]] §Licensing Gate.
