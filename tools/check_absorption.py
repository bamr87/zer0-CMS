#!/usr/bin/env python3
"""Gate the absorption into one Python platform (ADR 0006).

Two of ADR 0006's decisions are promises about the future — "no Ruby remains"
and "every merged repository is absorbed with its content, features and
capabilities". A promise about the future is the easiest thing for a later
change to break without anyone noticing: a new `.rb` file looks like progress
on the feature it serves, and a deleted directory looks like cleanup. This
turns both into a check over `docs/plan/capabilities.yml` and the tracked tree.

The ledger has two halves. `platform:` is the target — every capability the one
platform must have, and its status on each surface that must offer it (`api`,
`studio`, `extension`, `mcp`, `site`, `ops`). `sources:` is what was merged in —
every capability of every absorbed repository, and the platform capability it
lands in.

It asserts:

  * **the Ruby ratchet** — every tracked Ruby file (by extension, by name such
    as `Gemfile`, or by a `ruby` shebang) lies under a prefix listed in
    `ruby_ratchet:`, and no prefix holds more Ruby files than its ceiling.
    `--tighten` lowers every ceiling to today's count and drops the prefixes
    that reached zero; it never raises one. `ruby_fixtures:` names the exact
    files that only *model* an outside Jekyll site for a test; each must exist;
  * **the theme ratchet** — zer0-mistakes leaves completely (ADR 0006 decision
    4): every tracked code or configuration file that names the theme
    (`zer0-mistakes`, `jekyll-theme-zer0`, `ZER0_THEME_*`) lies under a
    `theme_ratchet:` prefix within its ceiling, or is listed in `theme_allowed:`
    (the Jekyll-theme option's own files, and this gate). Content that merely talks
    about the theme (Markdown, a site's `_posts`/`_docs`/`_data`, `docs/`, test
    fixtures that model outside repositories, the workspace tool's and the
    distribution lane's golden recordings of what their Ruby predecessors
    printed or computed about the old tree and its sites' pages, and the
    recordings of what each site's Jekyll build wrote, `web/site/fixtures/`,
    whose paths include the theme's own asset names) is not counted — it is
    content, and content is kept;
  * **the platform catalog** — unique ids, a known surface and status for each
    surface, and for every surface marked `done` a `proof` that is a test: a
    test file that exists, optionally `::` a test it holds — not a tool, a
    command line or a CI job, which prove nothing by existing. The test is
    looked up in the file: in Python, a top-level function or class, then a
    method or class inside that class (`SyncTest::test_runs`, a `[param]`
    suffix ignored), read with `ast`; in a `.ts`/`.tsx` test, `::"<title>"`, an
    `it`, `test`, `describe` or `suite` of that title. A surface's proof may be
    a list of such tests, each checked; a proof named on a cell that is not
    `done` must hold too. A row with a `studio` surface has an `extension` cell,
    or `extension_gap:` with the reason the extension does not owe it (ADR 0006
    decision 9: a studio capability the extension lacks is a gap the ledger
    reports, never one it omits);
  * **the sources** — every capability has a unique id, a known status and a
    `target` that is a platform capability id; a `done` capability names a `proof` that is such a test; a `dropped`
    one names the owner's decision in `decided_by`; a `specified` one — its source deleted by the owner's decision
    before it moved, what it did kept as a written spec — names that decision in `decided_by` and the spec, a file
    that exists, in `spec`, and keeps a live `target`: the platform still owes it;
  * **the deletion gate** — a source whose `path` no longer exists has no
    capability left `missing` or `partial`. Deleting a directory before its
    capabilities moved is exactly the loss ADR 0006 forbids, unless the owner
    decided it and what each capability did survives as its spec (`specified`).

`--report` prints the burn-down: Ruby files per prefix, capability status per
source, surface coverage per platform domain, and every studio capability the
extension does not match — a different status or a recorded `extension_gap`
(ADR 0006 decision 9 — reported, not failed). Exits 0 when everything holds, 1 with every violation listed, and
2 when the ledger is unreadable.

Run it from anywhere (`python3 tools/check_absorption.py`); CI runs it in
`.github/workflows/zer0-workspace.yml`. Its tests are
`tools/tests/test_check_absorption.py`.
"""

from __future__ import annotations

import argparse
import ast
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Callable, Iterable

import yaml

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "docs" / "plan" / "capabilities.yml"

RUBY_SUFFIXES = (".rb", ".rake", ".ru", ".erb", ".gemspec")
RUBY_NAMES = {"Gemfile", "Gemfile.lock", "Rakefile", ".ruby-version", "Guardfile"}
THEME_TERMS = re.compile(rb"zer0-mistakes|jekyll-theme-zer0|ZER0_THEME_")
THEME_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".mjs", ".cjs", ".rb", ".yml", ".yaml", ".json", ".gemspec", ".toml")
THEME_NAMES = {"Gemfile", "Gemfile.lock", "Dockerfile"}
THEME_SKIP_PREFIXES = (
    "docs/",
    "src/test/fixtures/",
    "features/",
    "tools/workspace/tests/golden/",
    "content/tests/distribution/golden/",
    "web/site/fixtures/",
)
# A proof is a test: a test file (under tests/ or test/, test_*, *.test.ts, *_test.py), optionally
# followed by `::` and a test in it — in Python its id (`test_x`, `SomeTest`, `SomeTest::test_x`,
# `test_x[case]`), in TypeScript its title in double quotes (`::"drafts a post"`).
TEST_FILE = re.compile(r"(^|/)tests?/|(^|/)test_[^/]*$|[._]test\.[a-z]+$")
TEST_ID = re.compile(r"[A-Za-z_]\w*(\[[^\]]*\])?(::[A-Za-z_]\w*(\[[^\]]*\])?)*")
TS_TESTS = (".ts", ".tsx")
TS_TITLE = re.compile(r'"[^"]+"')
TEST_DEFS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
STATUSES = ("missing", "partial", "done", "dropped", "specified")
OPEN = ("missing", "partial")
SURFACES = ("api", "studio", "extension", "mcp", "site", "ops")
SURFACE_STATUSES = ("missing", "partial", "done")


def is_ruby(path: str, head: Callable[[str], bytes]) -> bool:
    """True for a Ruby source, a Ruby build file, or an extensionless Ruby script."""
    name = path.rsplit("/", 1)[-1]
    if name in RUBY_NAMES or name.endswith(RUBY_SUFFIXES):
        return True
    if "." in name:
        return False
    first = head(path).split(b"\n", 1)[0]
    return first.startswith(b"#!") and b"ruby" in first


def is_theme_dependency(path: str, read: Callable[[str], bytes]) -> bool:
    """True for a code or configuration file that names the zer0-mistakes theme."""
    if path.startswith(THEME_SKIP_PREFIXES):
        return False
    name = path.rsplit("/", 1)[-1]
    if not (name in THEME_NAMES or name.endswith(THEME_SUFFIXES)):
        return False
    # A Jekyll collection or data directory (`_posts/`, `_docs/`, `_data/` …) holds content.
    if any(part.startswith("_") for part in path.split("/")[:-1]):
        return False
    if "CHANGELOG" in name:
        return False
    return bool(THEME_TERMS.search(read(path)))


def owning_prefix(path: str, prefixes: Iterable[str]) -> str | None:
    """The longest ratchet prefix that contains `path`, matched by whole segment."""
    best = None
    for prefix in prefixes:
        bare = prefix.rstrip("/")
        if path == bare or path.startswith(bare + "/"):
            if best is None or len(bare) > len(best.rstrip("/")):
                best = prefix
    return best


def check_fixtures(fixtures: list[str], exists: Callable[[str], bool]) -> list[str]:
    return [f"ruby_fixtures: {f} is listed but does not exist" for f in fixtures if not exists(f)]


def check_ratchet(
    files: list[str], ratchet: dict[str, int], what: str = "Ruby", fix: str = "port it to Python or TypeScript"
) -> tuple[list[str], Counter]:
    errors: list[str] = []
    counts: Counter = Counter()
    for path in files:
        prefix = owning_prefix(path, ratchet)
        if prefix is None:
            errors.append(f"new {what} outside the ratchet: {path} (ADR 0006 — {fix})")
        else:
            counts[prefix] += 1
    for prefix, ceiling in ratchet.items():
        if counts[prefix] > ceiling:
            errors.append(f"{what} grew under {prefix}: {counts[prefix]} files, ceiling {ceiling} (the ratchet only goes down)")
    return errors, counts


def python_test_in(source: bytes, test_id: str) -> bool:
    """True when the module defines `test_id`: a top-level function or class, then a function or class inside
    that class, and so on (`SyncTest::test_runs`); a `[param]` suffix names a case of it and is ignored."""
    try:
        body: list[ast.stmt] = ast.parse(source).body
    except (SyntaxError, ValueError):
        return False
    for name in re.sub(r"\[[^\]]*\]", "", test_id).split("::"):
        node = next((n for n in body if isinstance(n, TEST_DEFS) and n.name == name), None)
        if node is None:
            return False
        body = node.body if isinstance(node, ast.ClassDef) else []
    return True


def titled_test_in(source: bytes, title: str) -> bool:
    """True when a Vitest or Mocha test (or its describe or suite) of that title is written in the file:
    `it(`, `test(`, `describe(` or `suite(` and the title in any quotes — never `it.skip(`."""
    quoted = "|".join(f"{q}{re.escape(title)}{q}" for q in ("'", '"', "`"))
    return re.search(rf"\b(?:it|test|describe|suite)\(\s*(?:{quoted})", source.decode("utf-8", "replace")) is not None


def proof_problem(proof: str, exists: Callable[[str], bool], read: Callable[[str], bytes] | None = None) -> str | None:
    """What is wrong with a row's proof, or None: it must name a test file that exists and, after `::`, a test
    in it — not a tool, a command line or a CI job, which can pass without proving anything. Given `read`, the
    test is looked up in the file, so a renamed or deleted test fails here rather than proving nothing."""
    path, named, test = proof.partition("::")
    if not path:
        return "done without a proof"
    titled = path.endswith(TS_TESTS)
    if not TEST_FILE.search(path) or (named and not (TS_TITLE.fullmatch(test) if titled else TEST_ID.fullmatch(test))):
        return f"proof {proof!r} is not a test (a test file, optionally ::<test id>, or ::\"<title>\" in a .ts/.tsx test)"
    if not exists(path):
        return f"proof {path} does not exist"
    if named and read is not None:
        found = titled_test_in(read(path), test[1:-1]) if titled else python_test_in(read(path), test)
        if not found:
            return f"proof names {test}, which is not in {path}"
    return None


def proofs_of(value) -> list[str]:
    """A proof field as its list of tests: one string, or a list of them."""
    items = value if isinstance(value, list) else [value]
    return [str(item) for item in items if item]


def spec_problem(spec: str, exists: Callable[[str], bool]) -> str | None:
    """What is wrong with a `specified` row's spec, or None: a file that exists, optionally `#` a section of it."""
    path = spec.partition("#")[0]
    if not path:
        return "specified without a spec (the file that keeps what its deleted source did)"
    if not exists(path):
        return f"spec {path} does not exist"
    return None


def check_platform(
    platform: list[dict], exists: Callable[[str], bool], read: Callable[[str], bytes] | None = None
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for cap in platform:
        cid = cap.get("id", "?")
        if cid in seen:
            errors.append(f"platform/{cid}: duplicate capability id")
        seen.add(cid)
        if not cap.get("what"):
            errors.append(f"platform/{cid}: no what")
        surfaces = cap.get("surfaces") or {}
        if not surfaces:
            errors.append(f"platform/{cid}: no surfaces")
        proofs = cap.get("proof") or {}
        for surface, status in surfaces.items():
            if surface not in SURFACES:
                errors.append(f"platform/{cid}: unknown surface {surface!r} (one of {', '.join(SURFACES)})")
            if status not in SURFACE_STATUSES:
                errors.append(f"platform/{cid}: {surface} status {status!r} is not one of {', '.join(SURFACE_STATUSES)}")
            named = proofs_of(proofs.get(surface))
            if status == "done" and not named:
                errors.append(f"platform/{cid}: {surface} done without a proof")
            for proof in named:
                if problem := proof_problem(proof, exists, read):
                    errors.append(f"platform/{cid}: {surface} {problem}")
        if "extension_gap" in cap:
            if "extension" in surfaces:
                errors.append(f"platform/{cid}: extension_gap on a row that has an extension cell (one or the other)")
            elif not str(cap["extension_gap"] or "").strip():
                errors.append(f"platform/{cid}: extension_gap needs its reason (why the extension does not owe it)")
        elif "studio" in surfaces and "extension" not in surfaces:
            errors.append(
                f"platform/{cid}: a studio surface and no extension cell "
                "(give it an extension status, or extension_gap: <why the extension does not owe it>)"
            )
    return errors


def parity_gaps(platform: list[dict]) -> list[str]:
    """Every capability the studio offers that the extension does not match: a different status, a recorded
    `extension_gap`, or no extension cell at all (which check_platform also fails)."""
    gaps = []
    for cap in platform:
        surfaces = cap.get("surfaces") or {}
        if "studio" not in surfaces:
            continue
        cid, studio = cap.get("id"), surfaces["studio"]
        if "extension" in surfaces:
            if studio != surfaces["extension"]:
                gaps.append(f"{cid}: studio {studio}, extension {surfaces['extension']}")
        elif cap.get("extension_gap"):
            gaps.append(f"{cid}: studio {studio}, extension not owed — {cap['extension_gap']}")
        else:
            gaps.append(f"{cid}: studio {studio}, no extension cell")
    return gaps


def check_ledger(
    sources: list[dict],
    exists: Callable[[str], bool],
    targets: set[str] | None = None,
    read: Callable[[str], bytes] | None = None,
) -> list[str]:
    errors: list[str] = []
    seen: set[str] = set()
    for source in sources:
        sid = source.get("id", "?")
        if not source.get("path"):
            errors.append(f"{sid}: source has no path")
            continue
        caps = source.get("capabilities") or []
        if not caps:
            errors.append(f"{sid}: source lists no capabilities")
        open_caps = []
        for cap in caps:
            cid = cap.get("id", "?")
            where = f"{sid}/{cid}"
            if cid in seen:
                errors.append(f"{where}: duplicate capability id")
            seen.add(cid)
            status = cap.get("status")
            if status not in STATUSES:
                errors.append(f"{where}: status {status!r} is not one of {', '.join(STATUSES)}")
                continue
            if not cap.get("target"):
                errors.append(f"{where}: no target (where in the platform it goes)")
            elif targets is not None and status != "dropped" and cap["target"] not in targets:
                errors.append(f"{where}: target {cap['target']!r} is not a platform capability")
            if (status == "done" or cap.get("proof")) and (problem := proof_problem(str(cap.get("proof") or ""), exists, read)):
                errors.append(f"{where}: {problem}")
            if status == "dropped" and not cap.get("decided_by"):
                errors.append(f"{where}: dropped without decided_by (only the owner drops a capability)")
            if status == "specified":
                if not cap.get("decided_by"):
                    errors.append(f"{where}: specified without decided_by (only the owner deletes a source early)")
                if problem := spec_problem(str(cap.get("spec") or ""), exists):
                    errors.append(f"{where}: {problem}")
            if status in OPEN:
                open_caps.append(cid)
        if open_caps and not exists(source["path"]):
            errors.append(
                f"{sid}: {source['path']} is gone but {len(open_caps)} capabilities are not absorbed "
                f"({', '.join(open_caps[:5])}{'…' if len(open_caps) > 5 else ''})"
            )
    return errors


def tracked_files(root: Path) -> list[str]:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    return [p for p in out.decode().split("\0") if p]


def read_all(root: Path) -> Callable[[str], bytes]:
    def read(path: str) -> bytes:
        try:
            return (root / path).read_bytes()
        except OSError:
            return b""

    return read


def read_head(root: Path) -> Callable[[str], bytes]:
    def head(path: str) -> bytes:
        try:
            with open(root / path, "rb") as fh:
                return fh.read(128)
        except OSError:
            return b""

    return head


def tighten(ratchet: dict[str, int], counts: Counter) -> dict[str, int]:
    return {p: min(c, counts[p]) for p, c in ratchet.items() if min(c, counts[p]) > 0}


def write_ratchet(ledger_path: Path, ratchet: dict[str, int], key: str = "ruby_ratchet") -> None:
    """Rewrite only one ratchet block, leaving the rest of the file's bytes alone (the block's comments too)."""
    lines = ledger_path.read_text().splitlines(keepends=True)
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{key}:"))
    end = start + 1
    while end < len(lines) and (lines[end].startswith((" ", "\t")) or not lines[end].strip()):
        end += 1
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    comments = [line for line in lines[start + 1 : end] if line.lstrip().startswith("#")]
    body = [f"  {p}: {c}\n" for p, c in ratchet.items()] or []
    head = f"{key}:\n" if body else f"{key}: {{}}\n"
    ledger_path.write_text("".join(lines[:start] + [head] + comments + body + lines[end:]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", action="store_true", help="print the burn-down")
    parser.add_argument("--tighten", action="store_true", help="lower ratchet ceilings to today's counts")
    args = parser.parse_args(argv)

    try:
        ledger = yaml.safe_load(LEDGER.read_text())
    except (OSError, yaml.YAMLError) as exc:
        print(f"cannot read {LEDGER.relative_to(ROOT)}: {exc}", file=sys.stderr)
        return 2
    if not isinstance(ledger, dict) or ledger.get("schema") != "capabilities/v1":
        print(f"{LEDGER.relative_to(ROOT)}: expected schema: capabilities/v1", file=sys.stderr)
        return 2

    exists = lambda p: (ROOT / p).exists()  # noqa: E731 — a one-line predicate
    ratchet = {str(k): int(v) for k, v in (ledger.get("ruby_ratchet") or {}).items()}
    fixtures = [str(f) for f in ledger.get("ruby_fixtures") or []]
    head = read_head(ROOT)
    tracked = tracked_files(ROOT)
    ruby = [p for p in tracked if is_ruby(p, head) and p not in fixtures]
    errors, counts = check_ratchet(ruby, ratchet)
    errors += check_fixtures(fixtures, exists)
    theme_ratchet = {str(k): int(v) for k, v in (ledger.get("theme_ratchet") or {}).items()}
    theme_allowed = [str(f) for f in ledger.get("theme_allowed") or []]
    read = read_all(ROOT)
    themed = [p for p in tracked if p not in theme_allowed and is_theme_dependency(p, read)]
    theme_errors, theme_counts = check_ratchet(
        themed, theme_ratchet, "zer0-mistakes dependency", "only the Jekyll-theme option names the theme (theme_allowed:)"
    )
    errors += theme_errors
    platform = ledger.get("platform") or []
    errors += check_platform(platform, exists, read)
    sources = ledger.get("sources") or []
    errors += check_ledger(sources, exists, {c.get("id") for c in platform}, read)

    if args.tighten:
        write_ratchet(LEDGER, tighten(ratchet, counts))
        write_ratchet(LEDGER, tighten(theme_ratchet, theme_counts), "theme_ratchet")
        print("ruby_ratchet and theme_ratchet tightened")

    if args.report:
        print(f"Ruby files: {len(ruby)}")
        for prefix in sorted(ratchet):
            print(f"  {prefix:<40} {counts[prefix]:>4} / {ratchet[prefix]}")
        print(f"zer0-mistakes dependencies (code and config): {len(themed)}")
        for prefix in sorted(theme_ratchet):
            print(f"  {prefix:<40} {theme_counts[prefix]:>4} / {theme_ratchet[prefix]}")
        print("Capabilities:")
        for source in sources:
            tally = Counter(c.get("status") for c in source.get("capabilities") or [])
            parts = ", ".join(f"{tally[s]} {s}" for s in STATUSES if tally[s])
            print(f"  {source.get('id', '?'):<24} {parts}")
        print("Platform surfaces (done/partial/missing):")
        for surface in SURFACES:
            tally = Counter(c["surfaces"][surface] for c in platform if surface in (c.get("surfaces") or {}))
            print(f"  {surface:<10} {tally['done']:>3} / {tally['partial']:>3} / {tally['missing']:>3}")
        gaps = parity_gaps(platform)
        print(f"Studio/extension parity gaps: {len(gaps)}")
        for gap in gaps:
            print(f"  - {gap}")

    if errors:
        print(f"absorption gate: {len(errors)} problem(s)", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    total = sum(len(s.get("capabilities") or []) for s in sources)
    print(
        f"absorption gate OK — {len(ruby)} Ruby files and {len(themed)} zer0-mistakes dependencies within their ratchets, "
        f"{len(platform)} platform capabilities, "
        f"{len(sources)} sources with {total} capabilities"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
