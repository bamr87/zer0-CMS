"""The repository's own workspace.yml (ported from test_real_manifest.rb): it
loads, every rule of `bin/zer0 check` passes against the real tree, and
docs/MONOREPO.md mentions every project. This is the test that fails when a
project is imported without being registered, a vendored copy drifts, or a
workflow stops filtering on the path it gates. It also runs the bin/zer0
script itself, which the other tests reach only through its library.

Run: python3 -m unittest discover tools/workspace
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workspace.checks import RULES, Checks  # noqa: E402
from workspace.manifest import Manifest  # noqa: E402

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
    def zer0(self, *args: str, python: tuple = (sys.executable,)) -> subprocess.CompletedProcess:
        return subprocess.run([*python, ZER0, *args], capture_output=True, text=True, encoding="utf-8")

    def test_check_passes_on_this_tree(self):
        done = self.zer0("check")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertRegex(done.stdout, r"^workspace OK — \d+ projects, \d+ vendored copies, every rule green\.\n$")

    def test_usage_and_an_unknown_command(self):
        self.assertTrue(self.zer0().stdout.startswith("usage: bin/zer0 <command> [options]\n"))
        done = self.zer0("bogus")
        self.assertEqual((done.returncode, done.stdout), (2, ""))
        self.assertTrue(done.stderr.startswith('bin/zer0: unknown command "bogus"\n\nusage:'))

    def test_without_pyyaml_it_says_how_to_get_it(self):
        if subprocess.run([sys.executable, "-S", "-c", "import yaml"], capture_output=True).returncode == 0:
            self.skipTest("PyYAML is importable without site-packages here")
        done = self.zer0("list", python=(sys.executable, "-S"))
        self.assertEqual(
            (done.returncode, done.stderr), (2, "bin/zer0: needs PyYAML — python3 -m pip install pyyaml\n")
        )


if __name__ == "__main__":
    unittest.main()
