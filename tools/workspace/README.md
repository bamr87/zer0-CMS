# tools/workspace — `bin/zer0`

The tooling behind `bin/zer0`, the one command that manages every project in this repository from the root `workspace.yml`. Python 3.9+ with PyYAML and nothing else (`python3 -m pip install pyyaml`; without it `bin/zer0` says so), so it runs in a bare checkout and in any CI job before a project's own dependencies are installed. Why it exists and how it fits the rest of the repository: [`docs/MONOREPO.md`](../../docs/MONOREPO.md).

It was stdlib Ruby until PLAN P5 ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 12). The port keeps every command, flag, message and exit code, and its tests prove it against recordings of the Ruby tool (§ Tests). Two things it does that the Ruby tool did not: `affected` reads git's paths NUL-separated, so a file whose name git would quote (a non-ASCII name, a quote) still counts for its project instead of landing among the unowned files; and every path the manifest names (`path`, `paths`, `site`, a task's `cwd`, a vendored `copy` and `source`) must be relative with no `..`, and a vendored path that leads out through a symlink is refused, so `vendor --write` can never write outside the checkout.

## Commands

| Command | What it does |
|---|---|
| `bin/zer0 list [--json]` | Every project: path, kind, what it publishes, the workflow that gates it. |
| `bin/zer0 info <project>` | One project in full: summary, tasks with their directory and environment, dependencies and dependents, site root. |
| `bin/zer0 run <task> [project...]` | Runs `setup`, `check`, `test`, `build` or `pages` for the named projects (default: every project that has the task), each in its own directory through `bash -c`. `--affected [--base REF]` narrows to what changed, `--dry-run` prints the commands, `--keep-going` does not stop at the first failure. A project without the task is reported as skipped, never as passed. |
| `bin/zer0 affected [--base REF]` | The projects changed since the merge base with `REF` (default `origin/main`), uncommitted and untracked files included, plus every project that depends on them. `--files a,b` takes paths instead of asking git; `--json` adds the direct set and the files no project owns. |
| `bin/zer0 matrix <task> [--affected]` | The projects that have `<task>`, as a JSON list for a CI matrix. |
| `bin/zer0 routes [--json]` | Where the one Pages deploy serves each site (`route:` in `workspace.yml`), root first; `--json` is `pages.yml`'s build plan. Sites that publish pages without a route are listed with their reason. |
| `bin/zer0 check` | The workspace contract, below. Exit 1 on any finding. |
| `bin/zer0 vendor [--write]` | Every vendored copy and whether it still matches its source; `--write` re-copies the drifted ones. |
| `bin/zer0 doctor [project...]` | The CMS's own `zer0 doctor` (`rails/bin/zer0-cms`) on every project with a `site:` root. Report-only unless `--strict`; `--verbose` prints each full report. That doctor is still Ruby until PLAN G4 ports it to the platform: with no `ruby` on `PATH`, this command says so and exits 2. |
| `bin/zer0 tags [--remote NAME]` | The tags on a remote (default `origin`), split into this repository's releases (a version with a `## [x.y.z]` heading in `CHANGELOG.md`), tags inherited from the Front Matter CMS fork (a bare semver with no heading) and anything else (component-prefixed tags, never touched). `--delete` removes the inherited ones from the remote and the local clone; `--json` prints the three lists. |

Options go anywhere on the line, as `--name VALUE` or `--name=VALUE`, and any unique prefix of a name works (`--dry` for `--dry-run`). Exit codes: 0 success, 1 a failing check, test or strict doctor, 2 a usage or manifest error.

## The contract `bin/zer0 check` enforces

| Rule | Fails when |
|---|---|
| `paths_exist` | A project's directory is missing, or a glob it claims in `paths:` matches no tracked file. |
| `containers_registered` | A directory directly under `packages/`, `sites/` or `apps/` is not a project in `workspace.yml`. |
| `workflows` | A project's `ci:` names a root workflow that does not exist, the workflow filters on paths but none is under the project, or `ci: none` gives no reason. |
| `routes` | A project publishes `pages` with no `route:`, a `route: none` gives no reason, a route is not `/` or `/name/…/`, a routed project has no `pages` task, or two routes are the same or nest (only `/` may contain the others). |
| `vendored` | A vendored copy or its source is missing, or the two differ by a single byte. |

## Ownership

A file belongs to the project whose glob matches it with the longest literal prefix, so `packages/zer0-image-generator/x` is the image generator's even though nothing claims `packages/`, and `schemas/openapi/x` is the platform's although the extension claims `schemas/**`. A `dir/**` glob owns everything under `dir/`; any other glob matches the way Ruby's `File.fnmatch` did with `FNM_PATHNAME`, which the manifest's globs were written for: `*` stays inside one path segment, `**/` spans directories and `{a,b}` is either. A project at `.` (the extension) must list the globs it owns. A root workflow belongs to every project whose `ci:` names it. Anything else, such as `docs/`, `workspace.yml` or `tools/`, is workspace infrastructure and affects no project on its own.

## Layout

| File | What it is |
|---|---|
| `__init__.py` | The package, and `puts`, Ruby's `puts`, which the tool's output was written with. |
| `manifest.py` | Loads and validates `workspace.yml` into `Project`, `Task` and `Vendored` values; dependency names and cycles are checked here, and every path it names is held inside the repository. Its `to_s` and `inspect` render values the way the Ruby tool's messages quoted them. |
| `ownership.py` | File → project, and the affected set with dependents. |
| `checks.py` | The five `check` rules. |
| `runner.py` | Runs a task per project; the spawn is injectable for tests. |
| `vendor.py` | Vendored-copy status and re-copy; `check` reads the same statuses. |
| `doctor.py` | `zer0 doctor` over every declared site. |
| `tags.py` | Release tags vs. tags inherited from the fork, and their deletion. |
| `cli.py` | The command line, on `argparse`; with the runner, the only code that prints. |
| `tests/` | The tests, below. |

## Tests

```bash
python3 -m unittest discover tools/workspace
```

| File | What it proves |
|---|---|
| `tests/test_workspace.py` | Every class against throwaway workspaces with their own git repository: the Ruby suite's tests, ported one for one, and the ones it lacked (longest-prefix ownership, the glob semantics, the real `bash` spawn, the doctor without Ruby, a remote that refuses a tag delete, paths held inside the repository, and `affected` from git itself — committed, uncommitted and untracked changes, each file once, names git would quote). |
| `tests/test_real_manifest.py` | The repository's own `workspace.yml` passes every rule, `docs/MONOREPO.md` mentions every project, and the `bin/zer0` script itself runs. |
| `tests/test_golden.py` | The Python tool prints what the Ruby one printed: every recorded step, replayed and compared byte for byte (stdout, stderr and exit status). |
| `tests/fixtures.py` | Builds every scenario the tests and the recordings use. |

**The golden recordings.** `tests/golden/recordings.json` holds the Ruby tool's stdout, stderr and exit status for 202 steps over 36 scenarios, recorded in a `ruby:3.3` container (Ruby 3.3.12, git 2.47.3) before the Ruby was deleted, by a recorder that lived beside it (`git show 095d5854:tools/workspace/tests/golden/record.py`). The scenarios are this repository frozen at commit `40c904b9` (cloned from the local history with shared objects, so a shallow clone skips those steps; CI fetches the full history), run against three fixed bases for `affected`, and the small workspaces the Ruby suite built, with every way it broke them. A doctor step replays each site's recorded `zer0-cms` report instead of running Ruby. Git runs with the user's and the system's configuration switched off, so a personal setting cannot change what it prints. Where the Python tool differs on purpose, `DEVIATIONS` in `test_golden.py` says how and why, and only the exit status is compared: the wording of a malformed option (argparse's, not OptionParser's), a command's own `--help`, OptionParser's completion of a one-dash prefix (`-j` for `--json`), and PyYAML's description of a YAML syntax error. A deliberate change to the tool's output edits the matching steps in `recordings.json` in the same commit and says why; never regenerate the file from the Python tool, which would erase the proof.
