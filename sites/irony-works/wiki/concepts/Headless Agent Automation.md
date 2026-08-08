---
type: concept
title: "Headless Agent Automation"
created: 2026-08-08
updated: 2026-08-08
tags:
  - concept
  - headless
  - ci
  - agents
  - architecture
status: developing
confidence: high
related:
  - "[[Obsidian CLI]]"
  - "[[obsidian-headless]]"
  - "[[Transport Selection]]"
  - "[[obsidian-official-headless-stance]]"
---

# Headless Agent Automation

The constraint that separates a desktop convenience from an automation substrate: **can the tool run with no display, no login session, and no human?** For the Obsidian CLI the answer is no, and the reason is architectural rather than incidental.

## The Mechanism

The CLI is a **client to a running process**, not a library over the vault. It locates Obsidian through an **IPC socket keyed to the display**, which is why `DISPLAY` must be set for the CLI to find an instance at all — without it, the CLI reports "unable to find Obsidian" (Source: [[obsidian-official-headless-stance]]).

That single fact determines everything downstream. A library could be linked into CI. A client needs its server alive, which means an Electron app, which means a display, which means Xvfb.

## The Three Options

| Approach | Works in CI | Vault semantics | Maintained |
|---|---|---|---|
| **Obsidian CLI direct** | No — requires the running app | Full | Vendor, but desktop-only |
| **Xvfb + Docker + config injection** | Yes, fragile | Full | Community; the reference implementation is abandoned (Source: [[obsidianless-project]]) |
| **[[obsidian-headless]] + filesystem** | Yes | None — plain files | Vendor, actively pushed |

The middle row costs `--disable-gpu --disable-software-rasterizer` (Chromium's GPU process crashes under Xvfb), a `DISPLAY` export, and manual cleanup of `SingletonLock`/`SingletonSocket`/`SingletonCookie` after any ungraceful shutdown — because an OOM-killed Electron app leaves locks that block restart (Source: [[obsidian-official-headless-stance]]).

That last item is what makes it unsuitable for unattended CI specifically. A workflow that dies mid-run poisons the next run's startup, and nothing in the stack cleans up after itself.

## The Support Boundary

Obsidian states the position plainly: headless CLI "is not something we *officially* support" and will not appear in the help docs (Source: [[obsidian-official-headless-stance]]). The gap is deliberate, not an oversight awaiting a patch.

The consequence for architecture is to **not build on the unsupported path**. An automation that depends on Xvfb-hosting a GUI app depends on undocumented behavior the vendor has declined to stabilize.

## The General Rule

When a vendor ships a first-party CLI, check whether it is a *library* or a *remote control* before designing automation around it. The command surface looks identical in both cases; the deployment envelope does not. A remote control inherits every requirement of the thing it controls — display, session, license, singleton locks — and those requirements surface only in the environment where they fail.

Prefer the vendor's *narrower* headless tool over a *wider* tool run in an unsupported mode. Less capability that is supported beats more capability that is reverse-engineered.
