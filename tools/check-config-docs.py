#!/usr/bin/env python3
"""Gate the settings documentation against `package.json`.

zer0-CMS documents every VS Code setting twice: `docs/CONFIG.md` section 5 is
the full table, and `README.md` names the handful that matter on day one. Both
were a convention — someone remembered, or nobody noticed. A setting renamed in
the manifest and left stale in the docs reads exactly like a setting that
exists, which is the worst kind of documentation bug: it costs a reader an
afternoon before they believe the file over the prose.

This turns that convention into a check. It asserts, using only the standard
library so it runs anywhere `python3` does:

  * every backticked ``zer0Cms.*`` id in `docs/CONFIG.md` section 5 is a
    setting the manifest actually contributes;
  * every backticked ``zer0Cms.*`` id in `README.md` is too;
  * every setting the manifest contributes appears in `docs/CONFIG.md`
    section 5.

`contributes.configuration` is read in both of the shapes VS Code accepts — a
single object with `properties`, or an array of titled sections each with their
own `properties` — because this repository is mid-move from the first to the
second and the gate must hold on either side of that change.

Exits 0 when the three sets agree, 1 with a readable list of what is missing on
each side, and 2 when a file it needs is unreadable.

Run it directly (`python3 tools/check-config-docs.py`); CI runs the same
command in `.github/workflows/extension.yml`.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PACKAGE_JSON = ROOT / "package.json"
CONFIG_DOC = ROOT / "docs" / "CONFIG.md"
README = ROOT / "README.md"

# The heading that opens the settings table, and any level-2 heading that ends
# it. Section 5 is bounded by headings rather than line numbers so the check
# survives every edit above and below it.
SECTION_START = re.compile(r"^##\s+5\.\s", re.MULTILINE)
NEXT_SECTION = re.compile(r"^##\s+(?!5\.)", re.MULTILINE)

# A setting is cited as an inline code span. Trailing dots are part of the id
# (`zer0Cms.panel.sections`), so the class deliberately includes `.`.
SETTING_REF = re.compile(r"`(zer0Cms\.[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)*)`")


def fail(message: str) -> None:
    """Report a problem the script cannot work around, and stop."""
    print(f"check-config-docs: {message}", file=sys.stderr)
    raise SystemExit(2)


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        fail(f"cannot read {path.relative_to(ROOT)}: {error}")
        raise  # unreachable; keeps the return type honest for type checkers


def manifest_ids() -> tuple[set[str], set[str]]:
    """Return (contributed setting ids, contributed command ids).

    Commands are collected only so an id documented in the wrong place gets a
    useful message instead of a bare "unknown".
    """
    raw = read_text(PACKAGE_JSON)
    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as error:
        fail(f"package.json is not valid JSON: {error}")
        raise

    contributes = manifest.get("contributes") or {}
    configuration = contributes.get("configuration")

    # Both shapes VS Code accepts: one object, or an array of titled sections.
    if isinstance(configuration, dict):
        sections = [configuration]
    elif isinstance(configuration, list):
        sections = [s for s in configuration if isinstance(s, dict)]
    elif configuration is None:
        sections = []
    else:
        fail("contributes.configuration is neither an object nor an array")
        raise

    settings: set[str] = set()
    for section in sections:
        properties = section.get("properties")
        if isinstance(properties, dict):
            settings.update(properties.keys())

    commands = {
        c["command"]
        for c in contributes.get("commands") or []
        if isinstance(c, dict) and isinstance(c.get("command"), str)
    }
    return settings, commands


def config_section_five(text: str) -> str:
    """Slice `docs/CONFIG.md` down to section 5."""
    start = SECTION_START.search(text)
    if not start:
        fail("docs/CONFIG.md has no '## 5.' heading — the settings table moved")
        raise
    rest = text[start.end():]
    end = NEXT_SECTION.search(rest)
    return rest[: end.start()] if end else rest


def cited(text: str) -> set[str]:
    return set(SETTING_REF.findall(text))


def report(title: str, ids: set[str], note: str) -> None:
    print(f"\n{title}", file=sys.stderr)
    for setting in sorted(ids):
        print(f"  - {setting}", file=sys.stderr)
    print(f"  {note}", file=sys.stderr)


def main() -> int:
    settings, commands = manifest_ids()
    if not settings:
        fail("package.json contributes no configuration properties")

    section_five = config_section_five(read_text(CONFIG_DOC))
    documented = cited(section_five)
    readme_cited = cited(read_text(README))

    undocumented = settings - documented
    doc_ghosts = documented - settings
    readme_ghosts = readme_cited - settings

    if not (undocumented or doc_ghosts or readme_ghosts):
        print(
            f"check-config-docs: OK — {len(settings)} settings, "
            f"all documented in docs/CONFIG.md §5; "
            f"{len(readme_cited)} cited in README.md, all real."
        )
        return 0

    print(
        f"check-config-docs: FAILED — {len(settings)} contributed settings, "
        f"{len(documented)} documented in docs/CONFIG.md §5.",
        file=sys.stderr,
    )

    if undocumented:
        report(
            "Contributed but missing from docs/CONFIG.md §5:",
            undocumented,
            "Add a row to the matching subsection of §5.",
        )
    if doc_ghosts:
        report(
            "Documented in docs/CONFIG.md §5 but not contributed:",
            doc_ghosts,
            _ghost_note(doc_ghosts, commands),
        )
    if readme_ghosts:
        report(
            "Cited in README.md but not contributed:",
            readme_ghosts,
            _ghost_note(readme_ghosts, commands),
        )
    return 1


def _ghost_note(ids: set[str], commands: set[str]) -> str:
    overlap = sorted(ids & commands)
    if overlap:
        return (
            "These are contributed COMMANDS, not settings: "
            + ", ".join(overlap)
            + ". Cite them outside the settings table."
        )
    return "Remove the row, or restore the setting in package.json."


if __name__ == "__main__":
    sys.exit(main())
