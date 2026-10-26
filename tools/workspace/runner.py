"""Runs a manifest task (setup, check, test, build, pages) for one or more
projects, each in its own directory with its own environment, through
`bash -c`, so a task can be the same one-liner a contributor would type. A
project without that task is skipped and reported as such — never counted as a
pass.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import dataclass

from . import puts
from .manifest import Manifest


@dataclass(frozen=True)
class Result:
    project: str
    task: str
    status: str  # passed, failed or skipped
    seconds: float = 0

    @property
    def ok(self) -> bool:
        return self.status != "failed"


def spawn_bash(env: dict, command: str, folder: str) -> bool:
    try:
        return subprocess.run(["bash", "-c", command], cwd=folder, env={**os.environ, **env}).returncode == 0
    except OSError:  # no bash, or the task's directory is missing: the task did not pass
        return False


class Runner:
    def __init__(
        self, manifest: Manifest, out=None, dry_run: bool = False, keep_going: bool = False, spawn=None
    ) -> None:
        self.manifest = manifest
        self.out = out or sys.stdout
        self.dry_run = dry_run
        self.keep_going = keep_going
        self.spawn = spawn or spawn_bash

    def run(self, task: str, names: list) -> list:
        results = []
        for name in names:
            project = self.manifest.project(name)
            spec = project.task(task)
            if spec is None:
                results.append(Result(name, task, "skipped"))
                continue
            folder = os.path.abspath(os.path.join(self.manifest.root, project.path, spec.cwd))
            puts(self.out, f"==> {name}: {task}  ({self._relative(folder)})", f"    $ {spec.run}")
            if self.dry_run:
                results.append(Result(name, task, "skipped"))
                continue
            self.out.flush()  # the task writes straight to the terminal; keep its header above it
            started = time.monotonic()
            ok = self.spawn(spec.env, spec.run, folder)
            results.append(Result(name, task, "passed" if ok else "failed", round(time.monotonic() - started, 1)))
            if not ok and not self.keep_going:
                break
        return results

    def _relative(self, folder: str) -> str:
        rel = folder.removeprefix(os.path.abspath(self.manifest.root))
        return rel.removeprefix("/") if rel else "."
