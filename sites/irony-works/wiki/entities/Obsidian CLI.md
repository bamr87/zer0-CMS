---
type: entity
entity_type: product
title: "Obsidian CLI"
created: 2026-08-08
updated: 2026-08-08
tags:
  - entity
  - obsidian
  - cli
  - first-party
status: current
confidence: high
related:
  - "[[obsidian-cli-documentation]]"
  - "[[obsidian-changelog-2026]]"
  - "[[Agent Bridge Plugins]]"
  - "[[Transport Selection]]"
---

# Obsidian CLI

Obsidian's first-party command-line interface. It is the single most consequential development for agent-vault integration, because it makes the vault scriptable without any plugin, MCP server, or running GUI mediation layer.

## Timeline

- **1.12** — CLI introduced (Source: [[obsidian-cli-documentation]])
- **1.12.7, 2026-03-23** — ships as a standalone binary, replacing direct Electron-binary invocation; full functionality requires this version or above (Source: [[obsidian-changelog-2026]])

Secondary write-ups collapse these into "1.12, February 2026", which is why conflicting dates circulate. Both halves are true of different milestones.

## Capabilities

File operations (create, read, append, prepend, move, rename, delete), search and discovery (search with context, backlinks, outgoing links, orphaned notes), content management (daily notes, tags, tasks, properties, aliases), organization (bases queries, bookmarks, templates), and developer tools (screenshot, JavaScript evaluation, DOM inspection, CSS analysis) (Source: [[obsidian-cli-documentation]]).

Activation is opt-in: Settings → General → "Command line interface", then OS-specific registration — macOS symlinks `/usr/local/bin/obsidian`, Linux copies to `~/.local/bin/obsidian`, Windows installs a terminal redirector.

## Why It Matters

Obsidian documents agent automation as an intended use case, naming "agentic coding tools" that use developer commands to test and debug plugins (Source: [[obsidian-cli-documentation]]). The vendor is not tolerating agents; it is courting them.

This compresses the value of the third-party integration layer. Every MCP server that exists to expose vault CRUD now overlaps a first-party surface that needs no plugin and no running Obsidian instance for many operations. The differentiated ground moves up-stack, to synthesis and knowledge structure — what [[Agent Bridge Plugins]] cannot supply by being a better pipe.

## Open Questions

- Does the CLI require the Obsidian GUI process to be running for all commands, or only for GUI-dependent ones (screenshot, DOM inspection)? Not established by the sources read.
