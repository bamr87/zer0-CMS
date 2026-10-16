# tools/workspace — `bin/zer0`

The tooling behind `bin/zer0`, the one command that manages every project in this repository from the root `workspace.yml`. Stdlib-only Ruby (3.3+), like `rails/lib`, so it runs in a bare checkout and in any CI job before a single dependency is installed. Why it exists and how it fits the rest of the repository: [`docs/MONOREPO.md`](../../docs/MONOREPO.md).

## Commands

| Command | What it does |
|---|---|
| `bin/zer0 list [--json]` | Every project: path, kind, what it publishes, the workflow that gates it. |
| `bin/zer0 info <project>` | One project in full: summary, tasks with their directory and environment, dependencies and dependents, site root. |
| `bin/zer0 run <task> [project...]` | Runs `setup`, `check`, `test` or `build` for the named projects (default: every project that has the task), each in its own directory through `bash -c`. `--affected [--base REF]` narrows to what changed, `--dry-run` prints the commands, `--keep-going` does not stop at the first failure. A project without the task is reported as skipped, never as passed. |
| `bin/zer0 affected [--base REF]` | The projects changed since the merge base with `REF` (default `origin/main`), uncommitted and untracked files included, plus every project that depends on them. `--files a,b` takes paths instead of asking git; `--json` adds the direct set and the files no project owns. |
| `bin/zer0 matrix <task> [--affected]` | The projects that have `<task>`, as a JSON list for a CI matrix. |
| `bin/zer0 check` | The workspace contract, below. Exit 1 on any finding. |
| `bin/zer0 vendor [--write]` | Every vendored copy and whether it still matches its source; `--write` re-copies the drifted ones. |
| `bin/zer0 doctor [project...]` | The CMS's own `zer0 doctor` (`rails/bin/zer0-cms`) on every project with a `site:` root. Report-only unless `--strict`; `--verbose` prints each full report. |

Exit codes: 0 success, 1 a failing check, test or strict doctor, 2 a usage or manifest error.

## The contract `bin/zer0 check` enforces

| Rule | Fails when |
|---|---|
| `paths_exist` | A project's directory is missing, or a glob it claims in `paths:` matches no tracked file. |
| `containers_registered` | A directory directly under `packages/`, `sites/` or `apps/` is not a project in `workspace.yml`. |
| `workflows` | A project's `ci:` names a root workflow that does not exist, the workflow filters on paths but none is under the project, or `ci: none` gives no reason. |
| `vendored` | A vendored copy or its source is missing, or the two differ by a single byte. |

## Ownership

A file belongs to the project whose glob matches it with the longest literal prefix, so `packages/zer0-mistakes/x` is the theme's even though nothing claims `packages/`. A project at `.` (the extension) must list the globs it owns. A root workflow belongs to every project whose `ci:` names it. Anything else, such as `docs/`, `workspace.yml` or `tools/`, is workspace infrastructure and affects no project on its own.

## Layout

| File | What it is |
|---|---|
| `lib/zer0_workspace/manifest.rb` | Loads and validates `workspace.yml` into `Project`, `Task` and `Vendored` values; dependency names and cycles are checked here. |
| `lib/zer0_workspace/ownership.rb` | File → project, and the affected set with dependents. |
| `lib/zer0_workspace/checks.rb` | The four `check` rules. |
| `lib/zer0_workspace/runner.rb` | Runs a task per project; the spawn is injectable for tests. |
| `lib/zer0_workspace/vendor.rb` | Vendored-copy status and re-copy. |
| `lib/zer0_workspace/doctor.rb` | `zer0 doctor` over every declared site. |
| `lib/zer0_workspace/cli.rb` | The command line; the only file that prints or exits. |
| `test/test_workspace.rb` | Every class against throwaway workspaces with their own git repository. |
| `test/test_real_manifest.rb` | The repository's own `workspace.yml` passes every rule, and `docs/MONOREPO.md` mentions every project. |

```bash
for f in tools/workspace/test/test_*.rb; do ruby "$f"; done
```
