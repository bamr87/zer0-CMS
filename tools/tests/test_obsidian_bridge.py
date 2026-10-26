"""Tests for tools/obsidian — the Obsidian bridge zer0-pages's Jekyll plugins were, in Python.

Ported from sites/zer0-pages/tests/test_obsidian_bridge.rb, test for test, so the
Python bridge is held to every promise the Ruby one was: code fences and inline
code are never touched, wikilinks and embeds resolve (or say they did not) with
the label a reader sees, callouts become the theme's alerts, every Dataview query
the vault has ever used parses and renders, an unsupported one falls back to a
listing, and built pages get the base URL on their root-relative links. No
Jekyll, no network. Run: `python3 -m unittest discover tools/tests`.
"""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from obsidian import bridge, callouts, dataview, fence_mask, wikilinks  # noqa: E402

D = dt.date


def doc(path: str, **fm) -> dict:
    base = path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return {"title": fm.get("title", base), "url": "/" + path.removesuffix(".md") + "/", "path": path, "fm": fm}


def posts() -> list:
    return [
        doc("_posts/2026-01-10-alpha.md", title="Alpha", type="post", date=D(2026, 1, 10), categories=["Dev"],
            tags=["ruby", "jekyll"], description="First post"),
        doc("_posts/2025-06-01-beta.md", title="Beta", type="post", date=D(2025, 6, 1), categories=["Dev", "Notes"],
            tags=["obsidian"], description="Second post"),
        doc("_posts/2024-03-05-gamma.md", title="Gamma", type="post", date=D(2024, 3, 5), categories=["Life"],
            tags=["ruby"], description="Third post"),
        doc("_posts/2026-02-01-hidden.md", title="Hidden", type="post", date=D(2026, 2, 1), draft=True,
            categories=["Dev"], description="Draft post"),
    ]  # fmt: skip


def docs_collection() -> list:
    return [
        doc("_docs/setup.md", title="Setup", type="doc", date=D(2025, 1, 1), lastmod=D(2026, 3, 1),
            difficulty="beginner", description="Setup guide", tags=["setup"]),
        doc("_docs/features/mermaid.md", title="Mermaid", type="doc", date=D(2025, 2, 1), difficulty="advanced",
            description="Diagrams", estimated_reading_time="5 min", tags=["diagrams"]),
        doc("_docs/jekyll/plugins.md", title="Plugins", type="doc", date=D(2025, 5, 1), description="Plugin guide",
            tags=["jekyll"]),
        doc("_docs/features/index.md", title="Features", type="doc", date=D(2025, 1, 1), description="Feature index"),
    ]  # fmt: skip


def quickstart() -> list:
    return [
        doc("_quickstart/second.md", title="Second Step", type="quickstart", quickstart={"step": 2}, description="Then this"),
        doc("_quickstart/first.md", title="First Step", type="quickstart", quickstart={"step": 1}, description="Start here"),
    ]


def about() -> list:
    return [
        doc("_about/features/one.md", title="Bravo", type="about", order=1, description="B"),
        doc("_about/features/two.md", title="Alpha2", type="about", order=1, description="A"),
        doc("_about/index.md", title="About", type="about", order=2, description="Idx"),
    ]


def site_pool() -> list:
    return posts() + docs_collection() + quickstart() + about() + [
        doc("index.md", title="Home", type="landing"),
        doc("wiki/topic.md", title="Topic", type="wiki"),
        doc("_templates/quest.md", title="Quest Template"),
        doc("_moc/Home.md", title="Home MOC", type="moc"),
    ]


# Every unique real Dataview query found in the vault (2026-07-05), plus the pinned quest-board query.
REAL_QUERIES = [
    'TABLE description AS Summary\nFROM "_about"\nWHERE type = "about" AND file.name != "index"\nSORT order ASC, title ASC',
    'TABLE rows.file.link AS Notes, length(rows) AS Count\nFROM "_about"\nWHERE file.name != "index" AND file.name != "README"\nGROUP BY file.folder AS Section\nSORT Section ASC',
    'TABLE type AS Type, description AS Summary\nFROM "_about"\nWHERE file.name != "index" AND file.name != "README"\nSORT file.folder ASC, title ASC',
    'TABLE rows.file.link AS Notes\nFROM "_about"\nWHERE file.name != "index" AND file.name != "README"\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC',
    'TABLE rows.file.link AS "Documents", length(rows) AS "Count"\nFROM "_docs"\nWHERE type = "doc"\nGROUP BY choice(file.folder = "_docs", "General", regexreplace(file.folder, "^_docs/", "")) AS Section\nSORT Section ASC',
    'TABLE choice(file.folder = "_docs", "General", regexreplace(file.folder, "^_docs/", "")) AS Section, description AS Summary\nFROM "_docs"\nWHERE type = "doc"\nSORT default(lastmod, date) DESC\nLIMIT 15',
    'TABLE rows.file.link AS "Documents"\nFROM "_docs"\nWHERE type = "doc" AND difficulty\nGROUP BY difficulty AS Level\nSORT Level ASC',
    'TABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC\nLIMIT 8',
    'TABLE difficulty AS Difficulty, date AS Date, description AS Summary\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nSORT date DESC',
    'TABLE rows.file.link AS Notebooks\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nFLATTEN default(difficulty, "intermediate") AS level\nGROUP BY level\nSORT level ASC',
    'TABLE rows.file.link AS Notebooks\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC',
    'TABLE rows.file.link AS Notebooks\nFROM "_notebooks"\nWHERE type = "notebook" AND draft != true\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC',
    'TABLE description AS Summary, difficulty AS Difficulty, date AS Date\nFROM "_notes"\nWHERE type = "note" AND draft != true\nSORT date DESC',
    'TABLE rows.file.link AS Notes\nFROM "_notes"\nWHERE type = "note" AND draft != true\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC',
    'TABLE rows.file.link AS Notes\nFROM "_notes"\nWHERE type = "note" AND draft != true\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC',
    'TABLE rows.file.link AS Notes\nFROM "_notes"\nWHERE type = "note" AND draft != true\nFLATTEN difficulty AS level\nGROUP BY level\nSORT level ASC',
    'TABLE date AS Date, tags AS Tags\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC',
    'TABLE rows.file.link AS Notes, length(rows) AS Count\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC',
    'TABLE difficulty AS Difficulty, xp AS XP, estimated_time AS Time, description AS Summary\nFROM "_quests"\nWHERE type = "quest" AND draft != true\nSORT file.name ASC',
    'TABLE description AS Summary, quickstart.step AS Step\nFROM "_quickstart"\nWHERE type = "quickstart"\nSORT quickstart.step ASC',
    'TABLE description AS Summary\nFROM "_quickstart"\nWHERE type = "quickstart" AND draft != true\nSORT file.name ASC',
    'TABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC',
    'TABLE rows.file.link AS Posts\nFROM "_posts"\nFLATTEN categories AS category\nWHERE type = "post" AND draft != true\nGROUP BY category',
    'TABLE rows.file.link AS Posts\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN dateformat(date, "yyyy") AS year\nGROUP BY year\nSORT year DESC',
    'TABLE rows.file.link AS Posts, rows.date AS Date\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN dateformat(date, "yyyy") AS year\nGROUP BY year\nSORT year DESC',
    'TABLE rows.file.link AS Notes, length(rows) AS Count\nFROM "_posts" OR "_notebooks"\nFLATTEN categories AS category\nGROUP BY category\nSORT category ASC',
    'TABLE\n  description AS Description,\n  difficulty AS Difficulty,\n  estimated_reading_time AS "Read Time"\nFROM "_docs/features"\nWHERE type = "doc" AND file.name != "index"\nSORT title ASC',
    'TABLE rows.file.link AS Features\nFROM "_docs/features"\nWHERE file.name != "index"\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC',
    'TABLE rows.file.link AS Features\nFROM "_docs/features"\nWHERE type = "doc" AND file.name != "index" AND difficulty\nGROUP BY difficulty\nSORT difficulty ASC',
    'TABLE description AS Description, tags AS Tags\nFROM "_about/features"\nWHERE file.name != "index" AND draft != true\nSORT title ASC',
    'LIST rows.file.link\nFROM "" AND -"wiki" AND -"_templates" AND -"_moc"\nGROUP BY file.folder AS Folder\nSORT Folder ASC',
    'TABLE rows.file.link AS Notes\nFROM "_posts" OR "_notebooks"\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC',
]


def link(text: str) -> str:
    return text.replace("[[x]]", "LINK")


class FenceMaskTest(unittest.TestCase):
    def test_transform_applies_only_outside_fences(self):
        out = fence_mask.apply_outside("before [[x]]\n```ruby\ncode [[x]]\n```\nafter [[x]]\n", link)
        self.assertIn("before LINK\n", out)
        self.assertIn("code [[x]]\n", out)
        self.assertIn("after LINK\n", out)

    def test_fence_at_beginning_and_end_of_text(self):
        md = "```\nraw [[x]]\n```"
        self.assertEqual(md, fence_mask.apply_outside(md, link))

    def test_tilde_fences(self):
        out = fence_mask.apply_outside("~~~\ntilde [[x]]\n~~~\ntail [[x]]\n", link)
        self.assertIn("tilde [[x]]", out)
        self.assertIn("tail LINK", out)

    def test_unclosed_fence_runs_to_eof(self):
        out = fence_mask.apply_outside("start [[x]]\n```\nnever closed [[x]]\n", link)
        self.assertIn("start LINK", out)
        self.assertIn("never closed [[x]]", out)

    def test_inline_code_masked(self):
        self.assertEqual("use `[[x]]` here and LINK there\n", fence_mask.apply_outside("use `[[x]]` here and [[x]] there\n", link))

    def test_double_backtick_inline_span_with_nested_backtick(self):
        out = fence_mask.apply_outside("a ``code ` tick [[x]]`` b [[x]]\n", link)
        self.assertIn("``code ` tick [[x]]``", out)
        self.assertIn("b LINK", out)

    def test_inline_masking_can_be_disabled(self):
        self.assertEqual("a `LINK` b\n", fence_mask.apply_outside("a `[[x]]` b\n", link, mask_inline=False))

    def test_replace_fences_targets_info_string(self):
        out = fence_mask.replace_fences(
            "intro\n```dataview\nLIST\n```\noutro\n", lambda info, body: f"<div>{body.strip()}</div>\n" if info == "dataview" else None
        )
        self.assertEqual("intro\n<div>LIST</div>\noutro\n", out)

    def test_replace_fences_skips_nested_fence_inside_outer_fence(self):
        md = "````markdown\n```dataview\nLIST\n```\n````\n"
        self.assertEqual(md, fence_mask.replace_fences(md, lambda info, _: "REPLACED" if info == "dataview" else None))

    def test_lines_and_strip_are_rubys(self):
        """Python's splitlines and strip would split at \\x0c and strip a no-break space; Ruby's do neither."""
        self.assertEqual(["a\x0cb\n", "c"], fence_mask.lines("a\x0cb\nc"))
        self.assertEqual(" x", fence_mask.strip("  x\0"))


class WikilinksTest(unittest.TestCase):
    TARGETS = {"_docs/setup": "/docs/setup/", "_notes/My Note": "/notes/my-note/", "assets/images/pic.png": "/assets/images/pic.png"}

    def convert(self, md: str) -> str:
        return wikilinks.convert(md, self.TARGETS.get)

    def test_plain_link(self):
        self.assertIn('<a href="/docs/setup/" class="wikilink">setup</a>', self.convert("See [[_docs/setup]]."))

    def test_alias_link(self):
        self.assertIn('<a href="/docs/setup/" class="wikilink">the setup guide</a>', self.convert("See [[_docs/setup|the setup guide]]."))

    def test_anchor_link_slugifies_fragment(self):
        self.assertIn('<a href="/docs/setup/#install-steps" class="wikilink">setup</a>', self.convert("See [[_docs/setup#Install Steps]]."))

    def test_anchor_link_with_alias(self):
        out = self.convert("See [[_docs/setup#Install Steps|installation]].")
        self.assertIn('<a href="/docs/setup/#install-steps" class="wikilink">installation</a>', out)

    def test_same_page_anchor(self):
        self.assertIn('<a href="#the-heading" class="wikilink">The Heading</a>', self.convert("Jump to [[#The Heading]]."))

    def test_image_embed_resolved(self):
        self.assertIn("![](/assets/images/pic.png)", self.convert("Look: ![[assets/images/pic.png]]"))

    def test_image_embed_unresolved_keeps_path(self):
        self.assertIn("![](missing.png)", self.convert("Look: ![[missing.png]]"))

    def test_note_embed_becomes_link(self):
        self.assertIn('<a href="/docs/setup/" class="wikilink">setup</a>', self.convert("Inline: ![[_docs/setup]]"))

    def test_unresolved_link_becomes_span(self):
        self.assertIn('<span class="wikilink-unresolved">Nowhere</span>', self.convert("See [[_docs/nowhere|Nowhere]]."))

    def test_display_text_is_html_escaped(self):
        self.assertIn("a &lt;b&gt; &amp; &quot;q&quot;", self.convert('See [[_docs/nowhere|a <b> & "q"]].'))

    def test_links_inside_fences_and_inline_code_untouched(self):
        out = self.convert("```\n[[_docs/setup]]\n```\nand `[[_docs/setup]]` but [[_docs/setup]]\n")
        self.assertIn("```\n[[_docs/setup]]\n```", out)
        self.assertIn("`[[_docs/setup]]`", out)
        self.assertIn('<a href="/docs/setup/" class="wikilink">setup</a>', out)

    def test_target_with_spaces(self):
        self.assertIn('<a href="/notes/my-note/" class="wikilink">My Note</a>', self.convert("Read [[_notes/My Note]]."))


class CalloutsTest(unittest.TestCase):
    def test_github_caps_style_without_title(self):
        out = callouts.convert("> [!NOTE]\n> Remember this.\n")
        self.assertIn('class="alert alert-info obsidian-callout obsidian-callout-note" markdown="1"', out)
        self.assertIn('<strong class="obsidian-callout-title">Note</strong>', out)
        self.assertIn("Remember this.\n", out)
        self.assertNotIn("> Remember", out)

    def test_obsidian_style_with_title(self):
        out = callouts.convert("> [!tip] Pro Tip\n> Do the thing.\n")
        self.assertIn("alert-success", out)
        self.assertIn('<strong class="obsidian-callout-title">Pro Tip</strong>', out)
        self.assertIn("Do the thing.\n", out)

    def test_type_mapping(self):
        for md, css in (("warning", "warning"), ("CAUTION", "warning"), ("danger", "danger"), ("IMPORTANT", "danger"),
                        ("quote", "secondary"), ("example", "light"), ("question", "info"), ("mystery", "info")):  # fmt: skip
            self.assertIn(f"alert-{css}", callouts.convert(f"> [!{md}]\n> x\n"), md)

    def test_fold_markers_are_stripped(self):
        out = callouts.convert("> [!tip]+ Folded Open\n> body\n")
        self.assertIn('<strong class="obsidian-callout-title">Folded Open</strong>', out)
        self.assertNotIn("]+", out)
        self.assertIn("alert-warning", callouts.convert("> [!warning]- Folded Closed\n> body\n"))

    def test_multi_line_body_kept_as_markdown(self):
        out = callouts.convert("> [!note] Steps\n> - one\n> - two\n>\n> **bold** tail\n")
        self.assertIn("- one\n- two\n", out)
        self.assertIn("**bold** tail", out)

    def test_plain_blockquote_untouched(self):
        md = "> just a quote\n> second line\n"
        self.assertEqual(md, callouts.convert(md))

    def test_callout_inside_fence_untouched(self):
        md = "```markdown\n> [!note] Example\n> body\n```\n"
        self.assertEqual(md, callouts.convert(md))

    def test_text_after_callout_continues(self):
        out = callouts.convert("> [!note]\n> body\n\nplain paragraph\n")
        self.assertIn("</div>\n", out)
        self.assertIn("plain paragraph", out)


class DataviewParseTest(unittest.TestCase):
    def test_every_real_query_parses(self):
        for i, query in enumerate(REAL_QUERIES):
            parsed = dataview.parse(query)
            self.assertIsNotNone(parsed, f"query #{i} failed to parse:\n{query}")
            self.assertIn(parsed.mode, ("table", "list"))

    def test_table_structure(self):
        q = dataview.parse('TABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC')
        self.assertEqual("table", q.mode)
        self.assertEqual(["Date", "Summary"], [c["label"] for c in q.columns])
        self.assertEqual(["_posts"], q.source["include"])
        self.assertEqual(2, len(q.where))
        self.assertEqual([{"expr": ("field", ["date"]), "dir": "desc"}], q.sort)

    def test_multiline_columns_and_quoted_label(self):
        q = dataview.parse('TABLE\n  description AS Description,\n  estimated_reading_time AS "Read Time"\nFROM "_docs/features"')
        self.assertEqual(["Description", "Read Time"], [c["label"] for c in q.columns])
        self.assertEqual(["_docs/features"], q.source["include"])

    def test_from_or_folders(self):
        q = dataview.parse('TABLE date AS Date\nFROM "_posts" OR "_notebooks"')
        self.assertEqual(["_posts", "_notebooks"], q.source["include"])
        self.assertEqual([], q.source["exclude"])

    def test_from_with_negations(self):
        q = dataview.parse('LIST rows.file.link\nFROM "" AND -"wiki" AND -"_templates" AND -"_moc"\nGROUP BY file.folder AS Folder\nSORT Folder ASC')
        self.assertEqual([""], q.source["include"])
        self.assertEqual(["wiki", "_templates", "_moc"], q.source["exclude"])
        self.assertEqual("Folder", q.group_by["alias"])

    def test_group_by_function_expression(self):
        q = dataview.parse(REAL_QUERIES[4])
        self.assertEqual("Section", q.group_by["alias"])
        self.assertEqual(("call", "choice"), q.group_by["expr"][:2])

    def test_limit_and_multi_sort(self):
        q = dataview.parse('TABLE description AS Summary\nFROM "_about"\nSORT order ASC, title ASC\nLIMIT 15')
        self.assertEqual(15, q.limit)
        self.assertEqual(2, len(q.sort))
        self.assertEqual("asc", q.sort[0]["dir"])

    def test_flatten_before_where_order_tolerated(self):
        q = dataview.parse(REAL_QUERIES[22])
        self.assertEqual(1, len(q.flatten))
        self.assertEqual("category", q.flatten[0]["alias"])

    def test_bare_truthy_where_clause(self):
        q = dataview.parse('TABLE rows.file.link AS X\nFROM "_docs"\nWHERE type = "doc" AND difficulty\nGROUP BY difficulty')
        self.assertEqual(2, len(q.where))
        self.assertEqual(("field", ["difficulty"]), q.where[1])

    def test_unsupported_queries_return_none(self):
        for query in ('TASK FROM "_posts"', "not a query at all", "", 'TABLE date AS\nFROM "_posts"'):
            self.assertIsNone(dataview.parse(query), query)

    def test_extract_from_survives_parse_failure(self):
        self.assertEqual(["_posts", "_notes"], dataview.extract_from('TASK something\nFROM "_posts" OR "_notes"\nWEIRD')["include"])
        self.assertIsNone(dataview.extract_from("no from here"))


class DataviewRenderTest(unittest.TestCase):
    def render(self, query: str, docs: list) -> str:
        parsed = dataview.parse(query)
        self.assertIsNotNone(parsed, f"query failed to parse:\n{query}")
        html = dataview.render(parsed, docs)
        self.assertIsNotNone(html, f"query failed to render:\n{query}")
        return html

    @staticmethod
    def row(html: str, start: int) -> str:
        return html[start : html.index("</tr>", start)]

    def test_flat_table_filters_drafts_and_sorts_desc(self):
        html = self.render(REAL_QUERIES[21], posts())
        self.assertIn("<th>File</th><th>Date</th><th>Summary</th>", html)
        self.assertNotIn("Hidden", html)
        self.assertLess(html.index("Alpha"), html.index("Beta"))
        self.assertLess(html.index("Beta"), html.index("Gamma"))
        self.assertIn('<a href="/_posts/2026-01-10-alpha/">Alpha</a>', html)
        self.assertIn("2026-01-10", html)

    def test_limit_truncates_rows(self):
        html = self.render('TABLE date AS Date\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC\nLIMIT 2', posts())
        self.assertIn("Alpha", html)
        self.assertIn("Beta", html)
        self.assertNotIn("Gamma", html)

    def test_group_by_category_with_length(self):
        html = self.render(REAL_QUERIES[17], posts())
        self.assertIn("<th>category</th><th>Notes</th><th>Count</th>", html)
        dev, life, notes = html.index("<td>Dev</td>"), html.index("<td>Life</td>"), html.index("<td>Notes</td>")
        self.assertTrue(dev < life < notes, "groups must sort ascending")
        self.assertIn("Alpha", self.row(html, dev))
        self.assertIn("Beta", self.row(html, dev))
        self.assertIn("<td>2</td>", self.row(html, dev))

    def test_group_by_year_via_dateformat_desc(self):
        html = self.render(REAL_QUERIES[23], posts())
        self.assertTrue(html.index("<td>2026</td>") < html.index("<td>2025</td>") < html.index("<td>2024</td>"))

    def test_rows_field_projection(self):
        self.assertIn("2026-01-10", self.render(REAL_QUERIES[24], posts()))

    def test_choice_and_regexreplace_section_column(self):
        html = self.render(REAL_QUERIES[5], docs_collection())
        for section in ("General", "features", "jekyll"):
            self.assertIn(f"<td>{section}</td>", html)
        self.assertLess(html.index("Setup"), html.index("Plugins"), "lastmod fallback must win over date")
        self.assertLess(html.index("Plugins"), html.index("Mermaid"))

    def test_group_by_function_expression_render(self):
        html = self.render(REAL_QUERIES[4], docs_collection())
        self.assertIn("<th>Section</th><th>Documents</th><th>Count</th>", html)
        self.assertIn("<td>General</td>", html)
        self.assertIn("<td>features</td>", html)

    def test_bare_truthy_where_drops_docs_without_field(self):
        html = self.render(REAL_QUERIES[6], docs_collection())
        self.assertIn("<td>advanced</td>", html)
        self.assertIn("<td>beginner</td>", html)
        self.assertNotIn("Plugins", html, "doc without difficulty must be filtered")

    def test_flatten_default_fills_missing_value(self):
        query = 'TABLE rows.file.link AS Docs\nFROM "_docs"\nWHERE type = "doc"\nFLATTEN default(difficulty, "intermediate") AS level\nGROUP BY level\nSORT level ASC'
        self.assertIn("<td>intermediate</td>", self.render(query, docs_collection()))

    def test_flatten_tags_group(self):
        html = self.render('TABLE rows.file.link AS Notes\nFROM "_posts"\nWHERE type = "post" AND draft != true\nFLATTEN tags AS tag\nGROUP BY tag\nSORT tag ASC', posts())
        jekyll, obsidian, ruby = html.index("<td>jekyll</td>"), html.index("<td>obsidian</td>"), html.index("<td>ruby</td>")
        self.assertTrue(jekyll < obsidian < ruby)
        self.assertIn("Alpha", self.row(html, ruby))
        self.assertIn("Gamma", self.row(html, ruby))

    def test_nested_frontmatter_field(self):
        html = self.render(REAL_QUERIES[19], quickstart())
        self.assertLess(html.index("First Step"), html.index("Second Step"), "must sort by nested quickstart.step")
        self.assertIn("<td>1</td>", html)

    def test_multi_key_sort_breaks_ties(self):
        html = self.render(REAL_QUERIES[0], about())
        self.assertLess(html.index("Alpha2"), html.index("Bravo"), "title must break the order tie")
        self.assertNotIn(">Idx<", html)

    def test_grouped_list_render(self):
        html = self.render(REAL_QUERIES[30], posts() + [doc("index.md", title="Home")])
        self.assertIn('<ul class="obsidian-dataview dataview-list">', html)
        self.assertIn("<strong>_posts</strong>", html)
        self.assertIn('<a href="/_posts/2026-01-10-alpha/">Alpha</a>', html)
        self.assertIn("&#8212;", html, "root files group under an em dash")

    def test_tags_array_renders_comma_joined(self):
        self.assertIn("ruby, jekyll", self.render('TABLE date AS Date, tags AS Tags\nFROM "_posts"\nWHERE type = "post" AND draft != true\nSORT date DESC', posts()))

    def test_every_real_query_renders_against_pool(self):
        pool = site_pool()
        for i, query in enumerate(REAL_QUERIES):
            parsed = dataview.parse(query)
            html = dataview.render(parsed, bridge.docs_for(pool, parsed.source))
            self.assertIsNotNone(html, f"query #{i} failed to render:\n{query}")
            self.assertIn("obsidian-dataview", html)

    def test_values_keep_rubys_meanings(self):
        """Zero and "" are true, `true` is not 1, a missing value sorts last either way, ties keep their order."""
        self.assertTrue(dataview.truthy(0) and dataview.truthy(""))
        self.assertFalse(dataview.values_equal(True, 1))
        rows = [doc(f"_n/{n}.md", rank=r) for n, r in (("a", None), ("b", 2), ("c", 1), ("d", 2))]
        for direction, order in (("ASC", ["c", "b", "d", "a"]), ("DESC", ["b", "d", "c", "a"])):
            html = self.render(f'TABLE rank AS R\nFROM "_n"\nSORT rank {direction}', rows)
            self.assertEqual(order, sorted(order, key=lambda name: html.index(f'"/_n/{name}/"')))


class BridgeHelpersTest(unittest.TestCase):
    def setUp(self):
        index = bridge.build_index([
            {"path": "_docs/jekyll/index.md", "url": "/docs/jekyll/", "aliases": ["/old-jekyll/"]},
            {"path": "_docs/setup.md", "url": "/docs/setup/", "aliases": None},
            {"path": "_notes/setup.md", "url": "/notes/setup/", "aliases": []},
            {"path": "_quests/forge-a-quest.md", "url": "/quests/forge-a-quest/", "aliases": "/quests/forge/"},
            {"path": "assets/images/pic.png", "url": "/assets/images/pic.png", "aliases": []},
        ])  # fmt: skip
        self.resolve = bridge.resolver_for(index)

    def test_resolves_by_vault_path_without_extension(self):
        self.assertEqual("/docs/jekyll/", self.resolve("_docs/jekyll/index"))

    def test_resolves_with_md_extension(self):
        self.assertEqual("/docs/jekyll/", self.resolve("_docs/jekyll/index.md"))

    def test_resolves_case_insensitively(self):
        self.assertEqual("/docs/jekyll/", self.resolve("_DOCS/Jekyll/Index"))

    def test_unique_basename_resolves(self):
        self.assertEqual("/quests/forge-a-quest/", self.resolve("forge-a-quest"))

    def test_ambiguous_basename_does_not_resolve(self):
        self.assertIsNone(self.resolve("setup"))

    def test_alias_resolves(self):
        self.assertEqual("/docs/jekyll/", self.resolve("/old-jekyll/"))
        self.assertEqual("/quests/forge-a-quest/", self.resolve("/quests/forge/"))

    def test_static_file_resolves_by_basename_and_path(self):
        self.assertEqual("/assets/images/pic.png", self.resolve("pic.png"))
        self.assertEqual("/assets/images/pic.png", self.resolve("assets/images/pic.png"))

    def test_unknown_target_is_none(self):
        self.assertIsNone(self.resolve("_docs/never-written"))

    def test_docs_for_include_exclude(self):
        pool = site_pool()
        self.assertEqual(4, len(bridge.docs_for(pool, {"include": ["_posts"], "exclude": []})))
        self.assertEqual(2, len(bridge.docs_for(pool, {"include": ["_docs/features"], "exclude": []})))
        self.assertEqual(6, len(bridge.docs_for(pool, {"include": ["_posts", "_quickstart"], "exclude": []})))
        everything = bridge.docs_for(pool, {"include": [""], "exclude": ["wiki", "_templates", "_moc"]})
        self.assertFalse(any(d["path"].startswith(("wiki/", "_templates/", "_moc/")) for d in everything))
        self.assertTrue(any(d["path"] == "index.md" for d in everything))


class BridgeTransformTest(unittest.TestCase):
    def setUp(self):
        self.pool = site_pool()
        index = bridge.build_index([{"path": d["path"], "url": d["url"], "aliases": d["fm"].get("aliases")} for d in self.pool])
        self.resolve = bridge.resolver_for(index)

    def transform(self, md: str) -> str:
        return bridge.transform(md, self.resolve, self.pool)

    def test_full_pipeline(self):
        md = (
            "# Page\n\nSee [[_docs/setup|Setup]] and [[_docs/missing]].\n\n> [!tip] Hint\n> Use `[[_docs/setup]]` syntax.\n\n"
            '```dataview\nTABLE date AS Date, description AS Summary\nFROM "_posts"\nWHERE type = "post" AND draft != true\n'
            'SORT date DESC\n```\n\n```ruby\nputs "[[_docs/setup]] stays raw"\n```\n'
        )
        out = self.transform(md)
        self.assertIn('<a href="/_docs/setup/" class="wikilink">Setup</a>', out)
        self.assertIn('<span class="wikilink-unresolved">missing</span>', out)
        self.assertIn("alert-success", out)
        self.assertIn("`[[_docs/setup]]`", out)
        self.assertIn("dataview-table", out)
        self.assertIn("Alpha", out)
        self.assertNotIn("```dataview", out)
        self.assertIn('puts "[[_docs/setup]] stays raw"', out)

    def test_unsupported_dataview_falls_back_to_link_list(self):
        out = self.transform('```dataview\nTASK\nFROM "_posts"\nWHERE !completed\n```\n')
        self.assertIn("unsupported dataview query", out)
        self.assertIn("dataview-fallback", out)
        self.assertIn("Alpha", out)

    def test_dataview_sample_inside_outer_fence_is_preserved(self):
        out = self.transform('````markdown\n```dataview\nTABLE date AS Date\nFROM "_posts"\n```\n````\n')
        self.assertIn("```dataview", out)
        self.assertNotIn("dataview-table", out)


class PostprocessHtmlTest(unittest.TestCase):
    BASE = "/zer0-pages"

    def post(self, html: str) -> str:
        return bridge.postprocess_html(html, self.BASE, "https://bamr87.github.io")

    def test_prefixes_root_relative_href_and_src(self):
        out = self.post('<a href="/docs/setup/">x</a><img src="/assets/pic.png">')
        self.assertIn('href="/zer0-pages/docs/setup/"', out)
        self.assertIn('src="/zer0-pages/assets/pic.png"', out)

    def test_does_not_double_prefix(self):
        self.assertEqual('<a href="/zer0-pages/docs/">x</a>', self.post('<a href="/zer0-pages/docs/">x</a>'))

    def test_skips_protocol_relative_and_absolute(self):
        out = self.post('<a href="//cdn.example.com/x.js">x</a><a href="https://a.b/">y</a>')
        self.assertIn('href="//cdn.example.com/x.js"', out)
        self.assertIn('href="https://a.b/"', out)

    def test_skips_pre_and_code_blocks(self):
        out = self.post('<p><a href="/docs/">go</a></p><pre><code>&lt;a href="/docs/"&gt;raw</code></pre><code>href="/x/"</code>')
        self.assertIn('href="/zer0-pages/docs/">go', out)
        self.assertIn('<pre><code>&lt;a href="/docs/"&gt;raw</code></pre>', out)
        self.assertIn('<code>href="/x/"</code>', out)

    def test_replaces_literal_liquid_leftovers(self):
        out = self.post("<p>{{ site.url }}/x and {{ site.baseurl }}/y</p><code>{{ site.url }}</code>")
        self.assertIn("https://bamr87.github.io/zer0-pages/x", out)
        self.assertIn("/zer0-pages/y", out)
        self.assertIn("<code>{{ site.url }}</code>", out)

    def test_noop_when_baseurl_empty(self):
        self.assertEqual('<a href="/docs/">x</a>', bridge.postprocess_html('<a href="/docs/">x</a>', "", "https://x"))

    def test_single_quoted_attributes(self):
        self.assertIn("href='/zer0-pages/docs/'", self.post("<a href='/docs/'>x</a>"))


if __name__ == "__main__":
    unittest.main()
