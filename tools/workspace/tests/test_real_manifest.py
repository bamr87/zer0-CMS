"""The repository's own workspace.yml (ported from test_real_manifest.rb): it
loads, every rule of `bin/zer0 check` passes against the real tree, and
docs/MONOREPO.md mentions every project. This is the test that fails when a
project is imported without being registered, a vendored copy drifts, or a
workflow stops filtering on the path it gates. It also runs the bin/zer0
script itself, which the other tests reach only through its library, with and
without PyYAML (and with the repository .venv it falls back on).

Run: python3 -m unittest discover tools/workspace
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workspace.checks import RULES, Checks  # noqa: E402
from workspace.manifest import Manifest  # noqa: E402
from workspace.tests import fixtures  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]
ZER0 = str(ROOT / "bin" / "zer0")


class RealManifestTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = Manifest.load(ROOT)

    def test_loads(self):
        self.assertTrue(self.manifest.projects)

    def test_every_rule_passes(self):
        for rule in RULES:
            with self.subTest(rule=rule):
                self.assertEqual(
                    [str(f) for f in Checks(self.manifest).run(only=(rule,))], [], f"bin/zer0 check — {rule}"
                )

    def test_every_project_is_in_the_monorepo_guide(self):
        """Every project the manifest lists is one docs/MONOREPO.md accounts for, so a new project cannot ship unmentioned."""
        guide = (ROOT / "docs" / "MONOREPO.md").read_text(encoding="utf-8")
        for p in self.manifest.projects:
            if p.path not in (".", "rails"):
                self.assertIn(f"`{p.path}/`", guide, f"docs/MONOREPO.md does not mention {p.path}/")


class EntryPointTest(unittest.TestCase):
    def zer0(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, ZER0, *args], capture_output=True, text=True, encoding="utf-8")

    def test_check_passes_on_this_tree(self):
        done = self.zer0("check")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertRegex(done.stdout, r"^workspace OK — \d+ projects, \d+ vendored copies, every rule green\.\n$")

    def test_usage_and_an_unknown_command(self):
        self.assertTrue(self.zer0().stdout.startswith("usage: bin/zer0 <command> [options]\n"))
        done = self.zer0("bogus")
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertTrue(done.stderr.startswith('bin/zer0: unknown command "bogus"\n\nusage:'))


class WithoutPyYAMLTest(unittest.TestCase):
    """bin/zer0 under `python -S`, which cannot import PyYAML, in a copy of the repository's
    root (bin/zer0, the package, a manifest) so that a real .venv here changes nothing."""

    def setUp(self):
        if subprocess.run([sys.executable, "-S", "-c", "import yaml"], capture_output=True).returncode == 0:
            self.skipTest("PyYAML is importable without site-packages here")
        self.root = Path(tempfile.mkdtemp(prefix="zer0-bin")).resolve()
        self.addCleanup(shutil.rmtree, self.root)
        (self.root / "bin").mkdir()
        shutil.copy2(ZER0, self.root / "bin" / "zer0")
        (self.root / "tools").mkdir()
        (self.root / "tools" / "workspace").symlink_to(ROOT / "tools" / "workspace")
        check = 'check: echo "mark=${ZER0_VENV-unset}"'  # root-app's task: did the .venv mark reach it?
        (self.root / "workspace.yml").write_text(fixtures.MANIFEST.replace('check: "true"', check, 1))

    def zer0(self, *args: str) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k != "ZER0_VENV"}
        command = [sys.executable, "-S", str(self.root / "bin" / "zer0"), *args]
        return subprocess.run(command, capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)

    def venv(self, *flags: str) -> None:
        """The root's .venv/bin/python: this Python, with `flags`."""
        python = self.root / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text(f'#!/bin/sh\nexec "{sys.executable}" {" ".join(flags)} "$@"\n')
        python.chmod(0o755)

    def assertHint(self, done: subprocess.CompletedProcess) -> None:
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertRegex(done.stderr, r"^bin/zer0: needs PyYAML, which \S+ cannot import\. Any one of:\n")
        self.assertIn("\n  python3 -m venv .venv && .venv/bin/pip install pyyaml ", done.stderr)

    def test_with_no_venv_it_says_how_to_get_it(self):
        self.assertHint(self.zer0("list"))

    def test_it_runs_on_the_repository_venv_and_its_tasks_start_afresh(self):
        self.venv()
        done = self.zer0("run", "check", "root-app")
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("\nmark=unset\n", done.stdout)

    def test_a_venv_without_pyyaml_is_tried_once(self):
        self.venv("-S")
        self.assertHint(self.zer0("list"))


if __name__ == "__main__":
    unittest.main()
