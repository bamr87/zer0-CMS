#!/usr/bin/env python3
"""
lowpoly.py — faceted low-poly gradient field. Stdlib only.

A jittered triangle grid (interior vertices perturbed, borders pinned so
there are no gaps) painted with a vertical palette gradient, then each
facet is brightened/darkened by smooth value noise so the surface reads
as folded planes catching light. A warm radial "sun" region pulls the
focal point off-center. This is the low-poly-background look, generated:
tune grid density and jitter, re-run, judge the population.

    python3 tools/svg/examples/lowpoly.py --seed 5 --palette dusk --out .sweep/poly.svg
"""
import argparse
import math
import os
import random

# vertical gradient stops top -> bottom, then [accent, shadow]
PALETTES = {
    "dusk":   ["#f5a35c", "#e2565b", "#7a3355", "#2b2240", "#ffd27a", "#161227"],
    "cyanic": ["#bfe6e4", "#5bc0be", "#1c7293", "#0b1f3a", "#e8f1f2", "#06101f"],
    "moss":   ["#e9edc9", "#a3c9a8", "#3e6b48", "#16241b", "#f2e9c9", "#0c1610"],
    "ember":  ["#ffd166", "#f2542d", "#a11d33", "#2a0e1a", "#fff0c2", "#170610"],
}


def _hex(c):
    return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))


def _rgb(t):
    return "#" + "".join(f"{max(0, min(255, round(v))):02x}" for v in t)


def _lerp(a, b, t):
    return tuple(a[i] + (b[i] - a[i]) * t for i in range(3))


def _grad(stops, t):
    t = max(0.0, min(1.0, t))
    n = len(stops) - 1
    seg = min(int(t * n), n - 1)
    return _lerp(stops[seg], stops[seg + 1], t * n - seg)


def value_noise(seed):
    def h(ix, iy):
        n = ix * 374761393 + iy * 668265263 + seed * 40503
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


def build(seed, palette, cols=16, rows=11):
    rng = random.Random(seed)
    noise = value_noise(seed)
    grad = [_hex(c) for c in PALETTES[palette][:4]]
    accent, shadow = _hex(PALETTES[palette][4]), _hex(PALETTES[palette][5])
    W, H = 1200, 800
    cw, ch = W / cols, H / rows

    # Sun focus in the upper band, off-center by seed.
    sx = rng.uniform(0.15, 0.5) * W
    sy = rng.uniform(0.12, 0.32) * H
    sun_r = rng.uniform(0.30, 0.42) * H

    pts = {}
    for r in range(rows + 1):
        for c in range(cols + 1):
            x, y = c * cw, r * ch
            if 0 < c < cols and 0 < r < rows:
                x += rng.uniform(-0.42, 0.42) * cw
                y += rng.uniform(-0.42, 0.42) * ch
            pts[(c, r)] = (x, y)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
        f'shape-rendering="geometricPrecision">',
        f"<title>Low-poly field, seed {seed}, palette {palette}</title>",
    ]

    def facet(a, b, c):
        cx = (a[0] + b[0] + c[0]) / 3
        cy = (a[1] + b[1] + c[1]) / 3
        base = _grad(grad, cy / H)
        # value noise -> plane shading; +/- ~14%
        shade = 0.86 + 0.28 * noise(cx / 190, cy / 190)
        col = tuple(v * shade for v in base)
        # sun glow: blend toward accent within radius, and lift shadow tint low
        dist = math.hypot(cx - sx, cy - sy)
        if dist < sun_r:
            col = _lerp(col, accent, (1 - dist / sun_r) ** 2 * 0.8)
        if cy > H * 0.82:
            col = _lerp(col, shadow, (cy / H - 0.82) / 0.18 * 0.5)
        p = f"{a[0]:.1f},{a[1]:.1f} {b[0]:.1f},{b[1]:.1f} {c[0]:.1f},{c[1]:.1f}"
        # Stroke each facet with its own fill: closes the sub-pixel seams
        # that float rounding leaves between triangles (they render as
        # stray hairlines otherwise), keeping the surface solid.
        rgb = _rgb(col)
        return f'<polygon points="{p}" fill="{rgb}" stroke="{rgb}" stroke-width="1"/>'

    for r in range(rows):
        for c in range(cols):
            p00, p10 = pts[(c, r)], pts[(c + 1, r)]
            p01, p11 = pts[(c, r + 1)], pts[(c + 1, r + 1)]
            # alternate the split diagonal so facets don't all lean one way
            if (c + r) % 2 == 0:
                parts.append(facet(p00, p10, p11))
                parts.append(facet(p00, p11, p01))
            else:
                parts.append(facet(p00, p10, p01))
                parts.append(facet(p10, p11, p01))

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--palette", choices=list(PALETTES), default="dusk")
    p.add_argument("--cols", type=int, default=16)
    p.add_argument("--rows", type=int, default=11)
    p.add_argument("--out", default=".sweep/lowpoly.svg")
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(a.seed, a.palette, a.cols, a.rows))
    print(a.out)
