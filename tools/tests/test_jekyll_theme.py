"""Tests for tools/jekyll_theme.py — the Jekyll-theme option (PLAN P2).

Each test pins one promise the option makes to a site that takes it: the
setting is read from workspace.yml and refused when malformed; the exported tree
is what git tracks, with the site's config merged with the route's and the theme
pinned to the setting's tag (never the gem, never floating); a site's `before:`
command runs in the copy, never in the repository; an Obsidian vault is resolved
before the build and its built pages finished after; each server runs as its
upstream runs it, as the caller's user; the build writes only a new or empty
directory or the site's own `_site`, and refuses any other before it starts;
and it reports what it resolved.
No test runs Docker or reaches the network: `subprocess.run` is replaced where
the option would call them. Run: `python3 -m unittest discover tools/tests`.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import jekyll_theme as jt  # noqa: E402
from workspace.manifest import Manifest, WorkspaceError  # noqa: E402
from workspace.tests import fixtures  # noqa: E402

WORKSPACE = """\
version: 1
projects:
  blog:
    path: sites/blog
    kind: site
    summary: A site on the option.
    ci: none — a test
    site: "."
    route: /blog/
    render: {as: jekyll-theme, theme: v1.31.3, server: github-pages, before: echo made > made.txt}
    tasks:
      pages: python3 ../../tools/jekyll_theme.py build blog
  vault:
    path: sites/vault
    kind: site
    summary: An Obsidian vault on the option.
    ci: none — a test
    site: "."
    render: {as: jekyll-theme, theme: v1.28.0, server: jekyll-4, obsidian: true}
  plain:
    path: sites/plain
    kind: site
    summary: A site that has not moved.
    ci: none — a test
    site: "."
"""
FILES = {
    "sites/blog/_config.yml": "title: Blog\nurl: https://own.test\nbaseurl: /own\nremote_theme: bamr87/zer0-mistakes\n"
    "github_user: &user bamr87\nrepository: [*user, /, blog]\nplugins: [jekyll-feed]\n",
    "sites/blog/index.md": "---\ntitle: Home\n---\nHello.\n",
    "sites/vault/_config.yml": "title: Vault\nsource: pages\ndestination: _site\ntheme: jekyll-theme-zer0\nbaseurl: /vault\n"
    "plugins: [jekyll-seo-tag]\ncollections: {docs: {output: true, permalink: '/docs/:path/'}}\n",
    "sites/vault/pages/index.md": "---\ntitle: Home\n---\nSee [[_docs/setup|Setup]].\n",
    "sites/vault/pages/_docs/setup.md": "---\ntitle: Setup\n---\nInstall.\n",
    "sites/vault/README.md": "outside the Jekyll source",
    "sites/plain/_config.yml": "title: Plain\n",
}


class OptionCase(unittest.TestCase):
    def setUp(self):
        fixtures.isolate_git(self)
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        (self.root / "workspace.yml").write_text(WORKSPACE)
        for rel, text in FILES.items():
            (self.root / rel).parent.mkdir(parents=True, exist_ok=True)
            (self.root / rel).write_text(text)
        fixtures.git(self.root, "init", "-q")
        fixtures.git(self.root, "add", ".")
        (self.root / "sites/blog/untracked.md").write_text("---\n---\nnot in git, never exported\n")

    def tearDown(self):
        self.tmp.cleanup()

    def route(self) -> Path:
        path = self.root / "route.yml"
        path.write_text('url: "https://bamr87.github.io"\nbaseurl: "/zer0-CMS/blog"\n')
        return path


class SettingTest(OptionCase):
    def test_the_setting_is_read_from_workspace_yml(self):
        blog = Manifest.load(self.root).project("blog")
        self.assertEqual({"as": "jekyll-theme", "theme": "v1.31.3", "server": "github-pages", "before": "echo made > made.txt", "obsidian": False}, blog.render)
        self.assertIsNone(Manifest.load(self.root).project("plain").render)

    def test_a_malformed_setting_is_refused(self):
        for render, message in (
            ("jekyll-theme", "must be a mapping"),
            ("{as: react, theme: v1, server: jekyll-4}", ".as must be one of jekyll-theme"),
            ("{as: jekyll-theme, theme: v1, server: hugo}", ".server must be one of"),
            ("{as: jekyll-theme, server: jekyll-4}", ".theme must be the theme's tag"),
            ("{as: jekyll-theme, theme: 'main; rm -rf /', server: jekyll-4}", ".theme must be the theme's tag"),
            ("{as: jekyll-theme, theme: v1, server: jekyll-4, obsidian: yes please}", ".obsidian must be true or false"),
            ("{as: jekyll-theme, theme: v1, server: jekyll-4, colour: red}", "unknown key(s) colour"),
        ):
            (self.root / "workspace.yml").write_text(WORKSPACE.replace("render: {as: jekyll-theme, theme: v1.28.0, server: jekyll-4, obsidian: true}", f"render: {render}"))
            with self.subTest(render=render), self.assertRaises(WorkspaceError) as caught:
                Manifest.load(self.root)
            self.assertIn(message, str(caught.exception))

    def test_a_site_without_the_option_is_refused(self):
        with self.assertRaisesRegex(jt.OptionError, "plain does not render with the Jekyll-theme option"):
            jt.project("plain", self.root)


class ExportTest(OptionCase):
    def test_the_config_is_the_sites_merged_with_the_route_and_the_theme_pinned(self):
        source, config = jt.site_config(jt.project("blog", self.root), self.root, self.route())
        self.assertEqual(self.root / "sites/blog", source)
        self.assertEqual(("https://bamr87.github.io", "/zer0-CMS/blog"), (config["url"], config["baseurl"]))
        self.assertEqual("bamr87/zer0-mistakes@v1.31.3", config["remote_theme"])
        self.assertEqual(["jekyll-feed", "jekyll-remote-theme"], config["plugins"])
        self.assertEqual(["bamr87", "/", "blog"], config["repository"], "YAML anchors resolve")

    def test_a_gem_theme_and_a_source_directory_give_way_to_the_export(self):
        source, config = jt.site_config(jt.project("vault", self.root), self.root)
        self.assertEqual(self.root / "sites/vault/pages", source)
        for key in ("theme", "source", "destination"):
            self.assertNotIn(key, config)
        self.assertEqual("bamr87/zer0-mistakes@v1.28.0", config["remote_theme"])

    def test_export_copies_what_git_tracks_and_runs_before_in_the_copy(self):
        out = self.root / "out"
        jt.export("blog", out, self.route(), self.root)
        self.assertEqual(["_config.yml", "index.md", "made.txt"], sorted(p.name for p in out.iterdir()))
        self.assertFalse((self.root / "sites/blog/made.txt").exists(), "before: never runs in the repository")
        written = yaml.safe_load((out / "_config.yml").read_text())
        self.assertEqual("bamr87/zer0-mistakes@v1.31.3", written["remote_theme"])
        self.assertNotIn("&", (out / "_config.yml").read_text(), "no YAML aliases for a Ruby parser to trip on")

    def test_the_export_never_deletes_what_it_did_not_write(self):
        (self.root / "busy").mkdir()
        (self.root / "busy/keep.txt").write_text("mine")
        with self.assertRaisesRegex(jt.OptionError, "is not empty"):
            jt.export("blog", self.root / "busy", None, self.root)
        (self.root / "sites/blog/deleted.md").write_text("tracked, then deleted from the working tree")
        fixtures.git(self.root, "add", "sites/blog/deleted.md")
        (self.root / "sites/blog/deleted.md").unlink()
        self.assertNotIn("deleted.md", jt.tracked(self.root / "sites/blog", self.root))

    def test_a_failing_before_command_stops_the_export(self):
        (self.root / "workspace.yml").write_text(WORKSPACE.replace("before: echo made > made.txt", "before: exit 3"))
        with self.assertRaisesRegex(jt.OptionError, "its `before:` command failed"):
            jt.export("blog", self.root / "out", None, self.root)

    def test_an_obsidian_vault_is_resolved_in_the_export(self):
        out = self.root / "out"
        config, items = jt.export("vault", out, None, self.root)
        self.assertEqual(["_config.yml", "_docs", "assets", "index.md"], sorted(p.name for p in out.iterdir()))
        self.assertIn('<a href="/docs/setup/" class="wikilink">Setup</a>', (out / "index.md").read_text())
        self.assertTrue((out / "assets/data/wiki-index.json").is_file())
        self.assertEqual({"index.md", "_docs/setup.md"}, {i.path for i in items})
        self.assertEqual("See [[_docs/setup|Setup]].\n", (self.root / "sites/vault/pages/index.md").read_text().split("---\n")[-1])


class ServerTest(unittest.TestCase):
    def test_github_pages_runs_as_actions_jekyll_build_pages_does(self):
        command = jt.SERVERS["github-pages"].command(Path("/w"), "bamr87/irony-works")
        self.assertEqual(["docker", "run", "--rm", "--platform", "linux/amd64"], command[:5])
        self.assertEqual("ghcr.io/actions/jekyll-build-pages:v1.0.13", command[-1], "its own entrypoint, no arguments")
        env = dict(arg.split("=", 1) for arg in command if "=" in arg and not arg.startswith("/"))
        self.assertEqual(("site", "out", "/srv/work", "bamr87/irony-works"),
                         (env["INPUT_SOURCE"], env["INPUT_DESTINATION"], env["GITHUB_WORKSPACE"], env["GITHUB_REPOSITORY"]))  # fmt: skip
        self.assertIn("/w:/srv/work", command)

    def test_jekyll_4_builds_its_image_from_the_dockerfile(self):
        server = jt.SERVERS["jekyll-4"]
        self.assertRegex(server.tag, r"^zer0-cms-jekyll:[0-9a-f]{12}$")
        command = server.command(Path("/w"), "bamr87/zer0-CMS")
        self.assertEqual([server.tag, "build", "--source", "/srv/work/site", "--destination", "/srv/work/out"], command[-6:])
        self.assertIn("JEKYLL_ENV=production", command)
        if hasattr(__import__("os"), "getuid"):
            self.assertIn("--user", command, "the build's files belong to the caller")

    def test_the_jekyll_4_image_pins_every_gem(self):
        dockerfile = jt.SERVERS["jekyll-4"].dockerfile.read_text()
        self.assertIn("--ignore-dependencies", dockerfile)
        for gem in ("jekyll:4.4.1", "jekyll-remote-theme:0.6.2", "jekyll-feed:0.18.0", "jekyll-seo-tag:2.9.1", "kramdown:2.5.2"):
            self.assertIn(gem, dockerfile)


class BuildTest(OptionCase):
    def fake_run(self, calls: list):
        """subprocess.run, with Docker and git ls-remote answered here; anything else really runs."""
        real = subprocess.run

        def run(command, *args, **kwargs):
            calls.append(command)
            if command[:3] == ["docker", "image", "inspect"]:
                return subprocess.CompletedProcess(command, 0)
            if command[:2] == ["docker", "run"]:
                work = Path(command[command.index("-v") + 1].split(":")[0])
                (work / "out/docs/setup").mkdir(parents=True)
                (work / "out/index.html").write_text('<a href="/docs/setup/" class="wikilink">Setup</a>')
                (work / "out/docs/setup/index.html").write_text("<p>Install.</p>")
                return subprocess.CompletedProcess(command, 0)
            if command[:2] == ["git", "ls-remote"]:
                return subprocess.CompletedProcess(command, 0, stdout="227fed10\trefs/tags/v1.28.0\n")
            return real(command, *args, **kwargs)

        return run

    def test_build_runs_the_server_and_finishes_the_vaults_pages(self):
        calls: list = []
        dest = self.root / "site"
        with mock.patch.object(jt.shutil, "which", return_value="/usr/bin/docker"), mock.patch.object(jt.subprocess, "run", self.fake_run(calls)):
            facts = jt.build("vault", dest, root=self.root)
        self.assertEqual('<a href="/vault/docs/setup/" class="wikilink">Setup</a>', (dest / "index.html").read_text())
        self.assertEqual({"remote_theme": {"bamr87/zer0-mistakes@v1.28.0": "227fed10"}, "server": {"jekyll-4": jt.SERVERS["jekyll-4"].tag}}, facts)
        self.assertTrue(any(c[:2] == ["docker", "run"] for c in calls))

    def build(self, dest: Path, calls: list) -> dict:
        with mock.patch.object(jt.shutil, "which", return_value="/usr/bin/docker"), mock.patch.object(jt.subprocess, "run", self.fake_run(calls)):
            return jt.build("blog", dest, root=self.root)

    def test_the_build_never_deletes_a_directory_it_did_not_write(self):
        """A typo'd --dest or a stale ZER0_PAGES_DEST: the site's source, a directory in it, the sites, a
        populated directory outside the repository — each refused before the server runs, and left whole."""
        fixtures.write(self.root, "sites/blog/_posts/2020-01-01-hi.md", "---\n---\nhi\n")
        fixtures.git(self.root, "add", "sites/blog/_posts")
        outside = Path(tempfile.mkdtemp(prefix="not-a-build-")).resolve()
        self.addCleanup(shutil.rmtree, outside)
        (outside / "notes.txt").write_text("mine")
        (self.root / "sites/blog/_site").mkdir()
        fixtures.write(self.root, "sites/blog/_site/committed.html", "tracked")
        fixtures.git(self.root, "add", "sites/blog/_site")
        for dest in ("sites/blog", "sites/blog/_posts", "sites", str(outside), "sites/blog/_site", "sites/blog/index.md"):
            calls: list = []
            with self.subTest(dest=dest), self.assertRaisesRegex(jt.OptionError, "refusing to replace"):
                self.build(self.root / dest, calls)
            self.assertFalse(any(c[:2] == ["docker", "run"] for c in calls), f"{dest}: refused only after building")
        self.assertEqual("---\n---\nhi\n", (self.root / "sites/blog/_posts/2020-01-01-hi.md").read_text())
        self.assertEqual("mine", (outside / "notes.txt").read_text())
        self.assertEqual("tracked", (self.root / "sites/blog/_site/committed.html").read_text())

    def test_the_build_writes_a_new_or_empty_directory_and_replaces_only_the_sites_own_site(self):
        (self.root / "empty").mkdir()
        fixtures.write(self.root, "sites/blog/_site/stale.html", "from an earlier build")
        for dest in ("new/site", "empty", "sites/blog/_site"):
            with self.subTest(dest=dest):
                self.build(self.root / dest, [])
                self.assertEqual(["docs", "index.html"], sorted(p.name for p in (self.root / dest).iterdir()))

    def test_keep_reuses_only_its_own_directory(self):
        keep = self.root / "keep"
        (keep / "notes").mkdir(parents=True)
        with mock.patch.object(jt.shutil, "which", return_value="/usr/bin/docker"), mock.patch.object(
            jt.subprocess, "run", self.fake_run([])
        ), self.assertRaisesRegex(jt.OptionError, "holds other files \\(notes\\)"):
            jt.build("vault", self.root / "site", keep=keep, root=self.root)

    def test_a_tag_resolves_to_its_commit_not_its_tag_object(self):
        out = "aaaa\trefs/tags/v2\nbbbb\trefs/tags/v2^{}\n"
        with mock.patch.object(jt.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, stdout=out)):
            self.assertEqual("bbbb", jt.theme_commit("v2"))

    def test_without_docker_the_option_says_so(self):
        with mock.patch.object(jt.shutil, "which", return_value=None), self.assertRaisesRegex(jt.OptionError, "`docker` is not on PATH"):
            jt.build("vault", self.root / "site", root=self.root)

    def test_the_cli_writes_what_the_build_resolved(self):
        facts = {"remote_theme": {"bamr87/zer0-mistakes@v1.31.3": "98e978d"}, "server": {"github-pages": "img"}}
        out = self.root / "built-with.json"
        with mock.patch.object(jt, "build", return_value=facts) as build, redirect_stdout(io.StringIO()):
            self.assertEqual(0, jt.main(["build", "blog", "--dest", str(self.root / "d"), "--built-with", str(out)]))
        self.assertEqual(facts, json.loads(out.read_text()))
        self.assertEqual("blog", build.call_args.args[0])

    def test_the_cli_reports_a_site_without_the_option(self):
        err = io.StringIO()
        with mock.patch.object(jt, "ROOT", self.root), redirect_stderr(err):
            self.assertEqual(2, jt.main(["export", "nowhere", "--out", str(self.root / "o")]))
        self.assertIn("no project named", err.getvalue())


if __name__ == "__main__":
    unittest.main()
