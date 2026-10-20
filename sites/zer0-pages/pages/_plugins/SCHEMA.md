---
schema: "0.1"
coverage: listed
---

# SCHEMA — _plugins

> The build-time Obsidian→Jekyll bridge — Jekyll glue plugins here, pure-Ruby converter cores in obsidian/.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `obsidian/` | dir | Pure-Ruby converter modules (no Jekyll dependency) — unit-tested from tests/ | |
| `obsidian_bridge.rb` | file | Jekyll hooks wiring wikilink, callout, and Dataview conversion into the build | |
| `obsidian_graph_index.rb` | file | Jekyll generator emitting /assets/data/wiki-index.json for the theme's graph UI | |

## Placement

- New conversion logic → a pure module in `obsidian/`, wired from a glue file here, with a test in `tests/`.
