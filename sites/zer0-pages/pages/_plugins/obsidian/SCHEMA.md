---
schema: "0.1"
coverage: listed
---

# SCHEMA — obsidian

> Pure-Ruby converter cores of the Obsidian bridge — importable without Jekyll, Ruby 2.6 compatible, exercised by tests/.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `callouts.rb` | file | Converts Obsidian/GitHub callout blockquotes into Bootstrap alert divs | |
| `dataview.rb` | file | Parses and renders the vault's subset of the Dataview query language (TABLE/LIST) | |
| `fence_mask.rb` | file | Splits markdown around code fences and inline code so converters never touch code samples | |
| `graph_index.rb` | file | Builds the wiki-index.json payload (nodes plus outgoing wikilink edges) | |
| `wikilinks.rb` | file | Converts [[wikilinks]] and ![[embeds]] into HTML/markdown links via a caller-supplied resolver | |

## Placement

- New converter → `<name>.rb` here (pure Ruby, no Jekyll), wired in from `../obsidian_bridge.rb` and tested in `tests/`.
