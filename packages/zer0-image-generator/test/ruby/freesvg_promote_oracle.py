#!/usr/bin/env python3
"""Byte-identity oracle for the Ruby FreeSVG `promote` port.

Reads a JSON spec on stdin and runs the REAL tools/svg/freesvg.py `promote`
against a throwaway repo root with `_http` mocked (the same technique as
test/test_freesvg.py), then writes the resulting MANIFEST.json bytes to stdout.
The Ruby differential test drives its own promote with an equivalent faked
transport and asserts the two manifests are byte-for-byte identical.

Spec: {"id": "7", "item": {...}, "name": "", "tags": [...] | null,
       "file_url": {"substr": "...", "b64": "<base64 svg bytes>"} | null}

The manifest entry produced is independent of the (temp) repo path — source_url
is a constant API route, the file path is repo-relative, size_kb is the SVG
byte length — so comparing the two files directly is a valid parity check.
"""
import base64
import json
import os
import shutil
import sys
import tempfile
from unittest import mock

REPO = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, os.path.join(REPO, "tools", "svg"))
import freesvg  # noqa: E402


def fake_jwt(exp: float) -> str:
    payload = base64.urlsafe_b64encode(json.dumps({"exp": exp}).encode()).decode().rstrip("=")
    return f"e30.{payload}.sig"


def main() -> int:
    spec = json.load(sys.stdin)
    svg_id = spec.get("id", "7")
    item = spec["item"]
    name = spec.get("name", "")
    tags = spec.get("tags")
    file_url = spec.get("file_url")

    tmp = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmp, "tools", "svg", "library"))
        shutil.copy(os.path.join(REPO, "tools", "svg", "svg-check.py"),
                    os.path.join(tmp, "tools", "svg", "svg-check.py"))
        # svg-check.py is a thin CLI over the engine's lint_svg(), found at its
        # real relative path — give the fake ROOT the same layout.
        os.makedirs(os.path.join(tmp, "lib", "zer0_image_generator"))
        shutil.copy(os.path.join(REPO, "lib", "zer0_image_generator", "preview_generator.py"),
                    os.path.join(tmp, "lib", "zer0_image_generator", "preview_generator.py"))
        manifest = os.path.join(tmp, "tools", "svg", "library", "MANIFEST.json")
        with open(manifest, "w") as f:
            json.dump({"entries": []}, f)

        env = {
            "FREESVG_CACHE_DIR": os.path.join(tmp, "cache"),
            "FREESVG_MANIFEST": manifest,
            "FREESVG_EMAIL": "u@example.com",
            "FREESVG_PASSWORD": "pw",
        }

        def side_effect(method, url, body=None, token=None):
            if "auth/login" in url:
                return 200, json.dumps({"token": fake_jwt(9999999999)}).encode()
            if f"/svg/{svg_id}" in url:
                return 200, json.dumps({"data": [item]}).encode()
            if file_url and file_url["substr"] in url:
                return 200, base64.b64decode(file_url["b64"])
            raise AssertionError(f"unexpected url {url}")

        with mock.patch.dict(os.environ, env), \
                mock.patch.object(freesvg, "ROOT", tmp), \
                mock.patch.object(freesvg, "_http", side_effect=side_effect):
            freesvg.promote(svg_id, name, tags)

        with open(manifest, "rb") as f:
            sys.stdout.buffer.write(f.read())
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
