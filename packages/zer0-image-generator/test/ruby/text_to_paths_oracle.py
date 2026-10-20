#!/usr/bin/env python3
"""Differential-test oracle for svg/text_to_paths.rb.

Reads {"fmt": [...], "runs": [...], "fits": [...], "docs": [...]} on stdin,
answers each with the REAL preview_generator functions, and prints JSON. The
Ruby test asks its port the same questions and compares: geometry byte for
byte, documents by their `d` strings, labels and counts in document order.
"""
import importlib.util
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ORACLE = os.path.join(HERE, "..", "..", "lib", "zer0_image_generator", "preview_generator.py")
spec = importlib.util.spec_from_file_location("pg", ORACLE)
pg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pg)


def doc_summary(result):
    return {
        "d": re.findall(r'\sd="([^"]*)"', result.svg),
        "labels": re.findall(r'aria-label="([^"]*)"', result.svg),
        "converted": result.converted, "stripped": result.stripped,
        "fitted": result.fitted, "missing": result.missing_glyphs, "notes": result.notes,
    }


def main():
    q = json.load(sys.stdin)
    out = {"fmt": [pg._fmt2(v) for v in q.get("fmt", [])], "runs": [], "fits": [], "docs": [],
           "metrics": {}}
    for family in pg.BUNDLED_FONTS:
        f = pg.load_bundled_font(family)
        out["metrics"][family] = [f.units_per_em, f.ascender, f.descender, f.x_height,
                                  len(f.cmap), f.num_glyphs]
    for r in q.get("runs", []):
        font = pg.load_bundled_font(r["family"])
        d, adv, missing = pg.glyph_run_path(font, r["text"], r["x"], r["y"], r["size"], r["ls"])
        out["runs"].append({"d": d, "advance": repr(adv), "missing": missing,
                            "width": repr(pg.text_advance(font, r["text"], r["size"], r["ls"])),
                            "shift": repr(pg.baseline_shift(font, r["baseline"], r["size"]))})
    for f in q.get("fits", []):
        font = pg.load_bundled_font(f["family"])
        lines, size = pg.fit_headline(font, f["text"], f["width"], f["lines"], f["max"],
                                      f["min"], max_height=f["height"])
        out["fits"].append({"lines": lines, "size": repr(size)})
    for doc in q.get("docs", []):
        out["docs"].append(doc_summary(pg.svg_text_to_paths(doc["svg"], doc["mode"], doc["family"])))
    json.dump(out, sys.stdout, ensure_ascii=False)


if __name__ == "__main__":
    main()
