"""`bin/zer0 doctor`: the platform's zer0 doctor run against every project the
manifest marks as a zer0 site, so the contract the platform checks on the wider
fleet is checked on this repository's sites in one command. Each run's last
line is "result: N error(s), M warning(s)"; that is what gets collected.

The doctor is `content/sites/doctor.py` (PLAN G4), run as `python -m
sites.doctor <site>` from `content/` on this Python: it needs no Django, only
PyYAML and jsonschema, and the Python the platform needs (3.12+). It replaced
the Ruby `rails/bin/zer0-cms doctor`; the theme's rules did not come with it
(ADR 0006 decision 4).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from .manifest import Manifest, WorkspaceError

RESULT = re.compile(r"^result: (\d+) error\(s\), (\d+) warning\(s\)", re.MULTILINE | re.ASCII)
# The platform this tool ships with: the doctor is its, not the checked workspace's.
PLATFORM = Path(__file__).resolve().parents[2] / "content"


@dataclass(frozen=True)
class Report:
    project: str
    root: str
    errors: int
    warnings: int
    output: str

    @property
    def ok(self) -> bool:
        return self.errors == 0


class Doctor:
    def __init__(self, manifest: Manifest, capture=None) -> None:
        self.manifest = manifest
        self.capture = capture or self.run_doctor

    def sites(self) -> list:
        """The projects that declare a `site:` root."""
        return [p for p in self.manifest.projects if p.site_root]

    def run(self, names: list | None = None) -> list:
        chosen = [self.manifest.project(n) for n in names] if names else self.sites()
        reports = []
        for project in chosen:
            root = project.site_root
            if root is None:
                raise WorkspaceError(f"{project.name} declares no site: root to check")
            output = self.capture(root)
            m = RESULT.search(output)
            errors, warnings = (int(m[1]), int(m[2])) if m else (1, 0)  # no result line: the doctor itself failed
            reports.append(Report(project.name, root, errors, warnings, output))
        return reports

    def run_doctor(self, root: str) -> str:
        """The doctor's whole report (stdout and stderr) on one site root."""
        command = [sys.executable, "-m", "sites.doctor", os.path.join(self.manifest.root, root)]
        done = subprocess.run(command, cwd=PLATFORM, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        output = done.stdout.decode("utf-8", "replace")
        missing = re.search(r"ModuleNotFoundError: No module named '([\w.]+)'", output)
        if missing and not RESULT.search(output):
            raise WorkspaceError(
                "doctor runs the platform's zer0 doctor (content/sites/doctor.py), which needs "
                f"{missing[1]} on {sys.executable} — e.g. .venv/bin/pip install pyyaml jsonschema"
            )
        return output
