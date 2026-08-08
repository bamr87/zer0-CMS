---
type: source
title: "Obsidian's Official Stance on Headless CLI"
source_type: primary-issue-tracker
author: Obsidian team (lishid, sigrunixia) and community filers
url: https://github.com/obsidianmd/obsidian-help/issues/1070
date_accessed: 2026-08-08
created: 2026-08-08
updated: 2026-08-08
tags:
  - source
  - obsidian
  - headless
  - primary
status: current
confidence: high
related:
  - "[[Obsidian CLI]]"
  - "[[obsidian-headless]]"
  - "[[Headless Agent Automation]]"
  - "[[Research: Obsidian CLI Headless Viability (2026-08)]]"
---

# Obsidian's Official Stance on Headless CLI

Three primary artifacts from Obsidian's own repositories, read via authenticated API. Together they establish that headless CLI operation is **explicitly not supported**, and that the question has been asked and closed twice.

## Artifact 1 — obsidian-help issue #1070 (the definitive statement)

"CLI docs: add troubleshooting for running the GUI app + CLI on headless Linux (Xvfb, GPU flags, DISPLAY)". Filed 2026-03-26 by `brettdavies`. **Closed**, 3 comments.

The filer requested docs for running the desktop app under Xvfb so the CLI can connect, explicitly distinguishing this from Headless Sync/Publish. An Obsidian team member (`sigrunixia`) replied:

> "As Headless Obsidian CLI is not something we *officially* support, we wouldn't add it to our main help docs. This is better content for the Obsidian Hub, or the Share and Showcase section of our forums. If we ever get an Headless Obsidian CLI for the main app (and not just Publish an[d Sync])…"

Confidence: high. This is a maintainer speaking on the vendor's issue tracker.

The issue also documents the exact technical requirements, which the vendor declined to publish:

1. **`--disable-gpu --disable-software-rasterizer`** — Obsidian's Chromium GPU process crashes under Xvfb (`Exiting GPU process due to errors during initialization`).
2. **`DISPLAY` set to the Xvfb display** (e.g. `:99`) — the CLI needs it to locate the running instance's **IPC socket**; without it the CLI reports "unable to find Obsidian."
3. **Singleton lock cleanup** — after SIGKILL or OOM, `SingletonLock` / `SingletonSocket` / `SingletonCookie` in `~/.config/obsidian/` block restart and must be removed manually.

## Artifact 2 — obsidian-headless issue #8 (the deflected question)

"Support for headless usage of Obsidian CLI for server/Docker environments". Filed 2026-03-05 by `self-made-boy`, asking whether the CLI can manage notes without the GUI "to allow AI agents or other automated tools to manage notes". **Closed** with a single comment from `lishid`:

> "Hi there, this is not the right place to discuss or ask questions. Please head to https://forum.obsidian.md/ instead."

The question received no technical answer. Confidence: high.

## Artifact 3 — the obsidianmd/obsidian-headless repository

Description: "Headless client for Obsidian Sync. Sync your vaults from the command line without the desktop app." Created 2026-02-27 · 212 stars · 22 forks · last push 2026-07-30 · 10 open issues · **no license file**.

Its scope is Sync and Publish. It does not control the desktop app and does not expose the CLI's note-manipulation surface.

## What This Contributes

The mechanism detail in artifact 1 is the most useful thing here: the CLI locates Obsidian through an **IPC socket keyed to the display**. That explains *why* the running-app requirement is architectural rather than a policy choice — the CLI is a client to a running process, not a library over the vault.

> [!gap] The absence of a license on the official `obsidian-headless` repository was read from the API (`license: null`). Whether a license exists in-tree but unrecognized by GitHub's detector was not checked.
