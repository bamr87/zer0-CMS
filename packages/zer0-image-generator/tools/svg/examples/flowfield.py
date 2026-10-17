#!/usr/bin/env python3
"""
flowfield.py — a parametric SVG generator. Stdlib only.

The point of this file is not the artwork. It is the *shape* of the work:
you ask Claude for a generator with named knobs, then you tune numbers and
re-run. Claude is very good at writing this. Claude is bad at hand-authoring
four hundred bezier control points, and so is everyone else.

    python3 tools/svg/examples/flowfield.py --seed 7 --out .sweep/piece.svg
"""
import argparse
import math
import random

PALETTES = {
    "ember":  ["#1a1423", "#f24236", "#f5a623", "#f7e8d3"],
    "cyanic": ["#0b132b", "#1c7293", "#5bc0be", "#e8f1f2"],
    "moss":   ["#16211b", "#3e6b48", "#a3c9a8", "#e9edc9"],
}


def value_noise(seed):
    """Cheap hash-based value noise with bilinear interpolation."""
    def h(ix, iy):
        n = ix * 374761393 + iy * 668265263 + seed * 1442695040888963407
        n = (n ^ (n >> 13)) * 1274126177
        return ((n ^ (n >> 16)) & 0xFFFF) / 0xFFFF

    def smooth(t):
        return t * t * (3 - 2 * t)

    def sample(x, y):
        ix, iy = math.floor(x), math.floor(y)
        fx, fy = smooth(x - ix), smooth(y - iy)
        a, b = h(ix, iy), h(ix + 1, iy)
        c, d = h(ix, iy + 1), h(ix + 1, iy + 1)
        return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy

    return sample


def build(seed, w, h, lines, steps, scale, palette):
    rng = random.Random(seed)
    noise = value_noise(seed)
    colors = PALETTES[palette]
    out = []

    for _ in range(lines):
        x, y = rng.uniform(0, w), rng.uniform(0, h)
        pts = [(x, y)]
        for _ in range(steps):
            angle = noise(x / scale, y / scale) * math.tau * 2
            x += math.cos(angle) * 4
            y += math.sin(angle) * 4
            if not (-20 < x < w + 20 and -20 < y < h + 20):
                break
            pts.append((x, y))
        if len(pts) < 8:
            continue
        d = "M" + " L".join(f"{px:.0f},{py:.0f}" for px, py in pts)
        stroke = rng.choice(colors[1:])
        width = rng.uniform(0.4, 2.4)
        op = rng.uniform(0.25, 0.8)
        out.append(
            f'<path d="{d}" fill="none" stroke="{stroke}" '
            f'stroke-width="{width:.2f}" stroke-opacity="{op:.2f}" '
            f'stroke-linecap="round"/>'
        )

    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" '
        f'role="img">\n'
        f'  <title>Flow field, seed {seed}, palette {palette}</title>\n'
        f'  <rect width="{w}" height="{h}" fill="{colors[0]}"/>\n  '
        + "\n  ".join(out)
        + "\n</svg>\n"
    )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default="art/flowfield.svg")
    p.add_argument("--width", type=int, default=800)
    p.add_argument("--height", type=int, default=800)
    p.add_argument("--lines", type=int, default=240)
    p.add_argument("--steps", type=int, default=70)
    p.add_argument("--scale", type=float, default=180.0)
    p.add_argument("--palette", choices=list(PALETTES), default="cyanic")
    a = p.parse_args()

    import os
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w") as f:
        f.write(build(a.seed, a.width, a.height, a.lines, a.steps,
                      a.scale, a.palette))
    print(a.out)
