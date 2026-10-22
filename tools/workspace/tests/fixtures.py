"""Throwaway workspaces for the bin/zer0 tests, built the same way for the
unit tests, the golden replay and the recorder that captured the Ruby tool
(deleted with it; `git show 095d5854:tools/workspace/tests/golden/record.py`).

Two kinds. The *small* workspace is the one the Ruby suite built (three
projects, two workflows, one vendored copy, its own git repository); its
variants are text edits of its manifest. The *frozen* tree is this repository
itself at the commit the golden recordings were made on (RECORDED_AT), cloned
with shared objects so it costs a checkout and no copy; it needs that commit in
the local history, so a shallow clone skips the tests that use it.

Every git call here runs with the user's and the system's git configuration
switched off (GIT_ENV), so a personal `diff.renames` or `core.quotePath` cannot
change what `git diff --name-only` prints between the recording and a replay.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[3]

# The commit the Ruby tool was recorded on, and the bases its `affected` ran against
# (40c904b9~3 changes only workspace files; 40c904b9~10 touches several projects and
# deletes a whole tree; the commit itself changes nothing).
RECORDED_AT = "40c904b90c54d5ef8f3053d9a7ce0775dac6dfa3"
BASES = {
    "head~3": "87fb9e5a1af20a1fbef05a19d47597c666901327",
    "head~10": "9a5e44f832e4cad6407cdd7e522f90231e2f6822",
    "head": RECORDED_AT,
}

# The tags the frozen tree's `fixture` remote carries: this repository's local tags on
# the day of the recording (its two releases and the 77 the Front Matter fork brought),
# plus one component-prefixed tag, so all three groups of `bin/zer0 tags` are exercised.
FROZEN_TAGS = (
    "3.1.0 4.0.0 4.0.1 v0.2.0 v0.3.0 v1.15.0 v1.15.1 v1.16.0 v1.16.1 v1.17.0 v1.17.1 v1.18.0 v10.0.0 "
    "v10.0.1 v10.0.2 v10.1.0 v10.2.0 v10.2.1 v10.3.0 v10.4.0 v10.4.1 v10.5.0 v10.5.1 v10.6.0 v10.7.0 "
    "v10.8.0 v10.9.0 v2.0.0 v2.0.1 v2.1.0 v2.2.0 v2.3.0 v2.4.0 v2.4.1 v2.5.0 v2.5.1 v3.0.0 v3.0.1 v3.0.2 "
    "v5.0.0 v5.1.0 v5.1.1 v5.10.0 v5.2.0 v5.3.0 v5.3.1 v5.4.0 v5.5.0 v5.6.0 v5.7.0 v5.8.0 v5.9.0 v6.0.0 "
    "v6.1.0 v6.1.1 v7.0.0 v7.1.0 v7.1.1 v7.1.2 v7.2.0 v7.3.0 v7.3.1 v7.3.2 v7.3.3 v7.3.4 v8.0.0 v8.0.1 "
    "v8.1.0 v8.1.1 v8.1.2 v8.2.0 v8.3.0 v8.4.0 v9.0.0 v9.1.0 v9.2.0 v9.3.0 v9.3.1 v9.4.0 content-v1.0.0"
).split()

GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
GIT_UNSET = ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_CONFIG")
IDENTITY = ("-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false")


def git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in GIT_UNSET}
    return {**env, **GIT_ENV}


def isolate_git(case: unittest.TestCase) -> None:
    """For the rest of the test, the tool's own git calls run under GIT_ENV too."""
    patcher = mock.patch.dict(os.environ, GIT_ENV)
    patcher.start()
    case.addCleanup(patcher.stop)
    for name in GIT_UNSET:
        os.environ.pop(name, None)


def git(cwd: Path | str, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=git_env())
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed in {cwd}: {done.stderr.strip()}")
    return done.stdout


def write(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# ── The small workspace (test_workspace.rb's fixture, byte for byte) ──────────

MANIFEST = """\
version: 1
projects:
  root-app:
    path: "."
    paths: ["src/**", "package.json"]
    kind: extension
    summary: The root project.
    ci: root.yml
    tasks:
      check: "true"
  theme:
    path: packages/theme
    kind: gem
    summary: A theme.
    ci: theme.yml
    tasks:
      check: "true"
      test:
        run: "exit 3"
        cwd: lib
  site:
    path: sites/site
    kind: site
    site: "."
    summary: A site built on the theme.
    depends_on: [theme]
    ci: none — nothing to test
    tasks:
      build: "true"
vendored:
  - copy: src/tokens.css
    source: packages/theme/tokens.css
"""

FILES = {
    "src/a.ts": "a",
    "package.json": "{}",
    "packages/theme/tokens.css": "--x: 1;",
    "packages/theme/lib/.keep": "",
    "src/tokens.css": "--x: 1;",
    "sites/site/index.md": "hi",
    ".github/workflows/root.yml": "on: [push]\n",
    ".github/workflows/theme.yml": 'on:\n  pull_request:\n    paths: ["packages/theme/**"]\n',
}

CHANGELOG = "# Changelog\n\n## [0.2.0](https://example.test) (2026-09-11)\n\n- é\n\n## [0.1.0] - 2026-07-31\n"


def small_workspace(root: Path, manifest: str = MANIFEST) -> Path:
    """The Ruby suite's workspace: its files, a git repository, everything staged."""
    write(root, "workspace.yml", manifest)
    for rel, body in FILES.items():
        write(root, rel, body)
    git(root, "init", "-q")
    git(root, "add", "-A")
    return root


def with_route(route: str | None, pages_task: bool = True, theme_route: str | None = None) -> str:
    """MANIFEST with the site publishing pages at `route` (None: no route line) and,
    unless told otherwise, the `pages` task that builds it; `theme_route` routes the
    theme too."""
    route_line = f"    route: {route}\n" if route else ""
    m = MANIFEST.replace(
        "    ci: none — nothing to test\n", f"    publishes: [pages]\n{route_line}    ci: none — nothing to test\n", 1
    )
    if pages_task:
        m = m.replace('      build: "true"\n', '      build: "true"\n      pages: "true"\n', 1)
    if theme_route:
        m = m.replace(
            "    ci: theme.yml\n", f"    publishes: [pages]\n    route: {theme_route}\n    ci: theme.yml\n", 1
        )
        m = m.replace('      check: "true"\n      test:', '      check: "true"\n      pages: "true"\n      test:', 1)
    return m


BLOG = """\
  blog:
    path: sites/blog
    kind: site
    summary: Built on the site.
    depends_on: [site]
    ci: none — demo
"""


def with_blog() -> str:
    """MANIFEST plus a site that depends on the site, so dependents are transitive."""
    return MANIFEST.replace("vendored:\n", BLOG + "vendored:\n", 1)


def tags_workspace(root: Path, remote: Path) -> Path:
    """The small workspace with a changelog, one commit, and a bare `origin` holding
    two releases, two inherited tags and one component tag."""
    small_workspace(root)
    write(root, "CHANGELOG.md", CHANGELOG)
    git(root, "add", "-A")
    git(root, *IDENTITY, "commit", "-q", "-m", "init")
    git(remote.parent, "init", "-q", "--bare", remote.name)
    git(root, "remote", "add", "origin", str(remote))
    for tag in ("v0.1.0", "v0.2.0", "v9.0.0", "3.1.0", "content-v1.0.0"):
        git(root, *IDENTITY, "tag", tag)
    git(root, "push", "-q", "origin", "--tags")
    return root


# ── Named scenarios: what the golden recordings ran on ───────────────────────

EDITS = {  # scenario: one (old, new) edit of MANIFEST, the way the Ruby suite broke it
    "ci-none": ("ci: none — nothing to test", "ci: none"),
    "gone-glob": ('"package.json"]', '"package.json", "gone.txt"]'),
    "shared-workflow": ("ci: none — nothing to test", "ci: theme.yml"),
    "bad-kind": ("kind: gem", "kind: library"),
    "bad-task": ('check: "true"\n      test:', 'lint: "true"\n      test:'),
    "bad-dep": ("depends_on: [theme]", "depends_on: [nope]"),
    "bad-key": ("    summary: A theme.\n", "    summary: A theme.\n    colour: blue\n"),
    "root-without-paths": ('    paths: ["src/**", "package.json"]\n', ""),
    "cycle": ("    summary: A theme.\n", "    summary: A theme.\n    depends_on: [site]\n"),
    "self-dependency": ("depends_on: [theme]", "depends_on: [site]"),
    "version-2": ("version: 1", "version: 2"),
    "bad-vendored": ("  - copy: src/tokens.css\n    source: packages/theme/tokens.css\n", "  - copy: src/tokens.css\n"),
    "bad-task-env": ("        cwd: lib\n", "        cwd: lib\n        env: [A]\n"),
    "missing-project-dir": ("path: sites/site", "path: sites/gone"),
}

ROUTES = {  # scenario: with_route(...) arguments
    "route-site": {"route": "/site/"},
    "route-missing": {"route": None},
    "route-none": {"route": "none", "pages_task": False},
    "route-none-reason": {"route": "none — published elsewhere", "pages_task": False},
    "route-malformed": {"route": "site"},
    "route-no-task": {"route": "/site/", "pages_task": False},
    "route-shared": {"route": "/site/", "theme_route": "/site/"},
    "route-overlap": {"route": "/site/inner/", "theme_route": "/site/"},
    "route-root": {"route": "/site/", "theme_route": "/"},
}

MANIFESTS = {"blog": with_blog(), "not-mapping": "- a\n- b\n", "bad-yaml": "version: 1\nprojects: [\n"}

AFTER = {  # scenario: files written (text) or deleted (None) once the workspace is staged
    "drift": {"packages/theme/tokens.css": "--x: 2;"},
    "stray-app": {"apps/stray/README.md": "x"},
    "missing-workflow": {
        ".github/workflows/root.yml": None,
        ".github/workflows/theme.yml": 'on:\n  pull_request:\n    paths: ["elsewhere/**"]\n',
    },
    "tags-no-changelog": {"CHANGELOG.md": None},
    "vendored-missing-copy": {"src/tokens.css": None},
    "vendored-missing-source": {"packages/theme/tokens.css": None},
}


def build(name: str, root: Path) -> Path:
    """Build the named scenario in `root` (created if missing, empty if present)."""
    root.mkdir(parents=True, exist_ok=True)
    if name == "frozen":
        return frozen_tree(root)
    if name == "no-manifest":
        return root
    if name.startswith("tags"):
        tags_workspace(root, root.parent / f"{root.name}-remote.git")
    else:
        manifest = MANIFESTS.get(name, MANIFEST)
        if name in EDITS:
            old, new = EDITS[name]
            assert old in MANIFEST, f"{name}: the edit no longer applies"
            manifest = MANIFEST.replace(old, new, 1)
        elif name in ROUTES:
            manifest = with_route(**ROUTES[name])
        small_workspace(root, manifest)
    for rel, body in AFTER.get(name, {}).items():
        if body is None:
            (root / rel).unlink()
        else:
            write(root, rel, body)
    return root


# ── The frozen tree: this repository at RECORDED_AT ──────────────────────────


def has_recorded_history() -> bool:
    """True when the local history holds the recorded commit and every base."""
    for sha in (RECORDED_AT, *BASES.values()):
        done = subprocess.run(
            ["git", "-C", str(REPO), "cat-file", "-e", f"{sha}^{{commit}}"], capture_output=True, env=git_env()
        )
        if done.returncode != 0:
            return False
    return True


def frozen_tree(dest: Path) -> Path:
    """A clean checkout of RECORDED_AT at `dest` (objects shared with this
    repository), with a `fixture` remote carrying FROZEN_TAGS."""
    git(dest.parent, "clone", "-q", "--shared", "--no-checkout", str(REPO), dest.name)
    git(dest, "checkout", "-q", "--detach", RECORDED_AT)
    tags = dest.parent / f"{dest.name}-tags"
    tags.mkdir()
    git(tags, "init", "-q")
    git(tags, *IDENTITY, "commit", "-q", "--allow-empty", "-m", "tags")
    for tag in FROZEN_TAGS:
        git(tags, "tag", tag)
    git(dest, "remote", "add", "fixture", str(tags))
    return dest
