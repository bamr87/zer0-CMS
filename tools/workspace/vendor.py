"""`bin/zer0 vendor`: the status of every vendored copy, and with `write()` a
fresh byte copy of each drifted or missing one from its source. Re-vendoring is
a change somebody reads in a diff, which is why this never runs on its own.
`bin/zer0 check` reads the same statuses.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from .manifest import Manifest, Vendored, WorkspaceError


@dataclass(frozen=True)
class Status:
    vendored: Vendored
    state: str  # same, drifted, missing_copy or missing_source


class Vendor:
    def __init__(self, manifest: Manifest) -> None:
        self.manifest = manifest

    def statuses(self) -> list:
        found = []
        for v in self.manifest.vendored:
            source, copy = self._path(v.source), self._path(v.copy)
            if not source.is_file():
                state = "missing_source"
            elif not copy.is_file():
                state = "missing_copy"
            else:
                state = "same" if source.read_bytes() == copy.read_bytes() else "drifted"
            found.append(Status(v, state))
        return found

    def write(self) -> list:
        """Copies every drifted or missing copy from its source; returns what it wrote."""
        written = []
        for s in self.statuses():
            if s.state in ("drifted", "missing_copy"):
                self._path(s.vendored.copy).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self._path(s.vendored.source), self._path(s.vendored.copy))
                written.append(s.vendored)
        return written

    def _path(self, rel: str) -> Path:
        """`rel` under the root, which the manifest already holds to a relative path with no
        `..`; resolved, so a symlink that leads out of the repository is refused too, and
        `write` can never copy over a file outside the checkout."""
        root = Path(self.manifest.root).resolve()
        path = (root / rel).resolve()
        if not path.is_relative_to(root):
            raise WorkspaceError(f"vendored {rel} leads outside the repository (through a symlink, to {path})")
        return path
