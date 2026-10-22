"""The workspace manifest (workspace.yml) loaded into plain values and validated.

Everything else in the package reads projects through here, so a malformed
manifest fails in one place with a message naming the key, rather than as an
error somewhere inside a command. The messages are the Ruby tool's, word for
word (tests/golden/), which is why `to_s` and `inspect` render values the way
Ruby did.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

import yaml

KINDS = tuple("extension rails gem python site app".split())
TASKS = tuple("setup check test build pages".split())
PROJECT_KEYS = tuple("path paths kind stack summary upstream depends_on publishes ci site route tasks".split())
TASK_KEYS = tuple("run cwd env".split())


class WorkspaceError(Exception):
    """A manifest or usage problem: bin/zer0 prints it and exits 2."""


def present(value) -> bool:
    """Ruby truthiness, which `a || b` in the old tool relied on: only nil and false are false."""
    return value is not None and value is not False


def to_s(value) -> str:
    """Ruby's #to_s for a YAML scalar."""
    return "" if value is None else "true" if value is True else "false" if value is False else str(value)


_ESCAPED = re.compile(r'#(?=[{$@])|[\x00-\x1f\x7f-\x9f"\\]')  # what Ruby's String#inspect escapes
_ESCAPES = {char: "\\" + letter for char, letter in zip('"\\#\n\t\r\x1b\b\a\f\v', '"\\#ntrebafv')}


def inspect(value) -> str:
    """Ruby's #inspect, so a message quotes a value exactly as the Ruby tool did."""
    if isinstance(value, str):
        return '"' + _ESCAPED.sub(lambda m: _ESCAPES.get(m[0]) or f"\\u{ord(m[0]):04X}", value) + '"'
    if isinstance(value, list):
        return "[" + ", ".join(map(inspect, value)) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{inspect(k)}=>{inspect(v)}" for k, v in value.items()) + "}"
    return "nil" if value is None else to_s(value)


def as_list(value) -> list:
    """Ruby's Kernel#Array: nil is empty, a list is itself, a mapping is its pairs, anything else one item."""
    if value is None:
        return []
    return value if isinstance(value, list) else list(value.items()) if isinstance(value, dict) else [value]


@dataclass(frozen=True)
class Task:
    """One command a project runs: `run` from `cwd` (relative to the project's path) with `env` added."""

    name: str
    run: str
    cwd: str = "."
    env: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Project:
    name: str
    path: str
    paths: list
    kind: str
    stack: list
    summary: str
    upstream: str
    depends_on: list
    publishes: list
    ci: str
    site: str | None
    route: str | None
    tasks: dict

    @property
    def globs(self) -> list:
        """The globs this project owns: a project at "." must list them; any other owns its directory."""
        return self.paths or [f"{self.path}/**"]

    @property
    def workflow(self) -> str | None:
        """The root workflow file that gates this project, or None when `ci` says `none — <reason>`."""
        return None if self.ci.startswith("none") else self.ci

    def task(self, name: str) -> Task | None:
        return self.tasks.get(name)

    @property
    def route_path(self) -> str | None:
        """The sub-path the one Pages deploy serves it at ("/", "/drsai/"), or None — no `route:`,
        or `route: none — <reason>` (ADR 0002 §4)."""
        return None if self.route is None or self.route.startswith("none") else self.route

    @property
    def site_root(self) -> str | None:
        """The Jekyll root `zer0 doctor` checks, relative to the repository root, or None."""
        if self.site is None:
            return None
        return self.path if self.site == "." else f"{self.path.rstrip('/')}/{self.site.lstrip('/')}"


@dataclass(frozen=True)
class Vendored:
    copy: str
    source: str
    why: str = ""


class Manifest:
    def __init__(self, root: str | Path, data) -> None:
        self.root = str(root)
        if not isinstance(data, dict):
            raise WorkspaceError("the manifest must be a mapping")
        version = data.get("version")
        if isinstance(version, bool) or version != 1:
            raise WorkspaceError(f"version must be 1 (got {inspect(version)})")
        projects = data.get("projects")
        if not isinstance(projects, dict) or not projects:
            raise WorkspaceError("projects must be a non-empty mapping")
        self.projects = [_project(to_s(name), spec) for name, spec in projects.items()]
        self.vendored = [_vendored(spec, i) for i, spec in enumerate(as_list(data.get("vendored")))]
        self._validate_dependencies()

    @classmethod
    def load(cls, root: str | Path, file: str = "workspace.yml") -> Manifest:
        full = Path(root, file)
        if not full.is_file():
            raise WorkspaceError(f"{file} not found under {root}")
        try:
            data = yaml.safe_load(full.read_text(encoding="utf-8"))
        except yaml.YAMLError as error:
            raise WorkspaceError(f"{file} is not valid YAML: {' '.join(str(error).split())}") from None
        return cls(root, data)

    @cached_property
    def names(self) -> list:
        return [p.name for p in self.projects]

    def project(self, name: str) -> Project:
        for p in self.projects:
            if p.name == name:
                return p
        raise WorkspaceError(f"no project named {inspect(name)}")

    def dependents_of(self, name: str) -> list:
        """The projects that depend on `name`, directly or through others."""
        found, queue = [], [name]
        while queue:
            current = queue.pop(0)
            for p in self.projects:
                if current in p.depends_on and p.name not in found:
                    found.append(p.name)
                    queue.append(p.name)
        return found

    def _validate_dependencies(self) -> None:
        for p in self.projects:
            for dep in p.depends_on:
                if dep not in self.names:
                    raise WorkspaceError(f"projects.{p.name}.depends_on names {inspect(dep)}, which is not a project")
                if dep == p.name:
                    raise WorkspaceError(f"projects.{p.name} depends on itself")
        for p in self.projects:
            if p.name in self.dependents_of(p.name):
                raise WorkspaceError(f"dependency cycle through {p.name}")


def _project(name: str, spec) -> Project:
    if not isinstance(spec, dict):
        raise WorkspaceError(f"projects.{name} must be a mapping")
    unknown = [k for k in spec if k not in PROJECT_KEYS]
    if unknown:
        raise WorkspaceError(f"projects.{name}: unknown key(s) {', '.join(map(to_s, unknown))}")
    path = _string(spec, "path", name)
    kind = _string(spec, "kind", name)
    if kind not in KINDS:
        raise WorkspaceError(f"projects.{name}.kind must be one of {', '.join(KINDS)} (got {kind})")
    paths = _strings(spec, "paths", name)
    if path == "." and not paths:
        raise WorkspaceError(f'projects.{name}: a project at "." must list the paths it owns')
    return Project(
        name=name,
        path=path,
        paths=paths,
        kind=kind,
        stack=_strings(spec, "stack", name),
        summary=_string(spec, "summary", name),
        upstream=to_s(spec.get("upstream")),
        depends_on=_strings(spec, "depends_on", name),
        publishes=_strings(spec, "publishes", name),
        ci=_string(spec, "ci", name),
        site=_string(spec, "site", name, required=False),
        route=_string(spec, "route", name, required=False),
        tasks=_tasks(name, spec["tasks"] if present(spec.get("tasks")) else {}),
    )


def _tasks(name: str, tasks) -> dict:
    if not isinstance(tasks, dict):
        raise WorkspaceError(f"projects.{name}.tasks must be a mapping")
    built = {}
    for task, value in tasks.items():
        if task not in TASKS:
            raise WorkspaceError(f"projects.{name}.tasks: unknown task {to_s(task)} (known: {', '.join(TASKS)})")
        built[task] = _task(name, task, value)
    return built


def _task(name: str, task: str, value) -> Task:
    if isinstance(value, str):
        return Task(task, value)
    if not isinstance(value, dict):
        raise WorkspaceError(f"projects.{name}.tasks.{task} must be a command string or a {{run:, cwd:, env:}} mapping")
    unknown = [k for k in value if k not in TASK_KEYS]
    if unknown:
        raise WorkspaceError(f"projects.{name}.tasks.{task}: unknown key(s) {', '.join(map(to_s, unknown))}")
    run = value.get("run")
    if not isinstance(run, str) or not run:
        raise WorkspaceError(f"projects.{name}.tasks.{task}.run must be a string")
    env = value["env"] if present(value.get("env")) else {}
    if not isinstance(env, dict):
        raise WorkspaceError(f"projects.{name}.tasks.{task}.env must be a mapping")
    cwd = to_s(value["cwd"] if present(value.get("cwd")) else ".")
    return Task(task, run, cwd, {to_s(k): to_s(v) for k, v in env.items()})


def _vendored(spec, index: int) -> Vendored:
    if not isinstance(spec, dict):
        raise WorkspaceError(f"vendored[{index}] must be a mapping")
    copy, source = to_s(spec.get("copy")), to_s(spec.get("source"))
    if not copy or not source:
        raise WorkspaceError(f"vendored[{index}] needs both copy and source")
    return Vendored(copy, source, to_s(spec.get("why")))


def _string(spec: dict, key: str, name: str, required: bool = True) -> str | None:
    value = spec.get(key)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value.strip(" \t\n\v\f\r\0"):  # Ruby's strip: no Unicode spaces
        raise WorkspaceError(f"projects.{name}.{key} {'is required' if required else 'must be a non-empty string'}")
    return value


def _strings(spec: dict, key: str, name: str) -> list:
    value = spec.get(key)
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise WorkspaceError(f"projects.{name}.{key} must be a list of strings")
    return list(value)
