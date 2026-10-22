"""Tests for tools/site_manifest.py — the recorder behind PLAN P1.

Each test builds a tiny site tree in a temporary directory and pins one promise
the recordings make to the milestones that must reproduce them (P2, P6, P7):
every path is listed with its type, a page's digest follows its words and not
its markup or its theme chrome, feeds keep their entries in order, sitemaps and
redirects are read, the same tree always gives the same bytes, and a comparison
names exactly what moved. No test runs Jekyll or touches the network: the
rebuild is replaced by a function that writes a tree. Run:
`python3 -m unittest tools/tests/test_site_manifest.py`.
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
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
  <entry><title type="html">Newest &amp; best</title><link href="https://x.test/b/" rel="alternate"/><id>https://x.test/b/</id></entry>
  <entry><title>Older</title><link href="https://x.test/a/"/><id>tag:x.test,2026:a</id></entry>
</feed>
"""
RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>S</title>
<item><title>One</title><link>https://x.test/1/</link><guid>id-1</guid></item>
<item><title>Two</title><link>https://x.test/2/</link></item>
</channel></rss>
"""
SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://x.test/z/</loc><lastmod>{updated}</lastmod></url>
  <url><loc>https://x.test/</loc></url>
</urlset>
"""


def page(body: str, title: str = "A page") -> str:
    head = f"<title>{title}</title><style>p{{color:red}}</style>"
    return f"<!doctype html><html><head>{head}</head><body>{body}</body></html>"


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

    def test_an_html_page_has_its_title_and_the_digest_of_its_main_text(self):
        paths = self.build(SITE)["paths"]
        self.assertEqual(paths["index.html"]["title"], "Home | Site")
        self.assertEqual(paths["index.html"]["text_sha256"], digest("Home Welcome, reader."))

    def test_the_main_text_comes_from_main_else_the_articles_else_the_body(self):
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
        self.assertEqual(paths["main.html"]["text_sha256"], digest("card more"))
        self.assertEqual(paths["articles.html"]["text_sha256"], digest("one two"))
        self.assertEqual(paths["body.html"]["text_sha256"], digest("Just a body."))
        self.assertEqual(paths["fragment.html"]["text_sha256"], digest("No body at all."))

    def test_theme_chrome_inside_main_is_left_out(self):
        main = (
            "<main><aside><ul><li>Every other page</li></ul></aside><nav>Breadcrumbs</nav>"
            "<article><header><h1>Title</h1><time>Oct 21</time></header><div><p>The words.</p>"
            '<p><time datetime="2026-10-22T05:43:45+00:00">Published Oct 22, 2026</time></p>'
            "<script>var built = Date.now();</script><style>.x{}</style><noscript>Enable JS</noscript>"
            "<template><p>later</p></template><button>Copy</button><svg><title>icon</title><text>A</text></svg>"
            "</div><footer>Share this</footer></article></main>"
        )
        self.assertEqual(self.build({"p.html": page(main)})["paths"]["p.html"]["text_sha256"], digest("The words."))

    def test_the_digest_follows_the_words_not_the_markup(self):
        jekyll = page(
            '<main>\n  <div class="content">\n    <p>A&nbsp;quick <em>brown</em>  fox.</p>\n'
            "<p>Next&amp;last</p>\n  </div>\n</main>"
        )
        react = page("<main><section><p>A quick <strong>brown</strong> fox.</p><p>Next&#38;last</p></section></main>")
        glued = page("<main><p>A quick brown fox.Next&amp;last</p></main>")
        paths = self.build({"jekyll.html": jekyll, "react.html": react, "glued.html": glued})["paths"]
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

    def test_feed_entries_keep_their_order_and_sitemaps_are_sorted(self):
        result = self.build(
            {**SITE, "rss.xml": RSS, "data.xml": "<data><loc>not a sitemap</loc></data>", "bad.xml": "<oops"}
        )
        self.assertEqual(
            result["feeds"]["feed.xml"],
            [
                {"id": "https://x.test/b/", "link": "https://x.test/b/", "title": "Newest & best"},
                {"id": "tag:x.test,2026:a", "link": "https://x.test/a/", "title": "Older"},
            ],
        )
        self.assertEqual(
            result["feeds"]["rss.xml"],
            [
                {"id": "id-1", "link": "https://x.test/1/", "title": "One"},
                {"id": "https://x.test/2/", "link": "https://x.test/2/", "title": "Two"},
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
        # what a build stamps outside the recorded facts (feed and sitemap dates) does not count
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
        self.assertEqual(json.loads(first)["schema"], "site-manifest/v1")


class CompareTest(TempTree):
    def setUp(self):
        super().setUp()
        self.recorded = sm.manifest(tree(self.tmp / "a", SITE), "demo")

    def candidate(self, changes: dict, drop: tuple = ()) -> dict:
        files = {k: v for k, v in {**SITE, **changes}.items() if k not in drop}
        return sm.manifest(tree(self.tmp / "b", files), "demo")

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
        self.assertEqual(
            sm.compare(self.recorded, candidate),
            [
                "missing  robots.txt",
                "extra    new/index.html",
                "title    about/index.html: 'About' → 'About us'",
                "text     about/index.html",
                'feed     feed.xml: missing {"id": "tag:x.test,2026:a", "link": "https://x.test/a/", "title": "Older"}',
                'sitemap  sitemap.xml: missing "https://x.test/z/"',
                'sitemap  sitemap.xml: extra "https://x.test/y/"',
                "redirect old/index.html: https://x.test/about/ → https://x.test/about-us/",
            ],
        )

    def test_a_reordered_feed_and_a_lost_feed_are_differences(self):
        entries = self.recorded["feeds"]["feed.xml"]
        reordered = {**self.recorded, "feeds": {"feed.xml": entries[::-1]}}
        self.assertEqual(sm.compare(self.recorded, reordered), ["feed     feed.xml: reordered"])
        self.assertEqual(sm.compare(self.recorded, {**self.recorded, "feeds": {}}), ["feed     feed.xml: missing"])

    def test_a_schema_change_is_reported_alone(self):
        self.assertEqual(
            sm.compare(self.recorded, {**self.recorded, "schema": "site-manifest/v2"}),
            ["schema   site-manifest/v1 → site-manifest/v2"],
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
        self.run_main("build", site, "--site", "demo", "--out", b)
        code, out = self.run_main("compare", a, b)
        self.assertEqual(code, 1)
        self.assertIn("missing  index.html", out)

    def test_check_and_write_rebuild_each_routed_site(self):
        plan = [
            {"name": "alpha", "path": "sites/alpha", "route": "/alpha/", "bundle_dir": "sites/alpha"},
            {"name": "beta", "path": "sites/beta", "route": "/beta/", "bundle_dir": "sites/beta"},
        ]
        built = []
        contents = {"alpha": SITE, "beta": SITE}

        def fake_rebuild(route, dest):
            built.append(route["name"])
            tree(dest, contents[route["name"]])
            return True

        fixtures = self.tmp / "fixtures"
        with (
            mock.patch.object(sm, "routes", return_value=plan),
            mock.patch.object(sm, "rebuild", side_effect=fake_rebuild),
        ):
            self.assertEqual(self.run_main("--check", "--fixtures", fixtures)[0], 1)  # nothing recorded yet
            self.assertEqual(self.run_main("--write", "--fixtures", fixtures)[0], 0)
            self.assertTrue((fixtures / "alpha" / "manifest.json").is_file())
            self.assertEqual(self.run_main("--check", "--fixtures", fixtures)[0], 0)
            contents["beta"] = {**SITE, "about/index.html": page("<main>changed</main>", "About")}
            code, out = self.run_main("--check", "--fixtures", fixtures)
            self.assertEqual(code, 1)
            self.assertIn("text     about/index.html", out)
            built.clear()
            self.assertEqual(self.run_main("--check", "--site", "alpha", "--fixtures", fixtures)[0], 0)
            self.assertEqual(built, ["alpha"])
            with self.assertRaises(SystemExit):
                self.run_main("--check", "--site", "gamma", "--fixtures", fixtures)

    def test_a_failed_build_is_a_failure_and_records_nothing(self):
        plan = [{"name": "alpha", "path": "sites/alpha", "route": "/alpha/", "bundle_dir": "sites/alpha"}]
        fixtures = self.tmp / "fixtures"
        with mock.patch.object(sm, "routes", return_value=plan), mock.patch.object(sm, "rebuild", return_value=False):
            self.assertEqual(self.run_main("--write", "--fixtures", fixtures)[0], 1)
        self.assertFalse((fixtures / "alpha").exists())

    def test_the_rebuild_is_the_pages_workflows(self):
        calls = []

        def fake_run(cmd, cwd, env):
            calls.append((cmd, cwd, {k: env[k] for k in env if k.startswith(("ZER0_PAGES", "PAGES_", "LANG"))}))
            if cmd[-2:] == ["pages", "drsai"]:
                config = Path(env["ZER0_PAGES_CONFIG"]).read_text(encoding="utf-8")
                calls.append(config)
                tree(Path(env["ZER0_PAGES_DEST"]), {"index.html": page("<main>x</main>")})
            return mock.Mock(returncode=0)

        route = {"name": "drsai", "path": "sites/drsai", "route": "/drsai/", "bundle_dir": "sites/drsai"}
        with mock.patch.object(sm.subprocess, "run", side_effect=fake_run):
            self.assertTrue(sm.rebuild(route, self.tmp / "out"))
        (install, install_dir, _), (pages, pages_dir, env), config = calls
        self.assertEqual((install, install_dir), (["bundle", "install"], sm.ROOT / "sites/drsai"))
        self.assertEqual((pages[1:], pages_dir), (["run", "pages", "drsai"], sm.ROOT))
        self.assertEqual(config, 'url: "https://bamr87.github.io"\nbaseurl: "/zer0-CMS/drsai"\n')
        self.assertEqual(env["ZER0_PAGES_BASEURL"], "/zer0-CMS/drsai")
        self.assertEqual(env["ZER0_PAGES_DEST"], str(self.tmp / "out"))
        self.assertEqual(env["PAGES_REPO_NWO"], "bamr87/zer0-CMS")
        self.assertEqual(env["LANG"], "C.UTF-8")


if __name__ == "__main__":
    unittest.main()
