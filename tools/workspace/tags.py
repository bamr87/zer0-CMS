"""`bin/zer0 tags`: which tags on a remote are this repository's own releases and
which it inherited from Front Matter CMS, the project zer0-CMS was forked from.

The fork brought estruyf/vscode-front-matter's release tags with it (v1.15.0
through v10.x, plus a few bare "3.1.0"-style ones). They are not this project's
releases: they make v0.3.0 look like a downgrade to every tool that sorts tags,
and they are a trap for anything that infers "latest" from tags. The rule that
tells them apart needs no history: a release of this repository is a version
with a heading in its CHANGELOG.md (`## [0.3.0]`), which release-please writes
for every tag it cuts. A bare semver tag with no heading is inherited. Anything
else — a component-prefixed tag such as `content-v1.0.0` — is neither and is
never touched.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass, field

from .manifest import WorkspaceError, inspect

SEMVER = re.compile(r"v?(\d+\.\d+\.\d+)", re.ASCII)
HEADING = re.compile(r"^## \[(\d+\.\d+\.\d+)\]", re.MULTILINE | re.ASCII)


@dataclass
class Classified:
    own: list = field(default_factory=list)
    inherited: list = field(default_factory=list)
    other: list = field(default_factory=list)


def _sort_key(tag: str) -> tuple:
    m = SEMVER.fullmatch(tag)
    return (0, *map(int, m[1].split(".")), tag) if m else (1, 0, 0, 0, tag)


class Tags:
    def __init__(self, root: str, changelog: str = "CHANGELOG.md") -> None:
        self.root = str(root)
        self.changelog = os.path.join(self.root, changelog)

    def releases(self) -> list:
        """The versions this repository has released, from its changelog headings."""
        if not os.path.isfile(self.changelog):
            raise WorkspaceError(f"{self.changelog} not found — the changelog is what says which tags are releases")
        with open(self.changelog, encoding="utf-8") as fh:
            return list(dict.fromkeys(HEADING.findall(fh.read())))

    def classify(self, tags: list) -> Classified:
        own = self.releases()
        groups = Classified()
        for tag in sorted(tags, key=_sort_key):
            m = SEMVER.fullmatch(tag)
            (groups.other if m is None else groups.own if m[1] in own else groups.inherited).append(tag)
        return groups

    def remote_tags(self, remote: str) -> list:
        """The tag names on `remote` (peeled refs are folded into their tag)."""
        out = self._git("ls-remote", "--tags", "--refs", remote)
        if out is None:
            raise WorkspaceError(f"git ls-remote --tags {remote} failed — is {inspect(remote)} a remote here?")
        return [line.split("\t", 1)[1].removeprefix("refs/tags/") for line in out.split("\n") if "\t" in line]

    def delete(self, remote: str, tags: list, batch: int = 25) -> list:
        """Deletes `tags` on `remote` (in batches, so one push carries many refs) and from
        the local clone. Returns the tags whose remote delete failed."""
        failed = []
        for i in range(0, len(tags), batch):
            chunk = tags[i : i + batch]
            push = ["git", "-C", self.root, "push", "--quiet", remote, *(f":refs/tags/{t}" for t in chunk)]
            if subprocess.run(push).returncode != 0:
                failed += chunk
        existing = set((self._git("tag", "--list") or "").split("\n"))
        local = [t for t in dict.fromkeys(tags) if t in existing]
        if local:
            subprocess.run(["git", "-C", self.root, "tag", "-d", *local], stdout=subprocess.DEVNULL)
        return failed

    def _git(self, *args: str) -> str | None:
        done = subprocess.run(["git", "-C", self.root, *args], capture_output=True, encoding="utf-8", errors="replace")
        return done.stdout if done.returncode == 0 else None
