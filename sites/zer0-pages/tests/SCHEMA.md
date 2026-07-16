---
schema: "0.1"
coverage: listed
---

# SCHEMA — tests

> Stdlib-only Ruby unit tests for the bridge plugin cores — run with `ruby -Ipages/_plugins tests/<file>` from the repo root.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `test_graph_index.rb` | file | Tests the graph index builder and the glue plugin's pure helpers | |
| `test_obsidian_bridge.rb` | file | Tests the wikilink, callout, Dataview, and fence-mask converters | |

## Placement

- New bridge module → a matching `test_<module>.rb` here.
