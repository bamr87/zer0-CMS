#!/usr/bin/env python3
"""
carry-study-guides.py — re-attach the site's study guides to freshly synced pages.

The docs aggregator regenerates every page under ``overthewire/**`` from the
upstream OverTheWire repo, which discards two things this site adds on top of
the vendored text:

  * the "Study guide" section at the end of each page, fenced by the
    ``<!-- study-guide:start -->`` / ``<!-- study-guide:end -->`` markers, and
  * the ``description`` / ``excerpt`` front matter, rewritten as a one-sentence
    summary of the page (upstream's derived value is truncated body text).

Run this after ``aggregate_docs.sh`` and before moving the refreshed pages into
``overthewire/``. For every page in NEW_DIR it looks up the same page in the
current ``overthewire/`` tree and copies those two things across, in place.

Usage:
  carry-study-guides.py NEW_DIR [--old-dir overthewire]

NEW_DIR is the refreshed tree, laid out like ``overthewire/`` (for example
``pages/_docs/wargames/overthewire``). Pages with no counterpart, or whose
counterpart has no study guide, are listed and left unchanged.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

import yaml

START = "<!-- study-guide:start -->"
END = "<!-- study-guide:end -->"
TOP_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*:")
FRONT = re.compile(r"\A---\n(.*?)\n---\n", re.S)


def split(text: str) -> tuple[list[str], str]:
    m = FRONT.match(text)
    if not m:
        raise ValueError("no front matter")
    return m.group(1).split("\n"), text[m.end():]


def key_end(lines: list[str], start: int) -> int:
    """Index just past the (possibly multi-line) value of the key at ``start``."""
    j = start + 1
    while j < len(lines) and not TOP_KEY.match(lines[j]) and not lines[j].startswith("- "):
        j += 1
    return j


def get_block(lines: list[str], key: str) -> list[str] | None:
    i = next((n for n, line in enumerate(lines) if line.startswith(key + ":")), None)
    return None if i is None else lines[i:key_end(lines, i)]


def set_block(lines: list[str], key: str, block: list[str], after: str = "description") -> None:
    i = next((n for n, line in enumerate(lines) if line.startswith(key + ":")), None)
    if i is not None:
        lines[i:key_end(lines, i)] = block
        return
    a = next((n for n, line in enumerate(lines) if line.startswith(after + ":")), None)
    at = key_end(lines, a) if a is not None else len(lines)
    lines[at:at] = block


def strip_guide(body: str) -> str:
    s = body.find(START)
    if s == -1:
        return body
    e = body.find(END, s)
    if e == -1:
        raise ValueError("unterminated study-guide block")
    before = body[:s]
    if before.endswith("\n\n"):
        before = before[:-2]  # remove only the blank line we added, never upstream text
    return before + "\n" + body[e + len(END):].lstrip("\n")


def carry(old_text: str, new_text: str) -> str | None:
    """Return ``new_text`` with the old page's guide and summary, or None if the old page has no guide."""
    old_fm, old_body = split(old_text)
    s = old_body.find(START)
    if s == -1:
        return None
    e = old_body.find(END, s)
    if e == -1:
        raise ValueError("unterminated study-guide block in the old page")
    guide = old_body[s:e + len(END)]

    new_fm, new_body = split(new_text)
    for key in ("description", "excerpt"):
        block = get_block(old_fm, key)
        if block is not None:
            set_block(new_fm, key, block)
    new_body = strip_guide(new_body)
    result = "---\n" + "\n".join(new_fm) + "\n---\n" + new_body.rstrip("\n") + "\n\n" + guide + "\n"
    yaml.safe_load("\n".join(new_fm))  # fail loudly on broken front matter
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Re-attach study guides to freshly synced pages.")
    ap.add_argument("new_dir", type=Path, help="refreshed tree, laid out like overthewire/")
    ap.add_argument("--old-dir", type=Path, default=Path("overthewire"),
                    help="current tree that holds the study guides (default: overthewire)")
    args = ap.parse_args()

    if not args.new_dir.is_dir() or not args.old_dir.is_dir():
        print("both NEW_DIR and --old-dir must be directories", file=sys.stderr)
        return 2

    done, skipped = 0, []
    for new_path in sorted(args.new_dir.rglob("*.md")):
        rel = new_path.relative_to(args.new_dir)
        old_path = args.old_dir / rel
        if not old_path.exists():
            skipped.append(f"{rel}: no counterpart in {args.old_dir}")
            continue
        merged = carry(old_path.read_text(encoding="utf-8"), new_path.read_text(encoding="utf-8"))
        if merged is None:
            skipped.append(f"{rel}: current page has no study guide")
            continue
        new_path.write_text(merged, encoding="utf-8")
        done += 1

    print(f"carried the study guide onto {done} page(s)")
    for line in skipped:
        print(f"  skipped {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
