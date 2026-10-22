"""`bin/zer0 check`: the workspace's structural contract. Each rule yields what
is wrong; no finding from any rule is a green workspace.

The rules exist because the cost of a monorepo is drift nobody notices: a
directory imported but never registered, a vendored copy that stopped being a
copy, a workflow that no longer filters on the path it gates. Each finding says
what is wrong and what fixes it.
"""

from __future__ import annotations

import itertools
import os
import re
import subprocess
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

from .manifest import Manifest, inspect, present, to_s
from .ownership import match
from .vendor import Vendor

CONTAINERS = ("packages", "sites", "apps")
RULES = ("paths_exist", "containers_registered", "workflows", "routes", "vendored")
ROUTE = re.compile(r"/(?:[a-z0-9][a-z0-9._-]*/)*")
NONE = re.compile(r"none[ \t\n\v\f\r]*[—-]?[ \t\n\v\f\r]*")  # what precedes the reason in `none — <reason>`
VENDORED = {
    "missing_source": "{source} (source of {copy}) does not exist",
    "missing_copy": "{copy} (copy of {source}) does not exist — bin/zer0 vendor --write",
    "drifted": "{copy} has drifted from {source} — bin/zer0 vendor --write, then read the diff",
}


@dataclass(frozen=True)
class Finding:
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.rule}: {self.message}"


class Checks:
    def __init__(self, manifest: Manifest, files: list | None = None) -> None:
        self.manifest = manifest
        self.root = manifest.root
        if files is not None:
            self.files = files

    def run(self, only=RULES) -> list:
        return [Finding(rule, message) for rule in only for message in getattr(self, rule)()]

    def paths_exist(self):
        """Every project's directory exists, and every glob it claims matches at least one
        tracked file (a glob that matches nothing is a typo or a file deleted without
        updating the manifest)."""
        for p in self.manifest.projects:
            if not os.path.isdir(os.path.join(self.root, p.path)):
                yield f"{p.name}: {p.path}/ does not exist"
                continue
            for glob in p.paths:
                if not any(match(glob, f) for f in self.files):
                    yield f"{p.name}: {inspect(glob)} matches no tracked file"

    def containers_registered(self):
        """Every directory directly under packages/, sites/ and apps/ is a project."""
        registered = {p.path for p in self.manifest.projects}
        for container in CONTAINERS:
            folder = os.path.join(self.root, container)
            for child in sorted(os.listdir(folder)) if os.path.isdir(folder) else ():
                path = f"{container}/{child}"
                if os.path.isdir(os.path.join(self.root, path)) and path not in registered:
                    yield f"{path}/ is not registered in workspace.yml — add it under projects:"

    def workflows(self):
        """A project's `ci:` names a root workflow that exists and, when that workflow filters
        on paths, includes the project's own path. `none` must carry a reason."""
        for p in self.manifest.projects:
            file = os.path.join(self.root, ".github/workflows", p.workflow or "")
            if p.workflow is None:
                if not _reason(p.ci):
                    yield f"{p.name}: ci is `none` without a reason — say why nothing gates it"
            elif not os.path.isfile(file):
                yield f"{p.name}: ci names .github/workflows/{p.workflow}, which does not exist"
            elif (filters := _path_filters(file)) is not None and p.path != ".":
                if not any(f == f"{p.path}/**" or f.startswith(f"{p.path}/") for f in filters):
                    yield f"{p.name}: {p.workflow} filters on paths but none is under {p.path}/"

    def routes(self):
        """Every project that publishes `pages` has a place in the one Pages deploy (ADR 0002 §4):
        a `route:` that is a sub-path like "/drsai/" — or `none — <reason>` — and a routed project
        has the `pages` task that builds it. No two routes are the same, and none but "/" contains
        another, so one site can never overwrite part of another."""
        for p in self.manifest.projects:
            if "pages" not in p.publishes:
                continue
            if p.route is None:
                yield f"{p.name}: publishes pages but has no route — add `route: /<path>/` or `route: none — <reason>`"
            elif p.route_path is None:
                if not _reason(p.route):
                    yield f"{p.name}: route is `none` without a reason — say where it is published instead"
            elif not ROUTE.fullmatch(p.route):
                yield f"{p.name}: route {inspect(p.route)} must look like /name/ (lowercase segments, leading and trailing slash)"
            elif p.task("pages") is None:
                yield f"{p.name}: has route {p.route} but no `pages` task to build it"
        routed = [p for p in self.manifest.projects if p.route_path]
        for a, b in itertools.combinations(routed, 2):
            if a.route_path == b.route_path:
                yield f"{a.name} and {b.name} share route {a.route_path}"
            elif "/" not in (a.route_path, b.route_path) and (
                a.route_path.startswith(b.route_path) or b.route_path.startswith(a.route_path)
            ):
                yield f"{a.name} ({a.route_path}) and {b.name} ({b.route_path}) overlap — one would overwrite part of the other"

    def vendored(self):
        """Every vendored copy is byte-identical to its source."""
        for s in Vendor(self.manifest).statuses():
            if s.state in VENDORED:
                yield VENDORED[s.state].format(copy=s.vendored.copy, source=s.vendored.source)

    @cached_property
    def files(self) -> list:
        """Every tracked file, from git."""
        out = subprocess.run(["git", "-C", self.root, "ls-files", "-z"], stdout=subprocess.PIPE).stdout
        return [f for f in out.decode("utf-8", "surrogateescape").split("\0") if f]


def _reason(value: str) -> str:
    """The reason in `none — <reason>`."""
    return value[NONE.match(value).end() :]


def _path_filters(file: str) -> list | None:
    """The union of `paths:` under the pull_request/push triggers, or None when the
    workflow does not filter on paths at all."""
    data = yaml.safe_load(Path(file).read_text(encoding="utf-8"))
    data = data if present(data) else {}
    on = data["on"] if present(data.get("on")) else data.get(True)  # YAML 1.1 reads a bare `on:` as true
    if not isinstance(on, dict):
        return None
    lists = [
        on[e]["paths"] for e in ("pull_request", "push") if isinstance(on.get(e), dict) and present(on[e].get("paths"))
    ]
    return [to_s(f) for paths in lists for f in (paths if isinstance(paths, list) else [paths])] if lists else None
