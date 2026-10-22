"""Tests for tools/obsidian/graph_index.py — the wiki-index.json the theme's graph view reads.

Ported from sites/zer0-pages/tests/test_graph_index.rb: the payload's shape is the
theme's contract, edges come only from prose (never a code fence or inline code,
never an image embed), every path-qualified link resolves through the same
lookup the browser builds, dead links stay as broken nodes, and the excerpt is
plain words. The Ruby file's last case, the Jekyll glue, is tools/tests/test_obsidian_vault.py's
now. Run: `python3 -m unittest discover tools/tests`.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from obsidian import graph_index as gi  # noqa: E402

GRAPH = {
    "title": "Graph View",
    "path": "_docs/obsidian/graph.md",
    "url": "/zer0-pages/docs/obsidian/graph/",
    "collection": "docs",
    "tags": ["obsidian", "graph"],
    "categories": ["Documentation", "Obsidian"],
    "aliases": ["/docs/obsidian/graph/"],
    "content": (
        "# Graph View\n\nEvery page and every [[_docs/obsidian/getting-started|getting started]]\n"
        "link becomes a node. This one is dead: [[_docs/missing/page|gone]].\n\n{% include obsidian/full-graph.html %}\n"
    ),
}
GETTING_STARTED = {
    "title": "Getting Started with the Obsidian Vault",
    "path": "_docs/obsidian/getting-started.md",
    "url": "/zer0-pages/docs/obsidian/getting-started/",
    "collection": "docs",
    "tags": ["obsidian", "setup"],
    "categories": ["Documentation"],
    "aliases": ["/docs/obsidian/getting-started/"],
    "content": (
        "# Getting Started\n\nSee the [[_docs/obsidian/graph]] and an anchored\n[[_docs/obsidian/graph#Legend|legend link]] "
        "plus a transclusion\n![[_notes/scratch]] and an image embed ![[assets/images/pic.png]].\n\n```bash\n"
        '# fenced code -- none of these become edges\nif [[ -f setup.md ]]; then echo "[[_docs/never-a-page]]"; fi\n```\n\n'
        "Inline code is masked too: `[[_docs/also-never]]`.\n"
    ),
}
POST = {
    "title": "Hello World",
    "path": "_posts/2026-01-01-hello-world.md",
    "url": "/zer0-pages/posts/hello-world/",
    "collection": "posts",
    "tags": ["intro"],
    "categories": ["Posts"],
    "aliases": None,
    "content": (
        "> [!tip] Welcome\n> First post. Read [[_docs/obsidian/getting-started]] twice:\n"
        "> [[_docs/obsidian/getting-started|again]].\n\n" + "Lorem ipsum dolor sit amet, consectetur adipiscing elit. " * 10 + "\n"
    ),
}
SCRATCH = {
    "title": "Scratch",
    "path": "_notes/scratch.md",
    "url": "/zer0-pages/notes/scratch/",
    "collection": "notes",
    "tags": [],
    "categories": [],
    "aliases": [],
    "content": "A tiny note with no links.\n",
}
POOL = [GRAPH, GETTING_STARTED, POST, SCRATCH]


def normalize(value) -> str:
    return " ".join(str(value or "").lower().split())


def client_lookup(entries: list) -> dict:
    """The theme's obsidian-graph.js `buildLookup`: normalized title, basename and aliases; the first entry wins."""
    lookup: dict = {}
    for entry in entries:
        if not entry["url"]:
            continue
        for key in [entry["title"], entry["basename"], *(entry["aliases"] or [])]:
            if normalize(key) and normalize(key) not in lookup:
                lookup[normalize(key)] = entry
    return lookup


def entry(entries: list, basename: str) -> dict:
    return next(e for e in entries if e["basename"] == basename)


class PayloadTest(unittest.TestCase):
    def setUp(self):
        self.payload = gi.build_payload(POOL, dt.datetime(2026, 7, 5, 12, tzinfo=dt.timezone.utc))

    def test_json_is_valid_and_roundtrips(self):
        parsed = json.loads(gi.to_json(POOL, dt.datetime(2026, 7, 5, tzinfo=dt.timezone.utc)))
        self.assertEqual(["count", "entries", "generated_at"], sorted(parsed))
        self.assertEqual(parsed["count"], len(parsed["entries"]))

    def test_generated_at_is_iso8601(self):
        self.assertEqual("2026-07-05T12:00:00Z", self.payload["generated_at"])

    def test_node_count_matches_doc_pool(self):
        self.assertEqual(len(POOL), self.payload["count"])
        self.assertEqual(len(POOL), len(self.payload["entries"]))

    def test_entry_shape_matches_theme_contract(self):
        first = self.payload["entries"][0]
        for key in ("title", "basename", "url", "collection", "tags", "categories", "aliases", "outgoing", "excerpt"):
            self.assertIn(key, first)
        self.assertEqual(("Graph View", "graph", "docs"), (first["title"], first["basename"], first["collection"]))
        self.assertEqual("/zer0-pages/docs/obsidian/graph/", first["url"])

    def test_posts_collection_is_posts(self):
        self.assertEqual("posts", entry(self.payload["entries"], "2026-01-01-hello-world")["collection"])


class EdgesTest(unittest.TestCase):
    def setUp(self):
        self.entries = gi.build_payload(POOL)["entries"]

    def test_edge_extraction_skips_code_fences_and_inline_code(self):
        outgoing = entry(self.entries, "getting-started")["outgoing"]
        self.assertNotIn("_docs/never-a-page", outgoing)
        self.assertNotIn("_docs/also-never", outgoing)

    def test_anchor_and_alias_are_stripped_and_targets_unique(self):
        outgoing = entry(self.entries, "getting-started")["outgoing"]
        self.assertEqual(1, outgoing.count("_docs/obsidian/graph"), "anchored and plain links to one target must dedupe")
        self.assertEqual(1, entry(self.entries, "2026-01-01-hello-world")["outgoing"].count("_docs/obsidian/getting-started"))

    def test_note_embeds_are_edges_but_image_embeds_are_not(self):
        outgoing = entry(self.entries, "getting-started")["outgoing"]
        self.assertIn("_notes/scratch", outgoing)
        self.assertNotIn("assets/images/pic.png", outgoing)

    def test_wikilinks_inside_callouts_are_edges(self):
        self.assertIn("_docs/obsidian/getting-started", entry(self.entries, "2026-01-01-hello-world")["outgoing"])

    def test_path_qualified_targets_resolve_client_side(self):
        lookup = client_lookup(self.entries)
        self.assertEqual("/zer0-pages/docs/obsidian/graph/", lookup[normalize("_docs/obsidian/graph")]["url"])
        self.assertEqual("/zer0-pages/notes/scratch/", lookup[normalize("_notes/scratch")]["url"])
        self.assertEqual("/zer0-pages/docs/obsidian/getting-started/", lookup[normalize("_docs/obsidian/getting-started")]["url"])

    def test_vault_path_added_to_aliases_after_frontmatter_aliases(self):
        self.assertEqual(["/docs/obsidian/graph/", "_docs/obsidian/graph"], entry(self.entries, "graph")["aliases"])
        doc = {"title": "X", "path": "_docs/x.md", "url": "/x/", "collection": "docs", "aliases": ["_docs/x"], "content": ""}
        self.assertEqual(["_docs/x"], gi.build_entry(doc)["aliases"])

    def test_dead_link_stays_in_outgoing_and_unresolved(self):
        self.assertIn("_docs/missing/page", entry(self.entries, "graph")["outgoing"])
        self.assertNotIn(normalize("_docs/missing/page"), client_lookup(self.entries))


class ExcerptTest(unittest.TestCase):
    def test_excerpt_drops_fences_markup_liquid_and_wikilink_syntax(self):
        excerpt = gi.build_entry(GRAPH)["excerpt"]
        for gone in ("```", "[[", "]]", "{%", "# Graph View"):
            self.assertNotIn(gone, excerpt)
        self.assertIn("getting started", excerpt)
        self.assertIn("gone", excerpt, "wikilink display text must survive")

    def test_excerpt_drops_fenced_code_content(self):
        excerpt = gi.build_entry(GETTING_STARTED)["excerpt"]
        self.assertNotIn("echo", excerpt)
        self.assertNotIn("_docs/also-never", excerpt)

    def test_excerpt_truncates_to_240_chars(self):
        excerpt = gi.build_entry(POST)["excerpt"]
        self.assertLessEqual(len(excerpt), 240)
        self.assertTrue(excerpt.endswith("…"), "long excerpts must end with an ellipsis")

    def test_excerpt_strips_callout_and_blockquote_markers(self):
        excerpt = gi.build_entry(POST)["excerpt"]
        self.assertNotIn("[!tip]", excerpt)
        self.assertNotIn("> ", excerpt)
        self.assertIn("Welcome", excerpt)
        self.assertIn("First post.", excerpt)

    def test_short_excerpt_is_untouched(self):
        self.assertEqual("A tiny note with no links.", gi.build_entry(SCRATCH)["excerpt"])


if __name__ == "__main__":
    unittest.main()
