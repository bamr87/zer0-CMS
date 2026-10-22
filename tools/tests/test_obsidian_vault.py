"""Tests for tools/obsidian/vault.py — the bridge run over a Jekyll source tree before the build.

zer0-pages's plugins read each page's URL and data from Jekyll; this module reads
them from the tree the way Jekyll 4.4 does, so these tests pin Jekyll's rules
the bridge depends on: which files are read, the URL each gets (collection
templates, pretty pages, `permalink:`, a post's categories and date), the data
a document gets filled in (title, slug, date, categories, tags, draft), the
order of a collection, and what the rewrite and the HTML pass do to the files.
The Ruby suite's "Jekyll glue" case lives here too: the graph index's URLs carry
the base URL and a page has no collection. No Jekyll, no network. Run:
`python3 -m unittest discover tools/tests`.
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from obsidian import vault  # noqa: E402

NOW = dt.datetime(2026, 10, 22, 12, tzinfo=dt.timezone.utc)
CONFIG = {
    "baseurl": "/zer0-pages",
    "url": "https://example.test",
    "permalink": "pretty",
    "collections": {"docs": {"output": True, "permalink": "/docs/:path/"}, "notes": {"output": True}},
    "exclude": ["_templates", "private"],
    "defaults": [{"scope": {"path": "", "type": "docs"}, "values": {"layout": "doc", "type": "doc"}}],
}
FILES = {
    "index.md": "---\ntitle: Home\npermalink: /\n---\nStart at [[_docs/setup|Setup]].\n",
    "about.md": "---\ntitle: About\n---\nAbout us. See [[Tips]] and [[_notes/missing]].\n",
    "wiki/index.md": "---\ntitle: Wiki\n---\n> [!tip] Hint\n> Use `[[_docs/setup]]`.\n",
    "wiki/topic.md": "---\ntitle: Topic\naliases: [Old Topic]\n---\nA [link](/docs/setup/) and an ![[assets/pic.png]].\n",
    "wiki/_hidden.md": "---\ntitle: Hidden\n---\nNever read.\n",
    "private/secret.md": "---\ntitle: Secret\n---\nExcluded.\n",
    "_templates/t.md": "---\ntitle: T\n---\nExcluded.\n",
    "assets/pic.png": "png",
    "notes.md": "no front matter, so a static file",
    "_docs/setup.md": "---\ntitle: Setup\n---\nInstall it.\n",
    "_docs/features/index.md": "---\ntitle: Features\ndate: 2025-01-02\n---\nAll of them.\n",
    "_docs/features/z-last.md": "---\ntitle: Last\n---\nZ.\n",
    "_docs/_drafts/wip.md": "---\ntitle: WIP\n---\nSpecial directory, never read.\n",
    "_notes/tips.md": "---\ntags: one two\n---\nNo title: Jekyll titleizes the slug.\n",
    "_posts/2026-04-28-hello-world.md": (
        "---\ntitle: Hello\ncategories: [Data Science, News]\ndate: 2026-04-28T09:30:00Z\ntype: post\n---\n"
        '```dataview\nTABLE date AS Date\nFROM "_posts"\nSORT date DESC\n```\n'
    ),
    "_posts/tech/2025-01-05-older.md": "---\ntitle: Older\ntype: post\n---\nOlder post.\n",
    "_posts/2099-01-01-future.md": "---\ntitle: Future\n---\nNot yet.\n",
    "_posts/2025-02-02-unpublished.md": "---\ntitle: Unpublished\npublished: false\n---\nNo.\n",
    "_posts/not-dated.md": "---\ntitle: Not a post\n---\nA post needs a date in its name.\n",
    "blog/_posts/2025-03-03-nested.md": "---\ntitle: Nested\n---\nIn the category blog.\n",
}


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for rel, text in FILES.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text, encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def site(self) -> vault.Site:
        return vault.Reader(self.root, CONFIG, NOW).read()

    def item(self, path: str) -> vault.Item:
        return next(i for i in self.site().items if i.path == path)

    def test_reads_what_jekyll_reads(self):
        site = self.site()
        paths = {i.path for i in site.items}
        for read in ("index.md", "about.md", "wiki/index.md", "_docs/setup.md", "_notes/tips.md", "blog/_posts/2025-03-03-nested.md"):
            self.assertIn(read, paths)
        for skipped in ("wiki/_hidden.md", "private/secret.md", "_templates/t.md", "_docs/_drafts/wip.md",
                        "_posts/2099-01-01-future.md", "_posts/2025-02-02-unpublished.md", "_posts/not-dated.md"):  # fmt: skip
            self.assertNotIn(skipped, paths)
        self.assertIn(("notes.md", "/notes.md"), site.static_files)
        self.assertIn(("assets/pic.png", "/assets/pic.png"), site.static_files)

    def test_urls_are_jekylls(self):
        expected = {
            "index.md": "/",
            "about.md": "/about/",
            "wiki/index.md": "/wiki/",
            "wiki/topic.md": "/wiki/topic/",
            "_docs/setup.md": "/docs/setup/",
            "_docs/features/index.md": "/docs/features/index/",
            "_notes/tips.md": "/notes/tips/",
            "_posts/2026-04-28-hello-world.md": "/data%20science/news/2026/04/28/hello-world/",
            "_posts/tech/2025-01-05-older.md": "/2025/01/05/older/",
            "blog/_posts/2025-03-03-nested.md": "/blog/2025/03/03/nested/",
        }
        urls = {i.path: i.url for i in self.site().items}
        for path, url in expected.items():
            self.assertEqual(url, urls[path], path)

    def test_documents_get_the_data_jekyll_fills_in(self):
        tips = self.item("_notes/tips.md").data
        self.assertEqual(("Tips", "tips", ".md", ["one", "two"], [], False),
                         (tips["title"], tips["slug"], tips["ext"], tips["tags"], tips["categories"], tips["draft"]))  # fmt: skip
        older = self.item("_posts/tech/2025-01-05-older.md").data
        self.assertEqual(dt.datetime(2025, 1, 5, tzinfo=dt.timezone.utc), older["date"])
        hello = self.item("_posts/2026-04-28-hello-world.md").data
        self.assertEqual(dt.datetime(2026, 4, 28, 9, 30, tzinfo=dt.timezone.utc), hello["date"])
        self.assertEqual(["Data Science", "News"], hello["categories"])
        self.assertEqual("doc", self.item("_docs/setup.md").data["type"], "front matter defaults apply")
        self.assertNotIn("date", self.item("_docs/setup.md").data, "an undated document has no date")

    def test_collection_order_is_date_then_path(self):
        site = self.site()
        docs = [d.path for d in site.documents if d.collection == "docs"]
        self.assertEqual(["_docs/features/index.md", "_docs/features/z-last.md", "_docs/setup.md"], docs)
        posts = [d.path for d in site.documents if d.collection == "posts"]
        self.assertEqual(["_posts/tech/2025-01-05-older.md", "blog/_posts/2025-03-03-nested.md", "_posts/2026-04-28-hello-world.md"], posts)
        self.assertEqual(["posts", "docs", "notes"], list(dict.fromkeys(d.collection for d in site.documents)))

    def test_resolve_rewrites_the_markdown_and_keeps_the_front_matter(self):
        items = vault.resolve(self.root, CONFIG, NOW)
        index = (self.root / "index.md").read_text()
        self.assertTrue(index.startswith("---\ntitle: Home\npermalink: /\n---\n"))
        self.assertIn('<a href="/docs/setup/" class="wikilink">Setup</a>', index)
        about = (self.root / "about.md").read_text()
        self.assertIn('<a href="/notes/tips/" class="wikilink">Tips</a>', about, "a unique basename resolves")
        self.assertIn('<span class="wikilink-unresolved">missing</span>', about)
        wiki = (self.root / "wiki/index.md").read_text()
        self.assertIn("alert-success", wiki)
        self.assertIn("`[[_docs/setup]]`", wiki, "inline code is left alone")
        self.assertIn("![](/assets/pic.png)", (self.root / "wiki/topic.md").read_text())
        hello = (self.root / "_posts/2026-04-28-hello-world.md").read_text()
        self.assertIn("dataview-table", hello)
        self.assertLess(hello.index(">Hello<"), hello.index(">Older<"), "newest first")
        self.assertNotIn("Future", hello, "a future post is not in the pool")
        self.assertNotIn("Nested", hello, 'FROM "_posts" is the folder _posts, not blog/_posts')
        self.assertEqual("Never read.\n", (self.root / "wiki/_hidden.md").read_text().split("---\n")[-1])
        self.assertTrue(all(i.markdown for i in items))

    def test_resolve_writes_the_graph_index_as_a_page(self):
        vault.resolve(self.root, CONFIG, NOW)
        text = (self.root / vault.INDEX_PAGE).read_text()
        self.assertTrue(text.startswith("---\nlayout: null\nsitemap: false\nrender_with_liquid: false\npermalink: /assets/data/wiki-index.json\n---\n"))
        payload = json.loads(text.split("---\n", 2)[2])
        self.assertEqual("2026-10-22T12:00:00Z", payload["generated_at"])
        topic = next(e for e in payload["entries"] if e["basename"] == "topic")
        self.assertEqual("/zer0-pages/wiki/topic/", topic["url"], "graph URLs carry the base URL")
        self.assertIsNone(topic["collection"], "a page has no collection")
        self.assertEqual(["Old Topic", "wiki/topic"], topic["aliases"])
        setup = next(e for e in payload["entries"] if e["basename"] == "setup")
        self.assertEqual("docs", setup["collection"])
        home = next(e for e in payload["entries"] if e["title"] == "Home")
        self.assertEqual(["_docs/setup"], home["outgoing"], "edges come from the Markdown as written, before the rewrite")

    def test_postprocess_puts_the_base_url_on_built_pages(self):
        items = vault.resolve(self.root, CONFIG, NOW)
        out = self.root / "_site"
        (out / "wiki/topic").mkdir(parents=True)
        (out / "wiki/topic/index.html").write_text('<a href="/docs/setup/">x</a><code>href="/raw/"</code>')
        (out / "theme.html").write_text('<a href="/docs/setup/">not a vault page</a>')
        vault.postprocess(out, items, CONFIG)
        self.assertEqual('<a href="/zer0-pages/docs/setup/">x</a><code>href="/raw/"</code>', (out / "wiki/topic/index.html").read_text())
        self.assertEqual('<a href="/docs/setup/">not a vault page</a>', (out / "theme.html").read_text())

    def test_slugify_and_escape_are_jekylls(self):
        self.assertEqual("Hello-World.v2", vault.slugify("Hello World.v2", mode="pretty", cased=True))
        self.assertEqual("hello-world-v2", vault.slugify("Hello  World.v2"))
        self.assertEqual("café-au-lait", vault.slugify("Café au lait!"))
        self.assertEqual("/a%20b/c", vault.escape_path("/a b/c"))
        self.assertEqual("/plain/path.html", vault.escape_path("/plain/path.html"))
        self.assertEqual("/2026/04/28/x_/", vault.url_for("/:year/:month/:day/:title_/", {"year": "2026", "month": "04", "day": "28", "title": "x"}, drop=True))


if __name__ == "__main__":
    unittest.main()
