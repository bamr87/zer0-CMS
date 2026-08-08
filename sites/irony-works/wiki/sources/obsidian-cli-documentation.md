---
type: source
title: "Obsidian CLI Documentation"
source_type: official-documentation
author: Obsidian
url: https://obsidian.md/help/cli
date_published: 2026
date_accessed: 2026-08-08
created: 2026-08-08
updated: 2026-08-08
tags:
  - source
  - obsidian
  - cli
status: current
confidence: high
related:
  - "[[Obsidian CLI]]"
  - "[[Agent Bridge Plugins]]"
  - "[[Research: Claude + Obsidian Ecosystem Refresh (2026-08)]]"
---

# Obsidian CLI Documentation

Primary source for the official command-line interface. Authoritative on version requirements and command surface.

## Key Claims

- The CLI is introduced in Obsidian **1.12**; full functionality requires **1.12.7 or above** (confidence: high).
- Activation is manual: Settings → General → enable "Command line interface", then follow the registration prompt (confidence: high).
- Registration differs per OS — Windows installs a terminal redirector, macOS symlinks `/usr/local/bin/obsidian`, Linux copies the binary to `~/.local/bin/obsidian` (confidence: high).
- Command surface spans file operations (create, read, append, prepend, move, rename, delete), search and discovery (search with context, backlinks, outgoing links, orphaned notes), content management (daily notes, tags, tasks, properties, aliases), organization (bases queries, bookmarks, templates), and developer tools (screenshot, JavaScript evaluation, DOM inspection, CSS analysis) (confidence: high).
- Stated purpose is "scripting, automation, and integration with external tools"; the docs explicitly name **agentic coding tools** using developer commands to "automatically test and debug" plugins (confidence: high).

## What This Contributes

This is the document that settles the version question. Secondary write-ups place the CLI at "1.12, February 2026" while the changelog records a standalone binary at 1.12.7 (March 23, 2026); the official help page reconciles both — introduced at 1.12, fully functional at 1.12.7. See [[Obsidian CLI]] for the resolved timeline.

It also establishes that agent support is an *intended* use case rather than a community appropriation. The vendor documents automation for agentic tools directly, which reframes every third-party bridge as competing with a first-party surface.

## Sources

Official Obsidian help documentation, accessed 2026-08-08.
