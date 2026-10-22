"""Record the Ruby bin/zer0's behaviour as golden fixtures (PLAN P5, step 1).

Builds every scenario in tests/fixtures.py under a scratch directory, runs the
Ruby tool on each in a ruby:3.3 container (the scenarios and this repository are
mounted at the same absolute paths, because git metadata uses absolute paths),
and writes recordings.json beside this file: for every step its argv, exit code,
stdout and stderr, plus the raw `zer0-cms doctor` report of every site the
doctor steps ran on, so the Python tool's doctor can be replayed without Ruby.
Absolute scenario paths are replaced by `<root>`.

It runs only where the Ruby tool still exists (commit RECORDED_AT and the
commit that added this file); the Python port deleted both.

    python3 tools/workspace/tests/golden/record.py SCRATCH_DIR
"""

from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from workspace.tests import fixtures  # noqa: E402

TASKS = ("setup", "check", "test", "build", "pages")
OUT = Path(__file__).resolve().parent / "recordings.json"
# Drives the Ruby CLI on a root other than the one bin/zer0 resolves for itself,
# the way test_workspace.rb did (Zer0Workspace::CLI.new(argv, root:)).
DRIVER = 'require ENV.fetch("ZER0_LIB"); exit Zer0Workspace::CLI.new(ARGV, root: ENV.fetch("ZER0_ROOT")).run'


def frozen_steps(projects: list[str]) -> list[list[str]]:
    steps: list[list[str]] = [[], ["help"], ["-h"], ["--help"], ["help", "extra"], ["bogus"], ["-x"]]
    steps += [["list"], ["list", "--json"], *[["info", p] for p in projects], ["info"], ["info", "nope"]]
    steps += [["info", "--json"], ["routes"], ["routes", "--json"], ["routes", "extra", "--json"]]
    steps += [["check"], ["check", "--bogus"], ["vendor"]]
    steps += [*[["matrix", t] for t in TASKS], ["matrix", "lint"], ["matrix"], ["matrix", "--affected", "check"]]
    for sha in fixtures.BASES.values():
        steps += [["affected", "--base", sha], ["affected", "--base", sha, "--json"]]
        steps += [["matrix", t, "--affected", "--base", sha] for t in TASKS]
        steps += [["run", "check", "--affected", "--base", sha, "--dry-run"]]
        steps += [["run", "test", "--base", sha, "--affected", "--dry-run"]]
    steps += [["affected", "--base", "nope"]]
    steps += [["affected", "--files", "packages/zer0-image-generator/lib/x.rb,docs/README.md", "--json"]]
    steps += [["affected", "--files", "docs/README.md"], ["affected", "--files=.github/workflows/sites.yml", "--json"]]
    steps += [["affected", "--files", "content/x.py,src/a.ts,sites/drsai/y.md,schemas/openapi/o.json"]]
    steps += [["run", t, "--all", "--dry-run"] for t in TASKS]
    steps += [["run", "test", "drsai", "books", "--dry-run"], ["run", "pages", "books", "parodynews", "--dry-run"]]
    steps += [["run", "test", "--dry-run", "drsai", "--", "--keep-going"], ["run", "--dry-run", "test", "--al", "aieo"]]
    steps += [["run"], ["run", "lint"], ["run", "test", "nope"]]
    steps += [["tags", "--remote", "fixture"], ["tags", "--remote", "fixture", "--json"], ["tags", "--remote", "nope"]]
    steps += [["doctor"], ["doctor", "--verbose"], ["doctor", "--strict"], ["doctor", "drsai", "zer0-pages"]]
    steps += [["doctor", "books"], ["doctor", "nope"]]
    # Option-parsing corners whose wording is OptionParser's own.
    steps += [["list", "--bogus"], ["list", "--json=1"], ["affected", "--base"], ["run", "test", "--a"]]
    steps += [["tags", "--remote"], ["vendor", "--write=1"], ["list", "--help"], ["list", "-j"], ["list", "--js"]]
    steps += [["run", "test", "--dry", "books"]]
    return steps


SMALL_STEPS = [
    ["list"], ["list", "--json"], ["info", "root-app"], ["info", "theme"], ["info", "site"], ["info", "nope"],
    ["check"], ["vendor"], ["routes"], ["routes", "--json"], ["bogus"], ["run", "lint"],
    ["matrix", "check"], ["matrix", "test"], ["matrix", "build"], ["matrix", "pages"],
    ["affected", "--files", "packages/theme/a,README.md", "--json"], ["affected", "--files", "packages/theme/a,README.md"],
    ["affected", "--files", "docs/x.md"], ["affected", "--files", ".github/workflows/theme.yml", "--json"],
    ["affected", "--files", "packages/themes/x,src/deep/file.ts,package.json,.github/workflows/x.yml", "--json"],
    ["affected"],
    ["run", "test", "theme"], ["run", "test", "--keep-going"], ["run", "check", "--dry-run"],
    ["run", "check", "root-app", "theme"], ["run", "build", "--dry-run", "root-app", "site"],
    ["doctor"], ["doctor", "--strict"], ["doctor", "--verbose"], ["doctor", "theme"],
]

# scenario → steps; each scenario is built fresh and its steps run in order.
CASES: dict[str, list[list[str]]] = {
    "small": SMALL_STEPS,
    "drift": [["check"], ["vendor"], ["vendor", "--write"], ["vendor"], ["vendor", "--write"], ["check"]],
    "stray-app": [["check"]],
    "missing-workflow": [["check"]],
    "ci-none": [["check"]],
    "gone-glob": [["check"]],
    "route-site": [["check"], ["routes"], ["routes", "--json"]],
    "route-missing": [["check"], ["routes"]],
    "route-none": [["check"]],
    "route-none-reason": [["check"], ["routes"]],
    "route-malformed": [["check"]],
    "route-no-task": [["check"]],
    "route-shared": [["check"], ["routes"]],
    "route-overlap": [["check"], ["routes", "--json"]],
    "route-root": [["check"], ["routes"], ["routes", "--json"], ["run", "pages", "--dry-run"]],
    "blog": [["affected", "--files", "packages/theme/x", "--json"], ["info", "theme"], ["list"]],
    "shared-workflow": [["affected", "--files", ".github/workflows/theme.yml", "--json"], ["list"], ["check"]],
    "bad-kind": [["list"]],
    "bad-task": [["list"]],
    "bad-dep": [["list"]],
    "bad-key": [["list"]],
    "root-without-paths": [["list"]],
    "cycle": [["check"]],
    "self-dependency": [["list"]],
    "version-2": [["list"]],
    "not-mapping": [["list"]],
    "bad-yaml": [["list"]],
    "no-manifest": [["list"]],
    "bad-vendored": [["list"]],
    "bad-task-env": [["list"]],
    "tags": [["tags", "--json"], ["tags"], ["tags", "--delete"], ["tags", "--json"], ["tags", "--delete"]],
    "tags-no-changelog": [["tags"]],
}


def site_roots(root: Path) -> list[str]:
    data = yaml.safe_load((root / "workspace.yml").read_text())
    roots = []
    for spec in data["projects"].values():
        if spec.get("site") is not None:
            roots.append(spec["path"] if spec["site"] == "." else f"{spec['path']}/{spec['site']}")
    return roots


def main(scratch: Path) -> None:
    trees = scratch / "trees"
    out = scratch / "out"
    shutil.rmtree(scratch, ignore_errors=True)
    trees.mkdir(parents=True)
    out.mkdir()
    lib = trees / "frozen" / "tools/workspace/lib/zer0_workspace"
    plan: list[tuple[str, Path, list[list[str]]]] = []
    frozen = fixtures.build("frozen", trees / "frozen")
    projects = list(yaml.safe_load((frozen / "workspace.yml").read_text())["projects"])
    plan.append(("frozen", frozen, frozen_steps(projects)))
    for name, steps in CASES.items():
        plan.append((name, fixtures.build(name, trees / name), steps))

    script = ["set -u", "git config --global --add safe.directory '*'"]
    for name, root, steps in plan:
        for i, argv in enumerate(steps):
            stem = shlex.quote(str(out / f"{name}.{i}"))
            args = " ".join(shlex.quote(a) for a in argv)
            if name == "frozen":
                run = f"ruby bin/zer0 {args}"
            else:
                run = f"ZER0_ROOT={shlex.quote(str(root))} ZER0_LIB={shlex.quote(str(lib))} ruby -e {shlex.quote(DRIVER)} -- {args}"
            script.append(f"(cd {shlex.quote(str(root))} && {run} >{stem}.out 2>{stem}.err; echo $? >{stem}.code)")
        if any(argv[:1] == ["doctor"] for argv in steps):
            for site in site_roots(root):
                raw = shlex.quote(str(out / f"{name}.doctor.{site.replace('/', '__')}"))
                cli = shlex.quote(str(root / "rails/bin/zer0-cms"))
                script.append(f"(cd {shlex.quote(str(root))} && ruby {cli} doctor {shlex.quote(str(root / site))} >{raw} 2>&1)")
    script.append(f"ruby -v >{shlex.quote(str(out / 'ruby-version'))}; git --version >{shlex.quote(str(out / 'git-version'))}")
    (scratch / "run.sh").write_text("\n".join(script) + "\n")

    # The frozen clone borrows this repository's objects, so its object store goes in too.
    common = Path(fixtures.git(fixtures.REPO, "rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    mounts = [arg for path in {fixtures.REPO, common, scratch} for arg in ("-v", f"{path}:{path}")]
    subprocess.run(["docker", "run", "--rm", *mounts, "ruby:3.3", "sh", str(scratch / "run.sh")], check=True)

    def clean(text: str, root: Path) -> str:
        return text.replace(str(root), "<root>")

    cases, doctor = [], {}
    for name, root, steps in plan:
        recorded = []
        for i, argv in enumerate(steps):
            stem = out / f"{name}.{i}"
            recorded.append({
                "argv": argv,
                "exit": int((stem.with_suffix(stem.suffix + ".code")).read_text()),
                "stdout": clean(Path(f"{stem}.out").read_text(encoding="utf-8"), root),
                "stderr": clean(Path(f"{stem}.err").read_text(encoding="utf-8"), root),
            })
        cases.append({"scenario": name, "steps": recorded})
        raws = sorted(out.glob(f"{name}.doctor.*"))
        if raws:
            doctor[name] = {
                p.name.split(".doctor.", 1)[1].replace("__", "/"): clean(p.read_text(encoding="utf-8"), root) for p in raws
            }
        status = fixtures.git(root, "status", "--porcelain") if name == "frozen" else ""
        if status:
            raise SystemExit(f"the Ruby tool changed the frozen tree:\n{status}")

    OUT.write_text(json.dumps({
        "recorded_at": fixtures.RECORDED_AT,
        "tool": f"bin/zer0 (Ruby) at {fixtures.RECORDED_AT}",
        "ruby": (out / "ruby-version").read_text().strip(),
        "git": (out / "git-version").read_text().strip(),
        "cases": cases,
        "doctor": doctor,
    }, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT} — {sum(len(c['steps']) for c in cases)} steps in {len(cases)} scenarios")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
