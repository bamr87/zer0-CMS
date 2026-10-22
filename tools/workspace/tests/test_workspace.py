"""Tests for the workspace tool (bin/zer0), ported from the Ruby suite
test_workspace.rb: the manifest's validation, file ownership and the affected
set, the structural checks, the vendored-copy contract, the task runner, the
doctor, release tags and the CLI's exit codes. Each test builds the small
throwaway workspace (fixtures.py) with its own git repository, so nothing here
depends on the real workspace.yml — test_real_manifest.py covers that one.
A few tests the Ruby suite lacked are marked "beyond the Ruby suite".

Run: python3 -m unittest discover tools/workspace
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workspace import cli  # noqa: E402
from workspace.checks import Checks  # noqa: E402
from workspace.doctor import Doctor  # noqa: E402
from workspace.manifest import Manifest, WorkspaceError  # noqa: E402
from workspace.ownership import Ownership, match  # noqa: E402
from workspace.runner import Runner, spawn_bash  # noqa: E402
from workspace.tags import Tags  # noqa: E402
from workspace.tests import fixtures  # noqa: E402
from workspace.vendor import Vendor  # noqa: E402


class WorkspaceCase(unittest.TestCase):
    def setUp(self):
        fixtures.isolate_git(self)
        tmp = Path(tempfile.mkdtemp(prefix="zer0-ws"))
        self.addCleanup(shutil.rmtree, tmp)
        self.root = tmp / "ws"
        self.build(self.root)

    def build(self, root: Path) -> None:
        fixtures.small_workspace(root)

    def write(self, rel: str, body: str) -> None:
        fixtures.write(self.root, rel, body)

    def edit(self, scenario: str) -> None:
        """Rewrite workspace.yml with one of the Ruby suite's edits (fixtures.EDITS)."""
        old, new = fixtures.EDITS[scenario]
        self.write("workspace.yml", fixtures.MANIFEST.replace(old, new, 1))

    def manifest(self) -> Manifest:
        return Manifest.load(self.root)

    def cli(self, *argv: str) -> tuple:
        out, err = io.StringIO(), io.StringIO()
        status = cli.main(list(argv), self.root, out, err)
        return status, out.getvalue(), err.getvalue()


class ManifestTest(WorkspaceCase):
    def test_loads_projects_in_order_with_tasks(self):
        m = self.manifest()
        self.assertEqual(m.names, ["root-app", "theme", "site"])
        self.assertEqual(m.project("theme").task("test").cwd, "lib")
        self.assertEqual(m.project("theme").task("check").cwd, ".")
        self.assertIsNone(m.project("site").workflow)
        self.assertEqual(m.project("theme").globs, ["packages/theme/**"])

    def test_dependents_are_transitive(self):
        self.write("workspace.yml", fixtures.with_blog())
        self.assertEqual(self.manifest().dependents_of("theme"), ["site", "blog"])

    def test_rejects_unknown_keys_kinds_tasks_and_dependencies(self):
        for scenario, message in (
            ("bad-kind", "kind must be one of"),
            ("bad-task", "unknown task lint"),
            ("bad-dep", "not a project"),
            ("bad-key", r"unknown key\(s\) colour"),
        ):
            with self.subTest(scenario):
                self.edit(scenario)
                with self.assertRaisesRegex(WorkspaceError, message):
                    self.manifest()

    def test_root_project_must_list_its_paths(self):
        self.edit("root-without-paths")
        with self.assertRaisesRegex(WorkspaceError, "must list the paths"):
            self.manifest()

    def test_rejects_cycles(self):
        self.edit("cycle")
        with self.assertRaisesRegex(WorkspaceError, "cycle"):
            self.manifest()

    def test_every_path_it_names_stays_inside_the_repository(self):  # beyond the Ruby suite
        for old, new, key in (
            ("path: packages/theme", "path: /etc", "projects.theme.path"),
            ('"package.json"]', '"package.json", "../x"]', "projects.root-app.paths"),
            ('site: "."', "site: docs/../..", "projects.site.site"),
            ("cwd: lib", "cwd: /tmp", "projects.theme.tasks.test.cwd"),
            ("copy: src/tokens.css", "copy: /tmp/victim.txt", "vendored[0].copy"),
            ("source: packages/theme/tokens.css", "source: ../tokens.css", "vendored[0].source"),
        ):
            with self.subTest(key):
                self.write("workspace.yml", fixtures.MANIFEST.replace(old, new, 1))
                with self.assertRaisesRegex(WorkspaceError, rf"^{re.escape(key)} must be a relative path inside"):
                    self.manifest()


class OwnershipTest(WorkspaceCase):
    def test_most_specific_glob_wins_and_workflows_map_to_their_project(self):
        o = Ownership(self.manifest())
        self.assertEqual(o.owner("src/a.ts"), "root-app")
        self.assertEqual(o.owner("package.json"), "root-app")
        self.assertEqual(o.owner("packages/theme/x/y.rb"), "theme")
        self.assertEqual(o.owner(".github/workflows/theme.yml"), "theme")
        self.assertIsNone(o.owner(".github/workflows/unrelated.yml"))
        self.assertIsNone(o.owner("docs/README.md"))
        self.assertIsNone(o.owner("packages/themes/x"), "a sibling with a longer name is not inside the project")

    def test_affected_adds_dependents_and_reports_unowned_files(self):
        r = Ownership(self.manifest()).affected(["packages/theme/a.rb", "docs/x.md"])
        self.assertEqual(r["affected"], ["theme", "site"])
        self.assertEqual(r["direct"], ["theme"])
        self.assertEqual(r["unowned"], ["docs/x.md"])

    def test_a_shared_workflow_affects_every_project_it_gates(self):
        self.edit("shared-workflow")
        o = Ownership(self.manifest())
        self.assertEqual(o.owners(".github/workflows/theme.yml"), ["theme", "site"])
        self.assertEqual(o.affected([".github/workflows/theme.yml"])["direct"], ["theme", "site"])

    def test_plain_globs_do_not_cross_directories(self):
        self.assertFalse(match("*.json", "a/b.json"))
        self.assertTrue(match("src/**", "src/deep/file"))

    def test_the_longest_literal_prefix_wins(self):  # beyond the Ruby suite
        self.write("workspace.yml", fixtures.MANIFEST.replace('"package.json"]', '"package.json", "packages/**"]', 1))
        o = Ownership(self.manifest())
        self.assertEqual(o.owner("packages/theme/x"), "theme")
        self.assertEqual(o.owner("packages/other/x"), "root-app")

    def test_globs_match_like_ruby_fnmatch(self):  # beyond the Ruby suite
        self.assertTrue(match("src/**/*.ts", "src/a/b/c.ts"))
        self.assertTrue(match("src/**/*.ts", "src/c.ts"), "**/ spans zero directories too")
        self.assertFalse(match("src/*", "src/a/b"))
        self.assertTrue(match("*.{json,yml}", "a.yml"))
        self.assertTrue(match("*.json", ".hidden.json"), "a dotfile matches *")


class ChecksTest(WorkspaceCase):
    def findings(self) -> list:
        return [str(f) for f in Checks(self.manifest()).run()]

    def assertFinding(self, text: str) -> None:
        self.assertTrue(any(text in f for f in self.findings()), f"no finding mentions {text!r}")

    def test_a_consistent_workspace_has_no_findings(self):
        self.assertEqual(self.findings(), [])

    def test_unregistered_container_directory_is_a_finding(self):
        self.write("apps/stray/README.md", "x")
        self.assertFinding("apps/stray/ is not registered")

    def test_missing_workflow_and_wrong_path_filter_are_findings(self):
        (self.root / ".github/workflows/root.yml").unlink()
        self.write(".github/workflows/theme.yml", 'on:\n  pull_request:\n    paths: ["elsewhere/**"]\n')
        self.assertFinding("root.yml, which does not exist")
        self.assertFinding("none is under packages/theme/")

    def test_none_without_a_reason_is_a_finding(self):
        self.edit("ci-none")
        self.assertFinding("without a reason")

    def test_glob_matching_no_tracked_file_is_a_finding(self):
        self.edit("gone-glob")
        self.assertFinding('"gone.txt" matches no tracked file')

    def with_route(self, route, pages_task=True, theme_route=None) -> None:
        self.write("workspace.yml", fixtures.with_route(route, pages_task, theme_route))

    def test_a_routed_site_with_a_pages_task_is_green(self):
        self.with_route("/site/")
        self.assertEqual(self.findings(), [])

    def test_publishing_pages_without_a_route_is_a_finding(self):
        self.with_route(None)
        self.assertFinding("publishes pages but has no route")

    def test_a_none_route_needs_a_reason_and_skips_the_task_requirement(self):
        self.with_route("none", pages_task=False)
        self.assertFinding("route is `none` without a reason")
        self.with_route("none — published elsewhere", pages_task=False)
        self.assertEqual(self.findings(), [])

    def test_a_malformed_route_or_a_missing_pages_task_is_a_finding(self):
        self.with_route("site")
        self.assertFinding("must look like /name/")
        self.with_route("/site/", pages_task=False)
        self.assertFinding("no `pages` task")

    def test_shared_or_nested_routes_are_findings_but_the_root_contains_everything(self):
        self.with_route("/site/", theme_route="/site/")
        self.assertFinding("share route /site/")
        self.with_route("/site/inner/", theme_route="/site/")
        self.assertFinding("overlap")
        self.with_route("/site/", theme_route="/")
        self.assertEqual(self.findings(), [])

    def test_routes_lists_the_root_first_as_json(self):
        self.with_route("/site/", theme_route="/")
        _, out, _ = self.cli("routes", "--json")
        self.assertEqual([(r["name"], r["route"]) for r in json.loads(out)], [("theme", "/"), ("site", "/site/")])

    def test_a_sites_render_setting_reaches_routes_list_and_info(self):  # PLAN P2, beyond the Ruby suite
        render = "    render: {as: jekyll-theme, theme: v1.31.3, server: jekyll-4}\n"
        self.write("workspace.yml", fixtures.with_route("/site/").replace('    site: "."\n', '    site: "."\n' + render, 1))
        setting = {"as": "jekyll-theme", "theme": "v1.31.3", "server": "jekyll-4", "before": None, "obsidian": False}
        _, out, _ = self.cli("routes", "--json")
        self.assertEqual([r.get("render") for r in json.loads(out)], [setting])
        _, out, _ = self.cli("list", "--json")
        self.assertEqual({p["name"]: p.get("render") for p in json.loads(out)}, {"root-app": None, "theme": None, "site": setting})
        self.assertNotIn("render", json.loads(out)[0], "a project without the setting lists as before")
        _, out, _ = self.cli("info", "site")
        self.assertIn("  render:     jekyll-theme v1.31.3, built by the jekyll-4 server\n", out)
        self.assertEqual(self.findings(), [])

    def test_vendored_drift_is_a_finding_and_vendor_write_repairs_it(self):
        self.write("packages/theme/tokens.css", "--x: 2;")
        self.assertFinding("src/tokens.css has drifted")
        self.assertEqual([v.copy for v in Vendor(self.manifest()).write()], ["src/tokens.css"])
        self.assertEqual((self.root / "src/tokens.css").read_text(), "--x: 2;")
        self.assertEqual(self.findings(), [])

    def test_vendor_never_writes_through_a_symlink_out_of_the_repository(self):  # beyond the Ruby suite
        victim = self.root.parent / "victim.css"
        victim.write_text("theirs")
        (self.root / "src/tokens.css").unlink()
        (self.root / "src/tokens.css").symlink_to(victim)
        for argv in (("vendor", "--write"), ("check",)):
            with self.subTest(argv=argv):
                status, out, err = self.cli(*argv)
                self.assertEqual((status, out), (2, ""))
                self.assertIn("bin/zer0: vendored src/tokens.css leads outside the repository", err)
        self.assertEqual(victim.read_text(), "theirs")


class RunnerTest(WorkspaceCase):
    def test_runs_in_the_task_directory_with_its_env_and_skips_projects_without_it(self):
        calls = []

        def spawn(env, command, folder):
            calls.append((env, command, os.path.realpath(folder)))
            return command != "exit 3"

        results = Runner(self.manifest(), out=io.StringIO(), spawn=spawn, keep_going=True).run(
            "test", ["root-app", "theme", "site"]
        )
        self.assertEqual([r.status for r in results], ["skipped", "failed", "skipped"])
        self.assertEqual(calls, [({}, "exit 3", os.path.realpath(self.root / "packages/theme/lib"))])

    def test_stops_at_the_first_failure_unless_told_to_keep_going(self):
        results = Runner(self.manifest(), out=io.StringIO(), spawn=lambda *_: False).run("check", ["root-app", "theme"])
        self.assertEqual([r.status for r in results], ["failed"])

    def test_dry_run_spawns_nothing(self):
        def spawn(*_):
            self.fail("a dry run must not spawn")

        results = Runner(self.manifest(), out=io.StringIO(), spawn=spawn, dry_run=True).run("check", ["theme"])
        self.assertEqual([r.status for r in results], ["skipped"])

    def test_bash_gets_the_task_env_in_the_task_directory(self):  # beyond the Ruby suite
        folder = self.root / "packages/theme/lib"
        self.assertTrue(spawn_bash({"ZER0_T": "yes"}, 'test "$ZER0_T" = yes && pwd -P > where', str(folder)))
        self.assertEqual((folder / "where").read_text().strip(), os.path.realpath(folder))
        self.assertFalse(spawn_bash({}, "true", str(self.root / "gone")), "a missing directory is a failure")


class CLITest(WorkspaceCase):
    def test_exit_codes(self):
        self.assertEqual(self.cli("list")[0], 0)
        self.assertEqual(self.cli("check")[0], 0)
        self.assertEqual(self.cli("vendor")[0], 0)
        self.assertEqual(self.cli("bogus")[0], 2)
        self.assertEqual(self.cli("info", "nope")[0], 2)
        self.assertEqual(self.cli("run", "lint")[0], 2)

    def test_run_reports_failure_with_status_one(self):
        status, out, _ = self.cli("run", "test", "theme")
        self.assertEqual(status, 1)
        self.assertRegex(out, r"failed\s+theme")

    def test_check_fails_on_drift(self):
        self.write("packages/theme/tokens.css", "--x: 9;")
        status, out, _ = self.cli("check")
        self.assertEqual(status, 1)
        self.assertIn("drifted", out)

    def test_affected_with_files_and_json(self):
        _, out, _ = self.cli("affected", "--files", "packages/theme/a,README.md", "--json")
        data = json.loads(out)
        self.assertEqual(data["affected"], ["theme", "site"])
        self.assertEqual(data["unowned"], ["README.md"])

    def test_matrix_lists_projects_with_the_task(self):
        _, out, _ = self.cli("matrix", "check")
        self.assertEqual(json.loads(out), ["root-app", "theme"])


class AffectedTest(WorkspaceCase):  # beyond the Ruby suite
    """`affected` without --files, as CI and `run --affected` use it: git's changes since the
    merge base, committed or not, and untracked files, each once and never quoted."""

    def build(self, root: Path) -> None:
        fixtures.small_workspace(root)
        fixtures.write(root, "docs/old.md", "x")
        fixtures.git(root, "add", "-A")
        fixtures.git(root, *fixtures.IDENTITY, "commit", "-q", "-m", "base")
        self.base = fixtures.git(root, "rev-parse", "HEAD").strip()

    def affected(self) -> dict:
        status, out, err = self.cli("affected", "--base", self.base, "--json")
        self.assertEqual((status, err), (0, ""))
        return json.loads(out)

    def test_committed_uncommitted_and_untracked_changes_each_count_once(self):
        self.write("src/a.ts", "b")
        fixtures.git(self.root, *fixtures.IDENTITY, "commit", "-q", "-am", "committed")  # root-app
        self.write("packages/theme/lib/.keep", "edited")  # uncommitted: theme
        self.write("sites/site/new.md", "new")  # untracked: site
        fixtures.git(self.root, "rm", "-q", "--cached", "docs/old.md")  # in git's diff and untracked: once
        everything = ["root-app", "theme", "site"]
        self.assertEqual(self.affected(), {"affected": everything, "direct": everything, "unowned": ["docs/old.md"]})
        status, out, _ = self.cli("run", "check", "--affected", "--base", self.base, "--dry-run")
        self.assertEqual(status, 0)
        self.assertEqual(re.findall(r"^==> (\S+): check", out, re.MULTILINE), ["root-app", "theme"])
        status, out, _ = self.cli("matrix", "check", "--affected", "--base", self.base)
        self.assertEqual((status, json.loads(out)), (0, ["root-app", "theme"]))

    def test_a_name_git_would_quote_still_has_its_owner(self):
        self.write('sites/site/say "hi".md', "x")
        fixtures.git(self.root, "add", "sites")
        fixtures.git(self.root, *fixtures.IDENTITY, "commit", "-q", "-m", "committed")
        self.write("packages/theme/café.css", "x")  # untracked
        self.assertEqual(self.affected(), {"affected": ["theme", "site"], "direct": ["theme", "site"], "unowned": []})


class DoctorTest(WorkspaceCase):
    def test_checks_every_declared_site_and_parses_the_result_line(self):
        seen = []

        def capture(root):
            seen.append(root)
            return "...\nresult: 2 error(s), 5 warning(s)\n"

        reports = Doctor(self.manifest(), capture=capture).run()
        self.assertEqual(seen, ["sites/site"])
        self.assertEqual([(r.errors, r.warnings) for r in reports], [(2, 5)])
        self.assertFalse(reports[0].ok)

    def test_a_doctor_that_prints_no_result_counts_as_an_error(self):
        self.assertEqual(Doctor(self.manifest(), capture=lambda _: "boom").run()[0].errors, 1)

    def test_a_project_without_a_site_root_is_refused(self):
        with self.assertRaises(WorkspaceError):
            Doctor(self.manifest(), capture=lambda _: "").run(["theme"])

    def test_site_root_joins_the_project_path(self):
        self.assertEqual(self.manifest().project("site").site_root, "sites/site")
        self.assertIsNone(self.manifest().project("theme").site_root)

    def test_without_ruby_it_says_so(self):  # beyond the Ruby suite: the doctor is Ruby until PLAN G4
        empty = self.root / "no-ruby-here"
        empty.mkdir()
        with mock.patch.dict(os.environ, {"PATH": str(empty)}):
            status, out, err = self.cli("doctor")
        self.assertEqual((status, out), (2, ""))
        self.assertIn("needs Ruby until PLAN G4", err)


class TagsTest(WorkspaceCase):
    def build(self, root: Path) -> None:
        self.remote = root.parent / "remote.git"
        fixtures.tags_workspace(root, self.remote)

    def remote_tags(self) -> list:
        out = fixtures.git(self.root, "ls-remote", "--tags", "--refs", "origin")
        return sorted(line.split("refs/tags/", 1)[1] for line in out.splitlines())

    def test_a_release_is_a_changelog_heading_and_a_bare_semver_without_one_is_inherited(self):
        groups = Tags(self.root).classify(["v10.0.0", "v0.2.0", "v2.0.0", "3.1.0", "content-v1.0.0", "v0.1.0"])
        self.assertEqual(groups.own, ["v0.1.0", "v0.2.0"])
        self.assertEqual(groups.inherited, ["v2.0.0", "3.1.0", "v10.0.0"])
        self.assertEqual(groups.other, ["content-v1.0.0"])

    def test_lists_by_default_and_deletes_only_the_inherited_tags_when_asked(self):
        status, out, _ = self.cli("tags", "--json")
        self.assertEqual(status, 0)
        self.assertEqual(
            json.loads(out),
            {"own": ["v0.1.0", "v0.2.0"], "inherited": ["3.1.0", "v9.0.0"], "other": ["content-v1.0.0"]},
        )

        status, out, _ = self.cli("tags", "--delete")
        self.assertEqual(status, 0)
        self.assertIn("deleted 2 inherited tag", out)
        self.assertEqual(self.remote_tags(), ["content-v1.0.0", "v0.1.0", "v0.2.0"])
        self.assertEqual(
            sorted(fixtures.git(self.root, "tag", "--list").split()), ["content-v1.0.0", "v0.1.0", "v0.2.0"]
        )

    def test_a_missing_changelog_is_a_usage_error_not_a_guess(self):
        (self.root / "CHANGELOG.md").unlink()
        status, _, err = self.cli("tags")
        self.assertEqual(status, 2)
        self.assertIn("CHANGELOG.md not found", err)

    def test_a_remote_that_refuses_the_delete_is_a_failure(self):  # beyond the Ruby suite
        hook = self.remote / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)
        with open(os.devnull, "w") as null, contextlib.ExitStack() as stack:
            saved = os.dup(2)  # git push reports the refusal on the real stderr
            stack.callback(os.close, saved)
            stack.callback(os.dup2, saved, 2)
            os.dup2(null.fileno(), 2)
            status, out, err = self.cli("tags", "--delete")
        self.assertEqual(status, 1)
        self.assertIn("deleted 0 inherited tag(s) from origin", out)
        self.assertEqual(err, "could not delete on origin: 3.1.0 v9.0.0\n")
        self.assertEqual(self.remote_tags(), ["3.1.0", "content-v1.0.0", "v0.1.0", "v0.2.0", "v9.0.0"])


if __name__ == "__main__":
    unittest.main()
