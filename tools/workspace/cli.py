"""The bin/zer0 command line: one entry point for every project in the workspace.

Commands print for people by default and emit JSON with --json where CI
consumes them. Only this module and the task runner print; the rest of the
package returns values. Output and exit codes are the Ruby tool's, byte for
byte (tests/golden/): 0 success, 1 a failing check, test or strict doctor, 2 a
usage or manifest error.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import subprocess
import sys
from functools import cached_property

from . import puts
from .checks import Checks
from .doctor import Doctor
from .manifest import TASKS, Manifest, Project, WorkspaceError, inspect
from .ownership import Ownership
from .runner import Runner
from .tags import Tags
from .vendor import Vendor

USAGE = """\
usage: bin/zer0 <command> [options]

  list                         every project: path, kind, what it publishes, what gates it
  info <project>               one project in full
  run <task> [project...]      run setup|check|test|build|pages for the named projects
      --all                    every project that has the task (the default with no names)
      --affected [--base REF]  only projects changed since REF (default origin/main), plus dependents
      --dry-run                print the commands without running them
      --keep-going             do not stop at the first failure
  affected [--base REF]        projects changed since REF, plus the projects that depend on them
      --files f1,f2            use these paths instead of asking git
      --json                   {"affected": [...], "direct": [...], "unowned": [...]}
  matrix <task> [--affected]   JSON list of projects that have <task>, for a CI matrix
  routes [--json]              where the one Pages deploy serves each site (route, path, pages task)
  check                        the workspace contract: registration, paths, workflows, routes, vendored copies
  vendor [--write]             vendored copies and whether each still matches its source
  doctor [project...]          the CMS's zer0 doctor on every zer0 site in the workspace
      --strict                 exit 1 when any site has an error (default: report only)
      --verbose                print each site's full doctor report
  tags [--remote NAME]         tags on the remote: this repository's releases vs. those inherited from the fork
      --delete                 delete the inherited ones on the remote and locally
      --json                   {"own": [...], "inherited": [...], "other": [...]}
"""

COMMANDS = ("list", "info", "run", "affected", "matrix", "routes", "check", "vendor", "doctor", "tags")


def main(argv: list, root, out=None, err=None) -> int:
    """Run one bin/zer0 command against the workspace at `root`; returns the exit status."""
    return CLI(argv, root, out, err).run()


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):
        raise WorkspaceError(message)  # printed as the tool's own usage error, exit 2


def _compact(value) -> str:
    """JSON.generate's layout: no spaces, non-ASCII as is."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _pretty(value) -> str:
    """JSON.pretty_generate's layout, which writes an empty list as `[`, a blank line and `]`."""
    text = json.dumps(value, indent=2, ensure_ascii=False)
    return re.sub(r"^( *)(.*)\[\](,?)$", r"\1\2[\n\n\1]\3", text, flags=re.MULTILINE)


def _join(items: list, sep: str = ", ") -> str:
    return sep.join(items) if items else "-"


class CLI:
    def __init__(self, argv: list, root, out=None, err=None) -> None:
        self.argv = list(argv)
        self.root = str(root)
        self.out = out or sys.stdout
        self.err = err or sys.stderr
        self.command = None

    def run(self) -> int:
        self.command = self.argv.pop(0) if self.argv else None
        if self.command in (None, "-h", "--help", "help"):
            puts(self.out, USAGE)
            return 0
        if self.command not in COMMANDS:
            puts(self.err, f"bin/zer0: unknown command {inspect(self.command)}\n\n{USAGE}")
            return 2
        try:
            return getattr(self, f"_{self.command}")()
        except WorkspaceError as error:
            puts(self.err, f"bin/zer0: {error}")
            return 2

    @cached_property
    def manifest(self) -> Manifest:
        return Manifest.load(self.root)

    # ── The commands ─────────────────────────────────────────────────────────

    def _list(self) -> int:
        if self._options("--json").json:
            puts(self.out, _pretty([self._summary(p) for p in self.manifest.projects]))
            return 0
        rows = [[p.name, p.path, p.kind, _join(p.publishes, " "), p.workflow or "none"] for p in self.manifest.projects]
        self._table([["PROJECT", "PATH", "KIND", "PUBLISHES", "CI"], *rows])
        return 0

    def _info(self) -> int:
        p = self.manifest.project(self._shift("info needs a project name"))
        owns = f"  (owns {', '.join(p.paths)})" if p.paths else ""
        lines = [
            f"{p.name} — {p.summary}",
            f"  path:       {p.path}{owns}",
            f"  kind:       {p.kind}   stack: {', '.join(p.stack)}",
        ]
        if p.upstream:
            lines.append(f"  upstream:   {p.upstream}")
        lines += [
            f"  depends on: {_join(p.depends_on)}",
            f"  used by:    {_join(self.manifest.dependents_of(p.name))}",
            f"  publishes:  {_join(p.publishes)}",
            f"  ci:         {p.ci}",
        ]
        if p.site_root:
            lines.append(f"  site:       {p.site_root} (checked by bin/zer0 doctor)")
        if p.render:
            lines.append(f"  render:     {p.render['as']} {p.render['theme']}, built by the {p.render['server']} server")
        for spec in filter(None, map(p.task, TASKS)):
            where = "" if spec.cwd == "." else f" (in {spec.cwd})"
            env = f" [{' '.join(f'{k}={v}' for k, v in spec.env.items())}]" if spec.env else ""
            lines.append(f"  {spec.name.ljust(6)}      {spec.run}{where}{env}")
        puts(self.out, *lines)
        return 0

    def _run(self) -> int:
        task = self._shift(f"run needs a task ({'|'.join(TASKS)})")
        if task not in TASKS:
            raise WorkspaceError(f"invalid argument: unknown task {task} ({'|'.join(TASKS)})")
        opts = self._options("--all", "--affected", "--dry-run", "--keep-going", values=("--base",))
        for name in opts.names:
            self.manifest.project(name)
        names = opts.names or self._with_task(task, opts)
        if not names:
            puts(self.out, f"Nothing to run: no {'affected ' if opts.affected else ''}project has a {task} task.")
            return 0
        results = Runner(self.manifest, self.out, dry_run=opts.dry_run, keep_going=opts.keep_going).run(task, names)
        puts(self.out)
        for r in results:
            timing = f" ({r.seconds}s)" if r.status in ("passed", "failed") else ""
            puts(self.out, f"  {r.status.ljust(8)} {r.project}{timing}")
        return 0 if all(r.ok for r in results) else 1

    def _affected(self) -> int:
        opts = self._options("--json", values=("--base", "--files"))
        ownership = Ownership(self.manifest)
        files = [f for f in opts.files.split(",") if f] if opts.files is not None else self._changed_files(opts.base)
        result = ownership.affected(files)
        if opts.json:
            puts(self.out, _compact(result))
        elif result["affected"]:
            puts(self.out, "\n".join(result["affected"]))
        else:
            puts(self.out, "No project is affected.")
            if result["unowned"]:
                puts(self.err, f"(workspace files only: {len(result['unowned'])})")
        return 0

    def _matrix(self) -> int:
        task = self._shift("matrix needs a task")
        puts(self.out, _compact(self._with_task(task, self._options("--affected", values=("--base",)))))
        return 0

    def _routes(self) -> int:
        """The one Pages deploy's plan: every routed project, root first. pages.yml builds a matrix
        from --json and stitches each build into the artifact at its route; `bundle_dir` is the
        site's root (its `site:`, or the project directory when it declares none), and `render` is
        how a site that renders with the Jekyll-theme option is built (its `render:` setting)."""
        opts = self._options("--json")
        routed = [p for p in self.manifest.projects if p.route_path]
        routed.sort(key=lambda p: (p.route_path != "/", p.route_path))
        if opts.json:
            plan = [
                dict(
                    name=p.name,
                    path=p.path,
                    route=p.route_path,
                    bundle_dir=p.site_root or p.path,
                    **({"render": p.render} if p.render else {}),
                )
                for p in routed
            ]
            puts(self.out, _compact(plan))
            return 0
        self._table([["ROUTE", "PROJECT", "PATH"], *([p.route_path, p.name, p.path] for p in routed)])
        for p in self.manifest.projects:
            if "pages" in p.publishes and p.route_path is None:
                puts(self.out, f"  (no route) {p.name}: {p.route or '—'}")
        return 0

    def _check(self) -> int:
        findings = Checks(self.manifest).run()
        if not findings:
            counted = f"{len(self.manifest.projects)} projects, {len(self.manifest.vendored)} vendored copies"
            puts(self.out, f"workspace OK — {counted}, every rule green.")
            return 0
        puts(self.out, *(f"  ✗ {f}" for f in findings))
        puts(self.out, f"\n{len(findings)} finding(s).")
        return 1

    def _vendor(self) -> int:
        vendor = Vendor(self.manifest)
        if self._options("--write").write:
            written = [f"re-vendored {v.copy}" for v in vendor.write()]
            puts(self.out, *(written or ["Every vendored copy already matches its source."]))
            return 0
        statuses = vendor.statuses()
        for s in statuses:
            puts(self.out, f"  {s.state.ljust(14)} {s.vendored.copy}\n  {'':14} ← {s.vendored.source}")
        return 0 if all(s.state == "same" for s in statuses) else 1

    def _doctor(self) -> int:
        opts = self._options("--strict", "--verbose")
        reports = Doctor(self.manifest).run(opts.names)
        for r in reports:
            if opts.verbose:
                puts(self.out, r.output)
            counted = f"{r.errors} error(s), {r.warnings} warning(s)"
            puts(self.out, f"  {('ok' if r.ok else 'errors').ljust(7)} {r.project.ljust(22)} {counted}  ({r.root})")
        return 1 if opts.strict and not all(r.ok for r in reports) else 0

    def _tags(self) -> int:
        opts = self._options("--delete", "--json", values=("--remote",))
        remote = "origin" if opts.remote is None else opts.remote
        tags = Tags(self.root)
        groups = tags.classify(tags.remote_tags(remote))
        if opts.json:
            puts(self.out, _compact(vars(groups)))
        else:
            counted = f"{len(groups.own)} release tag(s) of this repository, {len(groups.inherited)} inherited"
            puts(self.out, f"{remote}: {counted}, {len(groups.other)} other")
            for name, group in vars(groups).items():
                if group:
                    puts(self.out, f"  {name + ':':<10} {' '.join(group)}")
        if not opts.delete:
            return 0
        if not groups.inherited:
            puts(self.out, "Nothing to delete.")
            return 0
        failed = tags.delete(remote, groups.inherited)
        puts(self.out, f"deleted {len(groups.inherited) - len(failed)} inherited tag(s) from {remote} and this clone")
        if not failed:
            return 0
        puts(self.err, f"could not delete on {remote}: {' '.join(failed)}")
        return 1

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _shift(self, needs: str) -> str:
        if not self.argv:
            raise WorkspaceError(f"missing argument: {needs}")
        return self.argv.pop(0)

    def _options(self, *flags: str, values: tuple = ()) -> argparse.Namespace:
        """Long options anywhere on the line, as `--name`, `--name VALUE` or `--name=VALUE` and
        any unique prefix of a name; whatever is not an option is left in `.names`."""
        parser = _Parser(prog=f"bin/zer0 {self.command}")
        for flag in flags:
            parser.add_argument(flag, action="store_true")
        for value in values:
            parser.add_argument(value)
        parser.add_argument("names", nargs="*")
        return parser.parse_intermixed_args(self.argv)

    def _with_task(self, task: str, opts: argparse.Namespace) -> list:
        names = [p.name for p in self.manifest.projects if p.task(task)]
        if not opts.affected:
            return names
        affected = Ownership(self.manifest).affected(self._changed_files(opts.base))["affected"]
        return [n for n in names if n in affected]

    def _changed_files(self, base: str | None) -> list:
        """Files changed between the merge base with `base` and the working tree, so local,
        uncommitted edits count too, plus untracked files; each once. NUL-separated (-z), so
        git never quotes a path (a non-ASCII name, a quote) into one no project owns."""
        base = "origin/main" if base is None else base
        merge_base = self._git("merge-base", base, "HEAD").strip()
        if not merge_base:
            raise WorkspaceError(f"cannot find a merge base with {base} (fetch it first)")
        diff = self._git("diff", "--name-only", "-z", merge_base)
        untracked = self._git("ls-files", "-z", "--others", "--exclude-standard")
        return list(dict.fromkeys(f for f in (diff + untracked).split("\0") if f))

    def _git(self, *args: str) -> str:
        done = subprocess.run(["git", "-C", self.root, *args], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        return done.stdout.decode("utf-8", "surrogateescape")

    def _table(self, rows: list) -> None:
        widths = [max(map(len, column)) for column in zip(*rows)]
        puts(self.out, *("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip() for row in rows))

    @staticmethod
    def _summary(p: Project) -> dict:
        """A project for `list --json`: its fields but `paths` (and `render` unless set), with the computed
        site, route and task names."""
        listed = {
            f.name: getattr(p, f.name)
            for f in dataclasses.fields(p)
            if f.name != "paths" and not (f.name == "render" and p.render is None)
        }
        return {**listed, "site": p.site_root, "route": p.route_path, "tasks": list(p.tasks)}
