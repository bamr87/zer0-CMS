"""Golden equivalence: the Python bin/zer0 prints what the Ruby one printed.

golden/recordings.json holds the Ruby tool's stdout, stderr and exit status for
every step it was recorded on (golden/README.md says how), over scenarios that
fixtures.py builds the same way here: the small workspaces of the old Ruby
suite, and the frozen tree — this repository at the recorded commit. Each step
is replayed through the Python CLI and all three are compared byte for byte,
with the scenario's path written as <root> and run timings as (…s). Doctor
steps replay each site's recorded zer0-cms report instead of running Ruby.

Where the two tools differ on purpose, DEVIATIONS says how and why; for those
only the exit status is compared, against the Python value given there.

Run: python3 -m unittest discover tools/workspace
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from workspace import cli  # noqa: E402
from workspace.doctor import Doctor  # noqa: E402
from workspace.manifest import TASKS  # noqa: E402
from workspace.tests import fixtures  # noqa: E402

RECORDINGS = json.loads((Path(__file__).parent / "golden" / "recordings.json").read_text(encoding="utf-8"))

_ARGPARSE = "the wording of a malformed option is argparse's, not OptionParser's (the established library, not a clone of Ruby's)"
DEVIATIONS = {  # (scenario, argv) → (the Python tool's exit status, why its output differs)
    ("frozen", ("list", "--bogus")): (2, _ARGPARSE),
    ("frozen", ("list", "--json=1")): (2, _ARGPARSE),
    ("frozen", ("affected", "--base")): (2, _ARGPARSE),
    ("frozen", ("run", "test", "--a")): (2, _ARGPARSE),
    ("frozen", ("tags", "--remote")): (2, _ARGPARSE),
    ("frozen", ("vendor", "--write=1")): (2, _ARGPARSE),
    ("frozen", ("list", "--help")): (0, "a command's --help is argparse's summary of its options"),
    ("frozen", ("list", "-j")): (
        2,
        "OptionParser completed a one-dash prefix of a long option (-j → --json); argparse accepts only what is declared",
    ),
    ("bad-yaml", ("list",)): (2, "the YAML parser's own description of the syntax error is PyYAML's, not libyaml's"),
}


def clean(text: str, root: Path) -> str:
    return re.sub(r"\(\d+\.\d+s\)", "(…s)", text.replace(str(root), "<root>"))


class GoldenCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        fixtures.isolate_git(self)

    def replay(self, scenario: str, root: Path, steps: list) -> None:
        reports = RECORDINGS["doctor"].get(scenario, {})
        with mock.patch.object(Doctor, "run_doctor", lambda _self, site: reports[site]):
            for i, step in enumerate(steps):
                argv = step["argv"]
                with self.subTest(scenario=scenario, step=i, argv=" ".join(argv)):
                    out, err = io.StringIO(), io.StringIO()
                    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                        try:
                            code = cli.main(argv, root, out, err)
                        except SystemExit as exit:  # argparse's own --help
                            code = exit.code
                    deviation = DEVIATIONS.get((scenario, tuple(argv)))
                    if deviation:
                        self.assertEqual(code, deviation[0], deviation[1])
                        continue
                    expected = (step["exit"], clean(step["stdout"], root), clean(step["stderr"], root))
                    self.assertEqual((code, clean(out.getvalue(), root), clean(err.getvalue(), root)), expected)


@unittest.skipUnless(
    fixtures.has_recorded_history(), f"needs commit {fixtures.RECORDED_AT[:8]} and its bases (a full clone)"
)
class FrozenTreeTest(GoldenCase):
    """list, info, routes, check, vendor, matrix, affected against three fixed bases, run --dry-run, tags,
    doctor, usage and errors — on this repository as it was when the Ruby tool was recorded."""

    def test_every_recorded_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = fixtures.build("frozen", Path(tmp) / "frozen")
            (case,) = [c for c in RECORDINGS["cases"] if c["scenario"] == "frozen"]
            self.replay("frozen", root, case["steps"])


class ScenarioTest(GoldenCase):
    """The old Ruby suite's small workspace and every way it broke it: check findings, manifest errors,
    routes, the vendor --write repair, tags --delete, the runner and the doctor."""

    def test_every_recorded_step(self):
        for case in RECORDINGS["cases"]:
            if case["scenario"] == "frozen":
                continue
            with tempfile.TemporaryDirectory() as tmp:
                root = fixtures.build(case["scenario"], Path(tmp) / case["scenario"])
                self.replay(case["scenario"], root, case["steps"])


class CoverageTest(unittest.TestCase):
    def test_every_command_and_task_was_recorded(self):
        steps = [s["argv"] for c in RECORDINGS["cases"] for s in c["steps"]]
        for command in cli.COMMANDS:
            self.assertTrue(any(argv[:1] == [command] for argv in steps), command)
        for task in TASKS:
            self.assertIn(["run", task, "--all", "--dry-run"], steps)

    def test_every_deviation_is_a_recorded_step(self):
        recorded = {(c["scenario"], tuple(s["argv"])) for c in RECORDINGS["cases"] for s in c["steps"]}
        self.assertLessEqual(set(DEVIATIONS), recorded)


if __name__ == "__main__":
    unittest.main()
