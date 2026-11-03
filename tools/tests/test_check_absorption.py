"""Tests for tools/check_absorption.py — the ADR 0006 gate.

Each test pins one way the absorption can go wrong silently: Ruby added in a
new place, Ruby growing under an old one, a directory deleted before its
capabilities moved, a capability marked done with nothing proving it — or with a
proof that names a test its file no longer has —, a studio capability whose
extension cell is simply absent, one dropped without the owner's word, or the CI
step that runs the gate passing when the gate fails. Run:
`python3 -m unittest discover tools/tests`.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "check_absorption", Path(__file__).resolve().parent.parent / "check_absorption.py"
)
ca = importlib.util.module_from_spec(_spec)
sys.modules["check_absorption"] = ca
_spec.loader.exec_module(ca)


def heads(mapping: dict[str, bytes]):
    return lambda path: mapping.get(path, b"")


class IsRubyTest(unittest.TestCase):
    def test_extensions_and_names(self):
        h = heads({})
        for path in ("a/b.rb", "x.rake", "config.ru", "v.html.erb", "g.gemspec", "s/Gemfile", "Gemfile.lock", "Rakefile", ".ruby-version"):
            self.assertTrue(ca.is_ruby(path, h), path)
        for path in ("a.py", "Gemfile.md", "README", "x.rbs.txt"):
            self.assertFalse(ca.is_ruby(path, h), path)

    def test_shebang_only_for_extensionless_files(self):
        h = heads({"bin/zer0": b"#!/usr/bin/env ruby\n", "bin/tool": b"#!/usr/bin/env python3\n", "x.sh": b"#!/usr/bin/env ruby\n"})
        self.assertTrue(ca.is_ruby("bin/zer0", h))
        self.assertFalse(ca.is_ruby("bin/tool", h))
        self.assertFalse(ca.is_ruby("x.sh", h))


class RatchetTest(unittest.TestCase):
    def test_within_ceiling_passes(self):
        errors, counts = ca.check_ratchet(["rails/a.rb", "rails/b.rb"], {"rails/": 2})
        self.assertEqual(errors, [])
        self.assertEqual(counts["rails/"], 2)

    def test_growth_fails(self):
        errors, _ = ca.check_ratchet(["rails/a.rb", "rails/b.rb"], {"rails/": 1})
        self.assertEqual(len(errors), 1)
        self.assertIn("grew", errors[0])

    def test_new_place_fails(self):
        errors, _ = ca.check_ratchet(["content/x.rb"], {"rails/": 5})
        self.assertIn("outside the ratchet", errors[0])

    def test_prefix_matches_whole_segments_and_longest_wins(self):
        self.assertIsNone(ca.owning_prefix("railsy/a.rb", ["rails/"]))
        self.assertEqual(ca.owning_prefix("rails/lib/a.rb", ["rails/", "rails/lib/"]), "rails/lib/")
        self.assertEqual(ca.owning_prefix("bin/zer0", ["bin/zer0"]), "bin/zer0")

    def test_tighten_never_raises_and_drops_zeroes(self):
        self.assertEqual(ca.tighten({"a/": 5, "b/": 2, "c/": 3}, Counter({"a/": 3, "b/": 4})), {"a/": 3, "b/": 2})

    def test_write_ratchet_rewrites_only_its_block(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.yml"
            p.write_text("schema: capabilities/v1\n# keep me\nruby_ratchet:\n  a/: 5\n  b/: 2\n\nsources: []\n")
            ca.write_ratchet(p, {"a/": 3})
            self.assertEqual(p.read_text(), "schema: capabilities/v1\n# keep me\nruby_ratchet:\n  a/: 3\n\nsources: []\n")


def source(path="apps/x", **cap):
    base = {"id": "x.one", "status": "missing", "target": "content/x"}
    base.update(cap)
    return {"id": "x", "path": path, "capabilities": [base]}


class LedgerTest(unittest.TestCase):
    def test_open_capability_with_source_present_passes(self):
        self.assertEqual(ca.check_ledger([source()], lambda p: True), [])

    def test_deleted_source_with_open_capability_fails(self):
        errors = ca.check_ledger([source()], lambda p: False)
        self.assertEqual(len(errors), 1)
        self.assertIn("is gone", errors[0])

    def test_deleted_source_fully_absorbed_passes(self):
        exists = lambda p: p == "content/tests/test_x.py"
        self.assertEqual(ca.check_ledger([source(status="done", proof="content/tests/test_x.py::test_it")], exists), [])

    def test_done_needs_existing_proof(self):
        self.assertIn("without a proof", ca.check_ledger([source(status="done")], lambda p: True)[0])
        self.assertIn("does not exist", ca.check_ledger([source(status="done", proof="tests/test_nope.py")], lambda p: p == "apps/x")[0])

    def test_a_proof_is_a_test_not_a_tool_or_a_command(self):
        for proof in ("tools/site_manifest.py::--check --site drsai", "tools/site_manifest.py", ".github/workflows/pages.yml::build",
                      "content/tests/test_x.py::run it by hand", "content/tests/test_x.py::"):  # fmt: skip
            with self.subTest(proof=proof):
                self.assertIn("is not a test", ca.check_ledger([source(status="done", proof=proof)], lambda p: True)[0])
        for proof in ("content/tests/api/test_pages.py::test_publish", "tools/workspace/tests/test_golden.py::FrozenTreeTest",
                      "content/tests/x.py::SomeTest::test_it[case-1]", "web/packages/ui/test/editor.test.tsx", "src/x_test.py"):  # fmt: skip
            with self.subTest(proof=proof):
                self.assertEqual(ca.check_ledger([source(status="done", proof=proof)], lambda p: True), [])
        cap = platform_cap(ops="done")
        cap["proof"] = {"ops": "tools/site_manifest.py::--check --site drsai"}
        self.assertIn("ops proof 'tools/site_manifest.py::--check --site drsai' is not a test", ca.check_platform([cap], lambda p: True)[0])

    def test_dropped_needs_owner(self):
        self.assertIn("decided_by", ca.check_ledger([source(status="dropped")], lambda p: True)[0])
        self.assertEqual(ca.check_ledger([source(status="dropped", decided_by="ADR 0006")], lambda p: True), [])

    def test_specified_needs_the_owners_decision_and_a_spec_that_exists(self):
        spec = "docs/plan/x-spec.md#rails.x"
        exists = lambda p: p == "docs/plan/x-spec.md"
        self.assertIn("decided_by", ca.check_ledger([source(status="specified", spec=spec)], exists)[0])
        self.assertIn("without a spec", ca.check_ledger([source(status="specified", decided_by="owner")], exists)[0])
        gone = source(status="specified", decided_by="owner", spec="docs/plan/gone.md")
        self.assertIn("spec docs/plan/gone.md does not exist", ca.check_ledger([gone], exists)[0])
        self.assertEqual(ca.check_ledger([source(status="specified", decided_by="owner", spec=spec)], exists), [])

    def test_deleted_source_whose_open_rows_are_specified_passes(self):
        exists = lambda p: p == "docs/plan/x-spec.md"
        row = source(status="specified", decided_by="owner, 2026-10-27", spec="docs/plan/x-spec.md")
        self.assertEqual(ca.check_ledger([row], exists), [])

    def test_bad_status_missing_target_and_duplicates(self):
        self.assertIn("status", ca.check_ledger([source(status="later")], lambda p: True)[0])
        self.assertIn("no target", ca.check_ledger([source(target="")], lambda p: True)[0])
        twice = source()
        twice["capabilities"].append(dict(twice["capabilities"][0]))
        self.assertIn("duplicate", ca.check_ledger([twice], lambda p: True)[0])


class LedgerTargetTest(unittest.TestCase):
    def test_target_must_be_a_platform_capability(self):
        self.assertIn("not a platform capability", ca.check_ledger([source()], lambda p: True, {"other"})[0])
        self.assertEqual(ca.check_ledger([source()], lambda p: True, {"content/x"}), [])

    def test_dropped_rows_need_no_live_target(self):
        self.assertEqual(ca.check_ledger([source(status="dropped", decided_by="owner")], lambda p: True, set()), [])

    def test_specified_rows_keep_a_live_target(self):
        row = source(status="specified", decided_by="owner", spec="docs/plan/x-spec.md")
        self.assertIn("not a platform capability", ca.check_ledger([row], lambda p: True, set())[0])


def platform_cap(**surfaces):
    return {"id": "content.create", "what": "create pages", "surfaces": surfaces or {"studio": "missing"}}


class PlatformTest(unittest.TestCase):
    def test_valid_catalog_passes(self):
        self.assertEqual(ca.check_platform([platform_cap(studio="missing", extension="missing", api="partial")], lambda p: True), [])

    def test_unknown_surface_and_status_fail(self):
        errors = ca.check_platform([platform_cap(desktop="done", studio="soon")], lambda p: True)
        self.assertTrue(any("unknown surface" in e for e in errors))
        self.assertTrue(any("status 'soon'" in e for e in errors))

    def test_done_surface_needs_existing_proof(self):
        cap = platform_cap(api="done")
        self.assertIn("without a proof", ca.check_platform([cap], lambda p: True)[0])
        cap["proof"] = {"api": "content/tests/test_api.py::test_create"}
        self.assertEqual(ca.check_platform([cap], lambda p: p == "content/tests/test_api.py"), [])
        self.assertIn("does not exist", ca.check_platform([cap], lambda p: False)[0])

    def test_duplicates_and_missing_fields(self):
        errors = ca.check_platform([platform_cap(), platform_cap(), {"id": "x"}], lambda p: True)
        self.assertTrue(any("duplicate" in e for e in errors))
        self.assertTrue(any("no what" in e for e in errors))
        self.assertTrue(any("no surfaces" in e for e in errors))

    def test_parity_gaps_list_every_studio_row_the_extension_does_not_match(self):
        caps = [
            platform_cap(studio="done", extension="missing"),
            dict(platform_cap(studio="done"), id="b"),
            dict(platform_cap(studio="partial", extension="partial"), id="c"),
            dict(platform_cap(studio="done"), id="d", extension_gap="first-run setup precedes any token"),
            dict(platform_cap(api="done"), id="e"),
        ]  # fmt: skip
        self.assertEqual(ca.parity_gaps(caps), [
            "content.create: studio done, extension missing",
            "b: studio done, no extension cell",
            "d: studio done, extension not owed — first-run setup precedes any token",
        ])  # fmt: skip

    def test_a_studio_row_without_an_extension_cell_needs_a_reason(self):
        self.assertEqual(
            ca.check_platform([platform_cap(studio="partial")], lambda p: True),
            ["platform/content.create: a studio surface and no extension cell (give it an extension status, or extension_gap: <why the extension does not owe it>)"],
        )
        gap = dict(platform_cap(studio="missing"), extension_gap="the install wizard runs before anyone holds a token")
        self.assertEqual(ca.check_platform([gap], lambda p: True), [])
        for bad in ("", "  ", None):
            with self.subTest(extension_gap=bad):
                errors = ca.check_platform([dict(platform_cap(studio="missing"), extension_gap=bad)], lambda p: True)
                self.assertTrue(any("extension_gap needs its reason" in e for e in errors), errors)
        both = dict(platform_cap(studio="missing", extension="missing"), extension_gap="not owed")
        self.assertIn("extension_gap on a row that has an extension cell", ca.check_platform([both], lambda p: True)[0])
        self.assertEqual(ca.check_platform([platform_cap(api="partial")], lambda p: True), [])  # no studio, nothing owed


TEST_PY = b'''
import pytest

def test_alone():
    pass

@pytest.mark.parametrize("case", [1, 2])
def test_cases(case):
    pass

class SyncTest:
    def test_runs(self):
        def test_hidden():
            pass

    class Nested:
        async def test_deep(self):
            pass

if True:
    def test_conditional():
        pass
'''

TEST_TSX = b"""
describe('Distribute', () => {
  it('drafts a post of the page for a channel and leads to the queue', async () => {});
  it("shows the guard's findings", () => {});
  test(
    `follows its log live`,
    () => {},
  );
  it.skip('a test that does not run', () => {});
});
const label = 'a string that is no test';
"""


class ProofResolutionTest(unittest.TestCase):
    """A proof's `::` id is looked up in its file: a Python test by its name, a TypeScript test by its title."""

    files = {"content/tests/test_sync.py": TEST_PY, "web/packages/ui/test/distribution.test.tsx": TEST_TSX, "src/test/core.test.ts": b"suite('core', () => { test('reads front matter', () => {}); });"}  # fmt: skip

    def problem(self, proof):
        return ca.proof_problem(proof, lambda p: p in self.files, heads(self.files))

    def test_a_proof_naming_a_test_that_is_not_in_the_file_fails(self):
        self.assertEqual(self.problem("content/tests/test_sync.py::test_alone"), None)
        self.assertEqual(
            self.problem("content/tests/test_sync.py::test_renamed"),
            "proof names test_renamed, which is not in content/tests/test_sync.py",
        )
        for gone in ("test_hidden", "test_conditional", "test_runs", "SyncTest::test_hidden", "test_alone::test_x", "SyncTest::test_deep"):
            with self.subTest(test=gone):
                self.assertIn("which is not in", self.problem(f"content/tests/test_sync.py::{gone}"))
        cap = platform_cap(api="done")
        cap["proof"] = {"api": "content/tests/test_sync.py::test_renamed"}
        errors = ca.check_platform([cap], lambda p: p in self.files, heads(self.files))
        self.assertEqual(errors, ["platform/content.create: api proof names test_renamed, which is not in content/tests/test_sync.py"])
        row = source(status="done", proof="content/tests/test_sync.py::test_renamed")
        self.assertIn("which is not in", ca.check_ledger([row], lambda p: True, read=heads(self.files))[0])

    def test_a_class_and_method_id_resolves(self):
        for found in ("SyncTest", "SyncTest::test_runs", "SyncTest::Nested::test_deep", "test_cases[1]", "SyncTest::test_runs[x-y]"):
            with self.subTest(test=found):
                self.assertIsNone(self.problem(f"content/tests/test_sync.py::{found}"))
        self.assertIn("is not a test", self.problem('content/tests/test_sync.py::"test_alone"'))

    def test_a_quoted_vitest_title_resolves(self):
        tsx = "web/packages/ui/test/distribution.test.tsx"
        for title in ("drafts a post of the page for a channel and leads to the queue", "shows the guard's findings", "follows its log live", "Distribute"):
            with self.subTest(title=title):
                self.assertIsNone(self.problem(f'{tsx}::"{title}"'))
        self.assertIsNone(self.problem('src/test/core.test.ts::"reads front matter"'))  # Mocha's tdd suite and test
        for absent in ("drafts a post", "a test that does not run", "a string that is no test"):
            with self.subTest(title=absent):
                self.assertEqual(self.problem(f'{tsx}::"{absent}"'), f'proof names "{absent}", which is not in {tsx}')
        for unquoted in (f"{tsx}::Distribute", f"{tsx}::''", f'{tsx}::""'):
            with self.subTest(proof=unquoted):
                self.assertIn("is not a test", self.problem(unquoted))

    def test_without_a_reader_only_the_file_is_checked(self):
        self.assertIsNone(ca.proof_problem("content/tests/test_sync.py::test_renamed", lambda p: True))


class ProofListTest(unittest.TestCase):
    def test_a_surface_may_name_several_proofs(self):
        files = {"content/tests/test_a.py": b"def test_a(): pass\n", "content/tests/test_b.py": b"class BTest:\n    def test_b(self): pass\n"}
        exists, read = (lambda p: p in files), heads(files)
        cap = platform_cap(ops="done")
        cap["proof"] = {"ops": ["content/tests/test_a.py::test_a", "content/tests/test_b.py::BTest::test_b", "content/tests/test_b.py"]}
        self.assertEqual(ca.check_platform([cap], exists, read), [])
        cap["proof"]["ops"] = ["content/tests/test_a.py::test_a", "content/tests/test_gone.py", "tools/site_manifest.py"]
        self.assertEqual(ca.check_platform([cap], exists, read), [
            "platform/content.create: ops proof content/tests/test_gone.py does not exist",
            "platform/content.create: ops proof 'tools/site_manifest.py' is not a test (a test file, optionally ::<test id>, or ::\"<title>\" in a .ts/.tsx test)",
        ])  # fmt: skip
        cap["proof"]["ops"] = []
        self.assertEqual(ca.check_platform([cap], exists, read), ["platform/content.create: ops done without a proof"])

    def test_a_proof_named_on_an_open_cell_must_hold_too(self):
        cap = platform_cap(api="partial")
        cap["proof"] = {"api": "content/tests/test_gone.py::test_x"}
        self.assertEqual(ca.check_platform([cap], lambda p: False), ["platform/content.create: api proof content/tests/test_gone.py does not exist"])


# The shell GitHub runs a `run:` step with on Linux (docs: workflow syntax, `jobs.<job_id>.steps[*].shell`):
# with no `shell:`, `bash -e {0}` — so a pipeline's status is its last command's —, and with `shell: bash`,
# `bash --noprofile --norc -eo pipefail {0}`.
GITHUB_SHELLS = {None: ["bash", "-e"], "bash": ["bash", "--noprofile", "--norc", "-eo", "pipefail"]}
FAILING_GATE = '#!/bin/sh\ncase "$*" in *check_absorption.py*) echo "absorption gate: 1 problem(s)" >&2; exit 1;; esac\n'


class WorkflowTest(unittest.TestCase):
    def test_the_gate_step_fails_when_the_gate_fails(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/zer0-workspace.yml").read_text())
        found = [
            (job, step) for job in workflow["jobs"].values() for step in job.get("steps", [])
            if "check_absorption.py" in str(step.get("run", ""))
        ]  # fmt: skip
        self.assertEqual(len(found), 1, "one step runs the gate")
        job, step = found[0]
        defaults = lambda node: ((node.get("defaults") or {}).get("run") or {}).get("shell")  # noqa: E731
        shell = step.get("shell") or defaults(job) or defaults(workflow)
        self.assertIn(shell, GITHUB_SHELLS, f"the gate step runs under {shell!r}, which this test does not model")
        with tempfile.TemporaryDirectory() as d:
            bin_dir = Path(d) / "bin"
            bin_dir.mkdir()
            python = bin_dir / "python"  # the step's `python`: every other command passes, the gate fails
            python.write_text(FAILING_GATE)
            python.chmod(0o755)
            script = Path(d) / "step.sh"
            script.write_text(step["run"])
            env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "GITHUB_STEP_SUMMARY": str(Path(d) / "summary.md")}
            ran = subprocess.run([*GITHUB_SHELLS[shell], str(script)], cwd=d, env=env, capture_output=True, text=True)
        self.assertIn("absorption gate: 1 problem(s)", ran.stderr)
        self.assertNotEqual(ran.returncode, 0, "the gate failed and its step passed")


class ThemeDependencyTest(unittest.TestCase):
    def test_code_and_config_naming_the_theme_count(self):
        read = heads({"sites/a/_config.yml": b"remote_theme: bamr87/zer0-mistakes\n", "src/core/x.ts": b"'jekyll-theme-zer0'", "sites/a/Gemfile": b'gem "jekyll-theme-zer0"', ".github/workflows/d.yml": b"ZER0_THEME_LOCAL: x", "web/site/render.ts": b"'zer0-mistakes'"})
        for path in ("sites/a/_config.yml", "src/core/x.ts", "sites/a/Gemfile", ".github/workflows/d.yml", "web/site/render.ts"):
            self.assertTrue(ca.is_theme_dependency(path, read), path)

    def test_content_never_counts(self):
        read = lambda p: b"remote_theme: bamr87/zer0-mistakes"  # noqa: E731
        for path in ("sites/a/pages/_docs/quick-start.md", "sites/a/_data/navigation/main.yml", "sites/a/_posts/2024-01-01-x.yml", "docs/MONOREPO.md", "src/test/fixtures/sites/x/_config.yml", "CHANGELOG.md", "features/features.yml", "tools/workspace/tests/golden/recordings.json", "content/tests/distribution/golden/ruby-lane.json", "web/site/fixtures/drsai/manifest.json"):
            self.assertFalse(ca.is_theme_dependency(path, read), path)

    def test_files_that_do_not_name_it_do_not_count(self):
        self.assertFalse(ca.is_theme_dependency("src/core/x.ts", heads({"src/core/x.ts": b"export const x = 1"})))

    def test_ratchet_message_names_the_option(self):
        errors, _ = ca.check_ratchet(["web/x.ts"], {"src/": 3}, "zer0-mistakes dependency", "the theme is only the option's")
        self.assertIn("new zer0-mistakes dependency outside the ratchet", errors[0])

    def test_write_ratchet_by_key(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.yml"
            p.write_text("ruby_ratchet:\n  a/: 1\ntheme_ratchet:\n  b/: 4\n  c/: 1\nsources: []\n")
            ca.write_ratchet(p, {"b/": 2}, "theme_ratchet")
            self.assertEqual(p.read_text(), "ruby_ratchet:\n  a/: 1\ntheme_ratchet:\n  b/: 2\nsources: []\n")

    def test_write_ratchet_keeps_the_blocks_comments(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "l.yml"
            p.write_text("theme_ratchet:\n  # why it exists\n  b/: 4\n  c/: 1\nsources: []\n")
            ca.write_ratchet(p, {"b/": 2}, "theme_ratchet")
            self.assertEqual(p.read_text(), "theme_ratchet:\n  # why it exists\n  b/: 2\nsources: []\n")


class FixtureTest(unittest.TestCase):
    def test_listed_fixture_must_exist(self):
        self.assertEqual(ca.check_fixtures(["a/Gemfile"], lambda p: True), [])
        self.assertIn("does not exist", ca.check_fixtures(["a/Gemfile"], lambda p: False)[0])


if __name__ == "__main__":
    unittest.main()
