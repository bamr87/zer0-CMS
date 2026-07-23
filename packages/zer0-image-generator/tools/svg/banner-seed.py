#!/usr/bin/env python3
"""
banner-seed.py — parametric adapter over the engine's own local banner template.

This is the repo-native "generator with knobs" for the svg-sweep workflow:
sweeping it renders a contact sheet of the exact SVG the `local` provider
would ship, across seeds — so template changes in preview_generator.py are
judged on real output, not on a lookalike.

    python3 tools/svg/banner-seed.py --seed 7 --out .sweep/seed-7.svg
    python3 tools/svg/banner-seed.py --slug my-post --out banner.svg
    bash tools/svg/svg-sweep.sh tools/svg/banner-seed.py 12

--slug reproduces a specific post's banner (seed derived the way the engine
derives it); a bare --seed drives the palette/composition scheme directly,
which is what a sweep wants.
"""
import argparse
import importlib.util
import os
import sys

ENGINE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), os.pardir, os.pardir,
    "lib", "zer0_image_generator", "preview_generator.py",
)


def load_engine():
    spec = importlib.util.spec_from_file_location("preview_generator", ENGINE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--slug", default="",
                    help="derive the seed from a post slug, as the engine does")
    ap.add_argument("--out", default=".sweep/banner.svg")
    args = ap.parse_args()

    pg = load_engine()
    if args.slug:
        title, seed = args.slug, pg.seed_for(args.slug)
    else:
        title, seed = f"banner-seed-{args.seed}", args.seed

    svg_text, notes = pg.sanitize_svg(pg.render_local_svg(title, seed))
    for note in notes:
        print(f"sanitizer: {note}", file=sys.stderr)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(svg_text)
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
