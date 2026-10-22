"""`bin/zer0 doctor`: the CMS's own `zer0 doctor` run against every project the
manifest marks as a zer0 site, so the stack contract the CMS enforces on the
wider fleet is enforced on this repository's sites in one command. Each run's
last line is "result: N error(s), M warning(s)"; that is what gets collected.

The doctor itself is still `rails/bin/zer0-cms`, stdlib Ruby, until PLAN G4
ports it to the platform; this module runs it with whatever `ruby` is on PATH
and says so when there is none.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

from .manifest import Manifest, WorkspaceError

RESULT = re.compile(r"^result: (\d+) error\(s\), (\d+) warning\(s\)", re.MULTILINE | re.ASCII)
CLI = "rails/bin/zer0-cms"


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
        command = ["ruby", os.path.join(self.manifest.root, CLI), "doctor", os.path.join(self.manifest.root, root)]
        try:
            done = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        except FileNotFoundError:
            raise WorkspaceError(
                f"doctor runs the CMS's zer0 doctor ({CLI}), which needs Ruby until PLAN G4 ports it to the "
                "platform — install Ruby 3.3+ or run it in a ruby:3.3 container"
            ) from None
        return done.stdout.decode("utf-8", "replace")
