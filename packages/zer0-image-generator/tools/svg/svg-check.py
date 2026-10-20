#!/usr/bin/env python3
"""
svg-check.py — deterministic SVG lint. No dependencies, stdlib only.

These are the checks you do NOT want to burn model tokens on. Vision is for
composition; this is for correctness. Exit 1 on error, 0 on pass.

    python3 tools/svg/svg-check.py banner.svg [--max-kb 200] [--strict]

The checks themselves live in the engine (`lint_svg()` in
lib/zer0_image_generator/preview_generator.py), so the authoring loop here and
the production illustration loop gate on the SAME lint — they cannot drift.
This file is the CLI over it, and stays the oracle that
lib/zer0_image_generator/svg/lint.rb is pinned to.
"""
import argparse
import importlib.util
import os
import sys

ENGINE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "lib",
                      "zer0_image_generator", "preview_generator.py")


def load_engine():
    spec = importlib.util.spec_from_file_location("zer0_preview_engine", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("path")
    ap.add_argument("--max-kb", type=float, default=250.0)
    ap.add_argument("--strict", action="store_true",
                    help="treat warnings as errors")
    args = ap.parse_args()

    if not os.path.exists(args.path):
        print(f"ERROR missing file: {args.path}", file=sys.stderr)
        return 1

    with open(args.path, "rb") as fh:
        raw = fh.read()
    report = load_engine().lint_svg(raw, args.path, max_kb=args.max_kb,
                                    strict=args.strict)
    for line in report.stderr_lines():
        print(line, file=sys.stderr)
    for line in report.stdout_lines():
        print(line)
    return 0 if report.clean else 1


if __name__ == "__main__":
    sys.exit(main())
