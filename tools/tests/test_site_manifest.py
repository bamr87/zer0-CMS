"""Tests for tools/site_manifest.py — the recorder behind PLAN P1.

Each test builds a tiny site tree in a temporary directory and pins one promise
the recordings make to the milestones that must reproduce them (P2, P6, P7):
every path is listed with its type; a page's text is its own content — the
words, not the markup, and not the layout a theme puts around them, so a
renderer in another design system can match it; feeds keep their entries and
dates in order; sitemaps and redirects are read; the same tree always gives the
same bytes; a comparison names exactly what moved; and the rebuild is
pages.yml's, in its time zone and without the caller's build variables. No test
runs Jekyll or touches the network: the rebuild's commands are replaced by
functions that write a tree. Run: `python3 -m unittest tools/tests/test_site_manifest.py`.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_spec = importlib.util.spec_from_file_location(
    "site_manifest", Path(__file__).resolve().parent.parent / "site_manifest.py"
)
sm = importlib.util.module_from_spec(_spec)
sys.modules["site_manifest"] = sm
_spec.loader.exec_module(sm)

ATOM = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Site</title><updated>{updated}</updated>
  <entry><title type="html">Newest &amp; best</title><link href="https://x.test/b/" rel="alternate"/>
    <published>2026-10-20T08:00:00-06:00</published><updated>2026-10-21T00:00:00Z</updated><id>https://x.test/b/</id></entry>
  <entry><title>Older</title><link href="https://x.test/a/"/><id>tag:x.test,2026:a</id></entry>
</feed>
"""
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>S</title>
<item><title>One</title><link>https://x.test/1/</link><guid>id-1</guid><pubDate>Tue, 20 Oct 2026 08:00:00 -0600</pubDate></item>
<item><title>Two</title><link>https://x.test/2/</link></item>
</channel></rss>
"""
SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://x.test/z/</loc><lastmod>{updated}</lastmod></url>
  <url><loc>https://x.test/</loc></url>
</urlset>
"""
LOCK = """GEM
  remote: https://rubygems.org/
  specs:
    jekyll (4.4.1)
      addressable (~> 2.4)
    jekyll-feed (0.18.0)
      jekyll (>= 3.7, < 5.0)
    nokogiri (1.18.10-x86_64-linux-gnu)
      racc (~> 1.4)

PLATFORMS
  x86_64-linux

DEPENDENCIES
  jekyll (~> 4.3)

BUNDLED WITH
   2.6.9
"""

# The layout a Jekyll theme writes around a page (title banner, reading time, share and edit
# menus, table of contents, sidebar) — the way the recorded builds do, in their own class names.
INTRO = (
    '<div class="bd-intro"><h1 class="bd-intro-title">About</h1><p>About the garden</p><ul><li>Iris Vance</li>'
    '<li><a href="https://github.com/x/y/blob/main/about.md">View source</a></li></ul>'
    '<p class="bd-intro-meta">Estimated reading time: 1 minute</p><div class="dropdown"><button>Share</button>'
    '<ul class="dropdown-menu"><li><a href="#">Share on Reddit</a></li></ul></div><a href="#">Edit on GitHub</a></div>'
)
TOC = '<div class="bd-toc"><div class="offcanvas-header"><h2>Table of Contents</h2></div><p>On this page</p></div>'


def page(body: str, title: str = "A page") -> str:
    head = f"<title>{title}</title><style>p{{color:red}}</style>"
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


def themed(column: str) -> str:
    sidebar = '<aside class="bd-sidebar"><ul><li>Every other page</li></ul></aside>'
    main = f'<main><div class="container">{sidebar}<div class="bd-main">{INTRO}{TOC}{column}</div></div></main>'
    return page(f"<header>Marginalia</header>{main}<footer>©</footer>", "About | Marginalia")


def tree(root: Path, files: dict[str, str | bytes]) -> Path:
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            path.write_bytes(content)
        else:
            path.write_text(content, encoding="utf-8")
    return root


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


SITE = {
    "index.html": page(
        "<header>Site name</header><main><h1>Home</h1><p>Welcome, reader.</p></main><footer>©</footer>", "Home | Site"
    ),
    "about/index.html": page("<main><h1>About</h1><p>We write.</p></main>", "About"),
    "old/index.html": "<!DOCTYPE html><html><head><title>Redirecting…</title>"
    '<meta http-equiv="refresh" content="0; url=https://x.test/about/"></head><body></body></html>',
    "assets/app.css": "body{}",
    "assets/app.js": "1;",
    "assets/logo.png": b"\x89PNG\r\n",
    "assets/font.woff2": b"wOF2",
    "feed.xml": ATOM.format(updated="2026-10-21T00:00:00Z"),
    "sitemap.xml": SITEMAP.format(updated="2026-10-21"),
    "robots.txt": "Sitemap: https://x.test/sitemap.xml\n",
    "CNAME": "x.test\n",
}


class TempTree(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp)


class ManifestTest(TempTree):
    def build(self, files: dict, name: str = "site") -> dict:
        return sm.manifest(tree(self.tmp / name, files), "demo")

    def test_every_path_is_listed_with_its_media_type(self):
        paths = self.build(SITE)["paths"]
        self.assertEqual(sorted(paths), sorted(SITE))
        types = {p: e["type"] for p, e in paths.items()}
        self.assertEqual(types["index.html"], "text/html")
        self.assertEqual(types["assets/app.css"], "text/css")
        self.assertEqual(types["assets/app.js"], "text/javascript")
        self.assertEqual(types["assets/logo.png"], "image/png")
        self.assertEqual(types["assets/font.woff2"], "font/woff2")
        self.assertEqual(types["feed.xml"], "application/xml")
        self.assertEqual(types["robots.txt"], "text/plain")
        self.assertEqual(types["CNAME"], "application/octet-stream")
        self.assertNotIn("title", paths["assets/app.css"])

    def test_an_html_page_has_its_title_its_text_and_the_texts_digest(self):
        entry = self.build(SITE)["paths"]["index.html"]
        self.assertEqual(entry["title"], "Home | Site")
        self.assertEqual(entry["text"], ["Home", "Welcome, reader."])
        self.assertEqual(entry["text_sha256"], digest("Home Welcome, reader."))

    def test_the_layout_around_a_themes_content_column_is_left_out(self):
        column = '<div id="page-content" class="bd-content ps-lg-2"><h1 id="about">About</h1><p>I read a lot.</p></div>'
        # the same words in another design system: the page's own title in a header, the rest in <main>
        renderer = page(
            "<main><header><h1>About</h1><p>Iris Vance · 1 min read</p></header><h1>About</h1>"
            "<p>I read a <em>lot</em>.</p></main>"
        )
        paths = self.build({"themed.html": themed(column), "renderer.html": renderer})["paths"]
        self.assertEqual(paths["themed.html"]["text"], ["About", "I read a lot."])
        self.assertEqual(paths["themed.html"]["text_sha256"], paths["renderer.html"]["text_sha256"])

    def test_an_entrys_marked_content_wins_over_the_column_around_it(self):
        post = (
            '<div class="bd-content"><article class="h-entry"><header><h1>Title</h1><time>Oct 21</time></header>'
            '<div class="post-content e-content"><p>The words.</p></div><footer>Share this note</footer>'
            '<section class="backlinks"><h3>Linked mentions 1</h3></section></article></div>'
        )
        schema_org = '<main><p>Related</p><div itemprop="articleBody"><p>Schema words.</p></div></main>'
        paths = self.build({"post.html": themed(post), "schema.html": page(schema_org)})["paths"]
        self.assertEqual(paths["post.html"]["text"], ["The words."])
        self.assertEqual(paths["schema.html"]["text"], ["Schema words."])

    def test_without_a_marked_content_it_is_main_else_the_articles_else_the_body(self):
        paths = self.build(
            {
                "main.html": page("<p>outside</p><main><article><p>card</p></article><p>more</p></main>"),
                "articles.html": page("<p>chrome</p><article>one</article><div>between</div><article>two</article>"),
                "body.html": page(
                    "<header>masthead</header><nav>menu</nav><p>Just a body.</p><footer>fine print</footer>"
                ),
                "fragment.html": "<p>No body at all.</p>",
            }
        )["paths"]
        self.assertEqual(paths["main.html"]["text"], ["card", "more"])
        self.assertEqual(paths["articles.html"]["text"], ["one", "two"])
        self.assertEqual(paths["body.html"]["text"], ["Just a body."])
        self.assertEqual(paths["fragment.html"]["text"], ["No body at all."])

    def test_elements_that_are_never_content_are_left_out(self):
        main = (
            "<main><aside><ul><li>Every other page</li></ul></aside><nav>Breadcrumbs</nav>"
            "<article><header><h1>Title</h1><time>Oct 21</time></header><div><p>The words.</p>"
            '<p><time datetime="2026-10-22T05:43:45+00:00">Published Oct 22, 2026</time></p>'
            "<script>var built = Date.now();</script><style>.x{}</style><noscript>Enable JS</noscript>"
            "<template><p>later</p></template><button>Copy</button><svg><title>icon</title><text>A</text></svg>"
            "</div><footer>Share this</footer></article></main>"
        )
        self.assertEqual(self.build({"p.html": page(main)})["paths"]["p.html"]["text"], ["The words."])

    def test_the_digest_follows_the_words_not_the_markup(self):
        jekyll = page(
            '<main>\n  <div class="content">\n    <p>A&nbsp;quick <em>brown</em>  fox.</p>\n'
            "<p>Next&amp;last</p>\n  </div>\n</main>"
        )
        react = page("<main><section><p>A quick <strong>brown</strong> fox.</p><p>Next&#38;last</p></section></main>")
        glued = page("<main><p>A quick brown fox.Next&amp;last</p></main>")
        paths = self.build({"jekyll.html": jekyll, "react.html": react, "glued.html": glued})["paths"]
        self.assertEqual(paths["jekyll.html"]["text"], ["A quick brown fox.", "Next&last"])
        self.assertEqual(paths["jekyll.html"]["text_sha256"], digest("A quick brown fox. Next&last"))
        self.assertEqual(paths["jekyll.html"]["text_sha256"], paths["react.html"]["text_sha256"])
        self.assertNotEqual(paths["jekyll.html"]["text_sha256"], paths["glued.html"]["text_sha256"])

    def test_the_title_is_the_documents_not_an_inline_svgs(self):
        body = "<body><svg><title>Logo</title></svg><main>x</main></body>"
        html = f"<html><head><title>  Real\n title </title></head>{body}</html>"
        untitled = f"<html>{body}</html>"
        paths = self.build({"a.html": html, "b.html": untitled})["paths"]
        self.assertEqual(paths["a.html"]["title"], "Real title")
        self.assertEqual(paths["b.html"]["title"], "")

    def test_feed_entries_keep_their_order_and_dates_and_sitemaps_are_sorted(self):
        result = self.build(
            {**SITE, "rss.xml": RSS, "data.xml": "<data><loc>not a sitemap</loc></data>", "bad.xml": "<oops"}
        )
        self.assertEqual(
            result["feeds"]["feed.xml"],
            [
                {
                    "id": "https://x.test/b/",
                    "link": "https://x.test/b/",
                    "title": "Newest & best",
                    "published": "2026-10-20T14:00:00+00:00",  # the instant, in UTC, however it was spelled
                    "updated": "2026-10-21T00:00:00+00:00",
                },
                {
                    "id": "tag:x.test,2026:a",
                    "link": "https://x.test/a/",
                    "title": "Older",
                    "published": "",
                    "updated": "",
                },
            ],
        )
        self.assertEqual(
            result["feeds"]["rss.xml"],
            [
                {
                    "id": "id-1",
                    "link": "https://x.test/1/",
                    "title": "One",
                    "published": "2026-10-20T14:00:00+00:00",
                    "updated": "",
                },
                {
                    "id": "https://x.test/2/",
                    "link": "https://x.test/2/",
                    "title": "Two",
                    "published": "",
                    "updated": "",
                },
            ],
        )
        self.assertEqual(result["sitemaps"], {"sitemap.xml": ["https://x.test/", "https://x.test/z/"]})
        self.assertNotIn("data.xml", result["feeds"])
        self.assertIn("bad.xml", result["paths"])

    def test_meta_refresh_pages_are_redirects(self):
        result = self.build(SITE)
        self.assertEqual(result["redirects"], {"old/index.html": "https://x.test/about/"})
        self.assertEqual(result["paths"]["old/index.html"]["title"], "Redirecting…")

    def test_the_same_tree_always_gives_the_same_bytes(self):
        reversed_site = dict(reversed(list(SITE.items())))
        first = sm.dumps(self.build(SITE, "one"))
        second = sm.dumps(self.build(reversed_site, "two"))
        # what a build stamps with its own clock (the feed's update time, sitemap lastmods) does not count
        rebuilt = sm.dumps(
            self.build(
                {
                    **SITE,
                    "feed.xml": ATOM.format(updated="2027-01-01T00:00:00Z"),
                    "sitemap.xml": SITEMAP.format(updated="2027-01-01"),
                },
                "three",
            )
        )
        self.assertEqual(first, second)
        self.assertEqual(first, rebuilt)
        self.assertTrue(first.endswith("}\n"))
        self.assertEqual(list(json.loads(first)), sorted(json.loads(first)))
        self.assertEqual(json.loads(first)["schema"], "site-manifest/v2")
        self.assertNotIn("built_with", json.loads(first))


class BuiltWithTest(TempTree):
    def test_the_gems_and_the_remote_themes_commit_are_what_the_build_resolved(self):
        source = tree(
            self.tmp / "site", {"Gemfile.lock": LOCK, "_config.yml": 'title: x\nremote_theme  : "owner/theme"\n'}
        )
        run = mock.Mock(return_value=mock.Mock(stdout="98e978d21f2d\tHEAD\n"))
        with mock.patch.object(sm.subprocess, "run", run):
            resolved = sm.built_with(source)
        self.assertEqual(
            resolved,
            {
                "gems": {"jekyll": "4.4.1", "jekyll-feed": "0.18.0", "nokogiri": "1.18.10"},
                "remote_theme": {"owner/theme": "98e978d21f2d"},
            },
        )
        self.assertEqual(run.call_args.args[0], ["git", "ls-remote", "https://github.com/owner/theme", "HEAD"])
        (source / "_config.yml").write_text("remote_theme: owner/theme@v2.1\n", encoding="utf-8")
        with mock.patch.object(sm.subprocess, "run", run):
            sm.built_with(source)
        self.assertEqual(run.call_args.args[0][-1], "v2.1")
        # no git, or no answer: the theme is named and its commit left unknown, never guessed
        for answer in (mock.Mock(side_effect=FileNotFoundError("git")), mock.Mock(return_value=mock.Mock(stdout=""))):
            with mock.patch.object(sm.subprocess, "run", answer):
                self.assertEqual(sm.built_with(source)["remote_theme"], {"owner/theme@v2.1": ""})

    def test_a_gem_theme_and_no_lockfile_resolve_nothing_remote(self):
        source = tree(self.tmp / "site", {"_config.yml": "theme: some-gem-theme\n"})
        with mock.patch.object(sm.subprocess, "run") as run:
            self.assertEqual(sm.built_with(source), {"gems": {}})
        run.assert_not_called()

    def test_what_resolved_differently_is_reported_and_not_counted(self):
        recorded = {
            "schema": sm.SCHEMA,
            "paths": {},
            "built_with": {"gems": {"a": "1", "b": "2"}, "remote_theme": {"o/t": "aaa"}},
        }
        fresh = {**recorded, "built_with": {"gems": {"a": "1", "b": "3", "c": "1"}, "remote_theme": {"o/t": "bbb"}}}
        self.assertEqual(sm.compare(recorded, fresh), [])
        self.assertEqual(
            sm.resolved_differently(recorded, fresh),
            ["gems: b 2 → 3", "gems: c (none) → 1", "remote_theme: o/t aaa → bbb"],
        )
        self.assertEqual(sm.resolved_differently(recorded, {**fresh, "built_with": {"gems": {}}}), [])


class CompareTest(TempTree):
    def setUp(self):
        super().setUp()
        self.recorded = sm.manifest(tree(self.tmp / "a", SITE), "demo")

    def candidate(self, changes: dict, drop: tuple = ()) -> dict:
        files = {k: v for k, v in {**SITE, **changes}.items() if k not in drop}
        return sm.manifest(tree(Path(tempfile.mkdtemp(dir=self.tmp)), files), "demo")

    def test_a_faithful_rebuild_has_no_differences(self):
        self.assertEqual(sm.compare(self.recorded, self.candidate({})), [])

    def test_each_kind_of_difference_is_named(self):
        moved = ATOM.replace(
            '<entry><title>Older</title><link href="https://x.test/a/"/><id>tag:x.test,2026:a</id></entry>', ""
        )
        candidate = self.candidate(
            {
                "about/index.html": page("<main><h1>About</h1><p>We write books.</p></main>", "About us"),
                "new/index.html": page("<main>new</main>"),
                "assets/app.js": "2;",  # bytes of a non-page file are not recorded
                "feed.xml": moved,
                "sitemap.xml": SITEMAP.format(updated="x").replace("https://x.test/z/", "https://x.test/y/"),
                "old/index.html": SITE["old/index.html"].replace("/about/", "/about-us/"),
            },
            drop=("robots.txt",),
        )
        older = (
            '{"id": "tag:x.test,2026:a", "link": "https://x.test/a/", "published": "", "title": "Older", "updated": ""}'
        )
        self.assertEqual(
            sm.compare(self.recorded, candidate),
            [
                "missing  robots.txt",
                "extra    new/index.html",
                "title    about/index.html: 'About' → 'About us'",
                "text     about/index.html",
                "         -We write.",
                "         +We write books.",
                f"feed     feed.xml: missing {older}",
                'sitemap  sitemap.xml: missing "https://x.test/z/"',
                'sitemap  sitemap.xml: extra "https://x.test/y/"',
                "redirect old/index.html: https://x.test/about/ → https://x.test/about-us/",
            ],
        )

    def test_a_shifted_entry_date_is_a_difference_and_a_respelled_one_is_not(self):
        shifted = self.candidate({"feed.xml": ATOM.format(updated="x").replace("2026-10-20T08", "2026-10-19T08")})
        self.assertEqual(
            len(sm.compare(self.recorded, shifted)), 2
        )  # the entry as recorded is missing, the shifted one extra
        self.assertIn("2026-10-19T14:00:00+00:00", sm.compare(self.recorded, shifted)[1])
        respelled = ATOM.format(updated="x").replace("2026-10-20T08:00:00-06:00", "2026-10-20T14:00:00.000Z")
        self.assertEqual(sm.compare(self.recorded, self.candidate({"feed.xml": respelled})), [])

    def test_the_pages_scope_leaves_out_every_file_that_is_not_a_page(self):
        renderer = self.candidate(
            {"assets/bundle-3f2a.js": "x", "about/index.html": page("<main>changed</main>", "About")},
            drop=("assets/app.css", "assets/app.js", "assets/logo.png", "assets/font.woff2", "robots.txt"),
        )
        self.assertEqual(
            sm.compare(self.recorded, renderer, pages=True),
            ["text     about/index.html", "         -About", "         -We write.", "         +changed"],
        )
        self.assertIn("missing  assets/app.css", sm.compare(self.recorded, renderer))
        lost = self.candidate({}, drop=("about/index.html", "feed.xml"))
        self.assertEqual(
            sm.compare(self.recorded, lost, pages=True), ["missing  about/index.html", "feed     feed.xml: missing"]
        )

    def test_a_long_text_difference_is_cut_short(self):
        words = [f"<p>word {n}</p>" for n in range(20)]
        candidate = self.candidate({"about/index.html": page(f"<main>{''.join(words)}</main>", "About")})
        lines = sm.compare(self.recorded, candidate)
        self.assertEqual(lines[0], "text     about/index.html")
        self.assertEqual(lines[13], "         … 10 more")

    def test_a_reordered_feed_and_a_lost_feed_are_differences(self):
        entries = self.recorded["feeds"]["feed.xml"]
        reordered = {**self.recorded, "feeds": {"feed.xml": entries[::-1]}}
        self.assertEqual(sm.compare(self.recorded, reordered), ["feed     feed.xml: reordered"])
        self.assertEqual(sm.compare(self.recorded, {**self.recorded, "feeds": {}}), ["feed     feed.xml: missing"])

    def test_a_schema_change_is_reported_alone(self):
        self.assertEqual(
            sm.compare(self.recorded, {**self.recorded, "schema": "site-manifest/v1"}),
            ["schema   site-manifest/v2 → site-manifest/v1"],
        )


class CommandLineTest(TempTree):
    def run_main(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            code = sm.main([str(a) for a in argv])
        return code, out.getvalue()

    def test_build_writes_and_compare_exits_by_the_result(self):
        site = tree(self.tmp / "_site", SITE)
        a, b = self.tmp / "a.json", self.tmp / "b.json"
        self.assertEqual(self.run_main("build", site, "--site", "demo", "--out", a)[0], 0)
        self.assertEqual(self.run_main("build", site, "--site", "demo", "--out", b)[0], 0)
        self.assertEqual(a.read_bytes(), b.read_bytes())
        self.assertEqual(json.loads(a.read_text(encoding="utf-8"))["site"], "demo")
        self.assertEqual(self.run_main("compare", a, b), (0, f"{b} against {a}: identical\n"))
        (site / "index.html").unlink()
        (site / "assets/app.css").unlink()
        self.run_main("build", site, "--site", "demo", "--out", b)
        code, out = self.run_main("compare", a, b)
        self.assertEqual(code, 1)
        self.assertIn("missing  index.html", out)
        self.assertIn("missing  assets/app.css", out)
        code, out = self.run_main("compare", "--pages", a, b)
        self.assertEqual((code, "assets/app.css" in out), (1, False))
        self.assertEqual(
            self.run_main("compare", self.tmp / "none.json", b), (1, f"nothing recorded at {self.tmp / 'none.json'}\n")
        )

    def test_build_with_its_source_records_what_the_build_resolved(self):
        site, source = tree(self.tmp / "_site", SITE), tree(self.tmp / "src", {"Gemfile.lock": LOCK})
        self.run_main("build", site, "--site", "demo", "--out", self.tmp / "m.json", "--source", source)
        self.assertEqual(
            json.loads((self.tmp / "m.json").read_text(encoding="utf-8"))["built_with"]["gems"]["jekyll"], "4.4.1"
        )

    def test_check_and_write_rebuild_each_routed_site(self):
        plan = [
            {"name": "alpha", "path": "sites/alpha", "route": "/alpha/", "bundle_dir": "sites/alpha"},
            {"name": "beta", "path": "sites/beta", "route": "/beta/", "bundle_dir": "sites/beta"},
        ]
        built = []
        contents = {"alpha": SITE, "beta": SITE}
        resolved = {"gems": {"jekyll": "4.4.1"}}

        def fake_rebuild(route, dest):
            built.append(route["name"])
            tree(dest, contents[route["name"]])
            return resolved

        fixtures = self.tmp / "fixtures"
        with (
            mock.patch.object(sm, "routes", return_value=plan),
            mock.patch.object(sm, "rebuild", side_effect=fake_rebuild),
        ):
            self.assertEqual(self.run_main("--check", "--fixtures", fixtures)[0], 1)  # nothing recorded yet
            self.assertEqual(self.run_main("--write", "--fixtures", fixtures)[0], 0)
            recording = json.loads((fixtures / "alpha" / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(recording["built_with"], resolved)
            self.assertEqual(self.run_main("--check", "--fixtures", fixtures)[0], 0)
            resolved["gems"] = {"jekyll": "4.4.2"}  # another gem version alone is a note, not a difference
            code, out = self.run_main("--check", "--site", "alpha", "--fixtures", fixtures)
            self.assertEqual(code, 0)
            self.assertIn("gems: jekyll 4.4.1 → 4.4.2", out)
            contents["beta"] = {**SITE, "about/index.html": page("<main>changed</main>", "About")}
            code, out = self.run_main("--check", "--fixtures", fixtures)
            self.assertEqual(code, 1)
            self.assertIn("text     about/index.html", out)
            contents["beta"] = {k: v for k, v in SITE.items() if k != "assets/app.js"}
            self.assertEqual(self.run_main("--check", "--site", "beta", "--fixtures", fixtures)[0], 1)
            self.assertEqual(self.run_main("--check", "--pages", "--site", "beta", "--fixtures", fixtures)[0], 0)
            built.clear()
            self.assertEqual(self.run_main("--check", "--site", "alpha", "--fixtures", fixtures)[0], 0)
            self.assertEqual(built, ["alpha"])
            with self.assertRaises(SystemExit):
                self.run_main("--check", "--site", "gamma", "--fixtures", fixtures)

    def test_a_failed_build_is_a_failure_and_records_nothing(self):
        plan = [{"name": "alpha", "path": "sites/alpha", "route": "/alpha/", "bundle_dir": "sites/alpha"}]
        fixtures = self.tmp / "fixtures"
        with mock.patch.object(sm, "routes", return_value=plan), mock.patch.object(sm, "rebuild", return_value=None):
            self.assertEqual(self.run_main("--write", "--fixtures", fixtures)[0], 1)
        self.assertFalse((fixtures / "alpha").exists())


class RebuildTest(TempTree):
    def rebuild(self, lockfile_committed: bool) -> tuple[dict | None, list]:
        source = tree(self.tmp / "sites/drsai", {"_config.yml": "remote_theme: owner/theme\n"})
        if lockfile_committed:
            (source / "Gemfile.lock").write_text(LOCK, encoding="utf-8")
        calls = []

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["git", "ls-remote"]:
                return mock.Mock(stdout="abc123\tHEAD\n")
            env = kwargs["env"]
            calls.append((cmd, kwargs["cwd"], env))
            if cmd == ["bundle", "install"]:
                (source / "Gemfile.lock").write_text(LOCK.replace("4.4.1", "4.4.2"), encoding="utf-8")
            else:
                calls.append(Path(env["ZER0_PAGES_CONFIG"]).read_text(encoding="utf-8"))
                tree(Path(env["ZER0_PAGES_DEST"]), {"index.html": page("<main>x</main>")})
            return mock.Mock(returncode=0)

        caller = {
            "JEKYLL_ENV": "development",
            "ZER0_ANY_LOCAL_CHECKOUT": "/src",
            "BUNDLE_GEMFILE": "/other/Gemfile",
            "OCTOKIT_ACCESS_TOKEN": "t",
            "PAGES_ENV": "dotcom",
            "TZ": "America/Denver",
            "KEPT": "1",
        }
        with (
            mock.patch.object(sm, "ROOT", self.tmp),
            mock.patch.dict(os.environ, caller),
            mock.patch.object(sm.subprocess, "run", side_effect=fake_run),
        ):
            route = {"name": "drsai", "path": "sites/drsai", "route": "/drsai/", "bundle_dir": "sites/drsai"}
            return sm.rebuild(route, self.tmp / "out"), calls

    def test_the_rebuild_is_the_pages_workflows(self):
        resolved, ((install, install_dir, _), (pages, pages_dir, env), config) = self.rebuild(lockfile_committed=False)
        self.assertEqual((install, install_dir), (["bundle", "install"], self.tmp / "sites/drsai"))
        self.assertEqual((pages[1:], pages_dir), (["run", "pages", "drsai"], self.tmp))
        self.assertEqual(config, 'url: "https://bamr87.github.io"\nbaseurl: "/zer0-CMS/drsai"\n')
        self.assertEqual(env["ZER0_PAGES_BASEURL"], "/zer0-CMS/drsai")
        self.assertEqual(env["ZER0_PAGES_DEST"], str(self.tmp / "out"))
        self.assertEqual(env["PAGES_REPO_NWO"], "bamr87/zer0-CMS")
        self.assertEqual((env["LANG"], env["LC_ALL"]), ("C.UTF-8", "C.UTF-8"))
        self.assertEqual(env["TZ"], "UTC")  # pages.yml's runners: a post dated just after midnight UTC keeps its URL
        for inherited in (
            "JEKYLL_ENV",
            "ZER0_ANY_LOCAL_CHECKOUT",
            "BUNDLE_GEMFILE",
            "OCTOKIT_ACCESS_TOKEN",
            "PAGES_ENV",
        ):
            self.assertNotIn(inherited, env)
        self.assertEqual(env["KEPT"], "1")
        self.assertEqual(
            resolved,
            {
                "gems": {"jekyll": "4.4.2", "jekyll-feed": "0.18.0", "nokogiri": "1.18.10"},
                "remote_theme": {"owner/theme": "abc123"},
            },
        )
        self.assertFalse((self.tmp / "sites/drsai/Gemfile.lock").exists())  # the next run resolves afresh, as CI does

    def test_a_committed_lockfile_is_left_alone(self):
        self.rebuild(lockfile_committed=True)
        self.assertTrue((self.tmp / "sites/drsai/Gemfile.lock").exists())

    def test_pages_yml_builds_and_records_the_same_way(self):
        """The rebuild restates pages.yml's build step; this holds the two together."""
        workflow = (sm.ROOT / ".github" / "workflows" / "pages.yml").read_text(encoding="utf-8")
        for fragment in (
            f"vars.PAGES_URL || '{sm.PAGES_URL}'",
            f"vars.PAGES_BASE_PATH || '{sm.PAGES_BASE_PATH}'",
            "PAGES_REPO_NWO: ${{ github.repository }}",
            'baseurl="${PAGES_BASE_PATH%/}${ROUTE%/}"',
            """printf 'url: "%s"\\nbaseurl: "%s"\\n' "$PAGES_URL" "$baseurl" > "$RUNNER_TEMP/route.yml\"""",
            'export ZER0_PAGES_CONFIG="$RUNNER_TEMP/route.yml" ZER0_PAGES_DEST="$RUNNER_TEMP/out"',
            'bin/zer0 run pages "$NAME"',
            "LC_ALL: C.UTF-8",
            "TZ: UTC",
            'tools/site_manifest.py build "$RUNNER_TEMP/out" --site "$NAME" --source "$SOURCE"',
            'tools/site_manifest.py compare "web/site/fixtures/$NAME/manifest.json"',
        ):
            self.assertIn(fragment, workflow)
        self.assertNotIn("JEKYLL_ENV", workflow)


if __name__ == "__main__":
    unittest.main()
