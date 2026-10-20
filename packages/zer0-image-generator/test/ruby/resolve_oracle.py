#!/usr/bin/env python3
"""Differential-test oracle for the Ruby settings port.

Reads a JSON spec {"args": {...}, "config": {...}} on stdin, constructs an
argparse.Namespace with exactly the attributes resolve_settings reads (argparse
defaults filled in for anything omitted, plus parse_args' enhance implication),
calls the real preview_generator.resolve_settings, and dumps the resolved
Settings as JSON on stdout. Env is inherited from the process the harness
launches us with, so the Ruby side and this side see the same environment.
"""
import dataclasses
import importlib.util
import json
import os
import sys
from argparse import Namespace

HERE = os.path.dirname(os.path.abspath(__file__))
ORACLE = os.path.join(HERE, "..", "..", "lib", "zer0_image_generator",
                      "preview_generator.py")

spec = importlib.util.spec_from_file_location("pg", ORACLE)
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)

# argparse dests resolve_settings touches, with build_arg_parser's defaults.
ARG_DEFAULTS = {
    "dry_run": False, "verbose": False, "file": None, "collection": None,
    "provider": None, "model": None, "output_dir": None, "force": False,
    "list_missing": False, "parallel": None, "enhance": False,
    "enhance_prompt": None, "enhance_model": None, "enhance_quality": None,
    "enhance_fidelity": None, "enhance_format": None, "prompt_engine": None,
    "review": None, "rasterizer": None, "style": None, "assets_prefix": None,
    "no_auto_prefix": False, "collections_dir": None, "front_matter_key": None,
    "authors_file": None, "batch": 0,
}


def build_namespace(overrides):
    fields = dict(ARG_DEFAULTS)
    for key, value in (overrides or {}).items():
        if key not in fields:
            raise SystemExit(f"unknown arg field: {key}")
        fields[key] = value
    # parse_args post-processing (historical): these imply --enhance.
    if fields["enhance_prompt"] or fields["enhance_fidelity"] or fields["enhance_format"]:
        fields["enhance"] = True
    return Namespace(**fields)


def main():
    payload = json.load(sys.stdin)
    args = build_namespace(payload.get("args"))
    config = payload.get("config") or {}
    settings = pg.resolve_settings(args, config)
    json.dump(dataclasses.asdict(settings), sys.stdout, sort_keys=True)


if __name__ == "__main__":
    main()
