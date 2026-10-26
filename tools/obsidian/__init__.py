"""zer0-pages's Obsidian bridge in Python: an Obsidian vault's syntax, resolved for a plugin-less Jekyll.

The vault's pages were Obsidian notes and Jekyll pages at once, joined by Ruby
plugins that ran inside the build. ADR 0006 removes the Ruby and keeps the
feature: the Jekyll-theme option (tools/jekyll_theme.py, PLAN P2) resolves
what those plugins did before the build and finishes the built pages after.
Each module is a port of one plugin file, kept behaviour for behaviour:

    fence_mask   code fences and inline code, which nothing else touches
    wikilinks    [[links]] and ![[embeds]]
    callouts     > [!note] callouts as the theme's alerts
    dataview     the vault's Dataview subset (TABLE/LIST, FROM, WHERE, FLATTEN, GROUP BY, SORT, LIMIT)
    graph_index  /assets/data/wiki-index.json for the theme's graph view
    bridge       the wikilink index and resolver, the page transform, the base-URL pass
    vault        all of it over a Jekyll source tree, read the way Jekyll 4.4 reads one

Stdlib and PyYAML only. Tests: tools/tests/test_obsidian_bridge.py,
test_graph_index.py and test_obsidian_vault.py.
"""
