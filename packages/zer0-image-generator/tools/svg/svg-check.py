#!/usr/bin/env python3
"""
svg-check.py — deterministic SVG lint. No dependencies, stdlib only.

These are the checks you do NOT want to burn model tokens on. Vision is for
composition; this is for correctness. Exit 1 on error, 0 on pass.

    python3 tools/svg/svg-check.py banner.svg [--max-kb 200] [--strict]
"""
import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK = "http://www.w3.org/1999/xlink"
NUM = re.compile(r"-?\d*\.?\d+(?:[eE][-+]?\d+)?")

errors: list[str] = []
warnings: list[str] = []


def tag(el) -> str:
    return el.tag.split("}")[-1] if "}" in el.tag else el.tag


def href(el):
    return el.get("href") or el.get(f"{{{XLINK}}}href")


def parse_viewbox(root):
    vb = root.get("viewBox")
    if not vb:
        return None
    parts = [float(n) for n in NUM.findall(vb)]
    return tuple(parts[:4]) if len(parts) == 4 else None


def coords_in_path(d: str):
    """Rough absolute-coordinate sample. Ignores relative commands on purpose —
    we only want a cheap 'is this wildly outside the canvas' signal."""
    out = []
    for seg in re.findall(r"[MLHVCSQTA][^A-Za-z]*", d):
        nums = [float(n) for n in NUM.findall(seg[1:])]
        cmd = seg[0]
        if cmd in "ML" and len(nums) >= 2:
            out += list(zip(nums[0::2], nums[1::2]))
        elif cmd == "C":
            out += list(zip(nums[4::6], nums[5::6]))
    return out


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

    raw = open(args.path, "rb").read()
    kb = len(raw) / 1024
    if kb > args.max_kb:
        errors.append(f"file is {kb:.0f}KB, budget is {args.max_kb:.0f}KB "
                      f"(run svgo, or reduce path precision)")

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"ERROR not well-formed XML: {e}", file=sys.stderr)
        return 1

    if tag(root) != "svg":
        errors.append(f"root element is <{tag(root)}>, expected <svg>")

    vb = parse_viewbox(root)
    if vb is None:
        errors.append("no viewBox on root — the art will not scale. "
                      'Add viewBox="0 0 W H".')

    # Accessibility + provenance
    kids = [tag(c) for c in root]
    if "title" not in kids:
        warnings.append("no <title> as first child (screen readers, and it "
                        "shows as a tooltip)")
    if root.get("role") != "img":
        warnings.append('missing role="img" on root')

    ids, dupes = set(), set()
    used_refs = set()
    ext_refs = []

    for el in root.iter():
        t = tag(el)
        _id = el.get("id")
        if _id:
            (dupes.add(_id) if _id in ids else ids.add(_id))

        h = href(el)
        if h:
            if h.startswith("#"):
                used_refs.add(h[1:])
            elif h.startswith(("http://", "https://", "//")):
                ext_refs.append(h)
            elif h.startswith("data:image") and t == "image":
                errors.append("embedded raster <image> — that is a PNG in a "
                              "trenchcoat, not vector art")
            elif t == "image":
                errors.append(f"external <image> reference: {h}")

        for attr, val in el.attrib.items():
            m = re.match(r"url\(#([^)]+)\)", (val or "").strip())
            if m:
                used_refs.add(m.group(1))

        # geometry sanity
        if vb and t == "path" and el.get("d"):
            minx, miny, w, h_ = vb
            pad = max(w, h_) * 2
            for x, y in coords_in_path(el.get("d")):
                if not (minx - pad <= x <= minx + w + pad and
                        miny - pad <= y <= miny + h_ + pad):
                    warnings.append(
                        f"path coordinate ({x:g},{y:g}) is far outside the "
                        f"viewBox — likely a stray control point")
                    break

        if t == "path" and el.get("d"):
            long_decimals = re.findall(r"\d+\.\d{5,}", el.get("d"))
            if len(long_decimals) > 20:
                warnings.append("path data carries 5+ decimal places; round "
                                "to 2-3 to cut file size ~40%")

        if t == "text" and args.strict:
            warnings.append("<text> present — fonts are not guaranteed at "
                            "render time. Convert to paths for distribution.")

    if ext_refs:
        errors.append(f"external network references: {', '.join(ext_refs[:3])}")
    if dupes:
        errors.append(f"duplicate id(s): {', '.join(sorted(dupes))}")
    dangling = used_refs - ids
    if dangling:
        errors.append(f"reference(s) to missing id(s): "
                      f"{', '.join(sorted(dangling))} — gradient or clipPath "
                      f"will silently render as black/none")

    for w in warnings:
        print(f"WARN  {w}", file=sys.stderr)
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)

    if errors or (args.strict and warnings):
        return 1
    print(f"svg-check: {args.path} clean ({kb:.1f}KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
