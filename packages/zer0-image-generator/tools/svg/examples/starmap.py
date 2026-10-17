#!/usr/bin/env python3
"""
starmap.py — compose a scene from LIBRARY assets + generated elements.

This is the "reuse gathered content" path: it inlines MIT-licensed
line icons from tools/svg/library/external/ (lucide, feather, tabler)
as the cast, over a generated seeded starfield and a low-poly hill
silhouette. Icons are stroke="currentColor", so each is recolored and
scaled on placement with a counter-scaled stroke width to keep line
weight constant regardless of size.

    python3 tools/svg/examples/starmap.py --seed 5 --out .sweep/starmap.svg

Only MIT-licensed icons are used, so the composite carries no
share-alike obligation (see tools/svg/library/external/LICENSES.md).
"""
import argparse
import math
import os
import random

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
LIB = os.path.join(ROOT, "tools", "svg", "library", "external")

PALETTE = {
    "sky_top": "#0a1330", "sky_bot": "#1b2a4a", "haze": "#2a3f66",
    "hill_far": "#213a63", "hill_near": "#0c1c38",
    "star": "#e8f1f2", "moon": "#f2e9c9", "moon_glow": "#8bbfd6",
    "rocket": "#f7e8d3", "planet": "#5bc0be", "accent": "#f2a541",
}


def inner(rel):
    """Strip the outer <svg> wrapper from a library icon, keep its marks."""
    with open(os.path.join(LIB, rel), encoding="utf-8") as f:
        t = f.read()
    t = t[t.index(">", t.index("<svg")) + 1:]
    return t[:t.rindex("</svg>")].strip()


def place(frag, cx, cy, s, color, sw=2.4, op=1.0):
    """Place a 24x24 icon centered at (cx,cy), scaled, stroke width held
    constant on screen by counter-scaling it against the group scale."""
    return (f'<g transform="translate({cx - 12*s:.1f} {cy - 12*s:.1f}) scale({s:.3f})" '
            f'fill="none" stroke="{color}" stroke-width="{sw / s:.3f}" '
            f'stroke-linecap="round" stroke-linejoin="round" opacity="{op}">{frag}</g>')


def build(seed):
    rng = random.Random(seed)
    W, H = 1200, 800
    horizon = int(H * 0.72)
    p = PALETTE
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img">',
        "<title>Star map: a rocket among planets over low-poly hills "
        "(composed from MIT library icons)</title>",
        "<defs>",
        f'<linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{p["sky_top"]}"/>'
        f'<stop offset="1" stop-color="{p["sky_bot"]}"/></linearGradient>',
        f'<radialGradient id="glow"><stop offset="0" stop-color="{p["moon_glow"]}" stop-opacity="0.5"/>'
        f'<stop offset="1" stop-color="{p["moon_glow"]}" stop-opacity="0"/></radialGradient>',
        "</defs>",
        f'<rect width="{W}" height="{H}" fill="url(#sky)"/>',
    ]

    # Seeded starfield, thinning toward the horizon
    for _ in range(150):
        x, y = rng.randrange(W), rng.randrange(horizon)
        if rng.random() > (1 - y / horizon) * 0.9:
            continue
        r = rng.choice([0.6, 0.9, 1.2, 1.8])
        out.append(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{p["star"]}" '
                   f'opacity="{rng.uniform(0.3, 0.95):.2f}"/>')

    # Moon with glow, upper right
    mx, my = int(W * 0.78), int(H * 0.24)
    out.append(f'<circle cx="{mx}" cy="{my}" r="150" fill="url(#glow)"/>')
    out.append(f'<circle cx="{mx}" cy="{my}" r="62" fill="{p["moon"]}"/>')
    out.append(f'<circle cx="{mx+22}" cy="{my-14}" r="54" fill="{p["sky_top"]}" opacity="0.55"/>')

    # Low-poly hill silhouettes: two ridges triangulated into facets
    def ridge(base, amp, color, step):
        cols = list(range(-40, W + 80, step))
        top = [base - rng.randrange(amp) for _ in cols]
        # smooth once
        top = [(top[max(0, i-1)] + top[i] + top[min(len(top)-1, i+1)]) // 3
               for i in range(len(top))]
        tris = []
        for i in range(len(cols) - 1):
            x0, x1 = cols[i], cols[i + 1]
            y0, y1 = top[i], top[i + 1]
            shade = 0.68 + 0.42 * rng.random()  # wider spread so facets read
            c = "#" + "".join(f"{max(0,min(255,int(int(color[j:j+2],16)*shade))):02x}"
                              for j in (1, 3, 5))
            tris.append(f'<polygon points="{x0},{y0} {x1},{y1} {x1},{H} {x0},{H}" '
                        f'fill="{c}" stroke="{c}" stroke-width="1"/>')
        return "\n".join(tris)

    out.append(ridge(horizon, 70, p["hill_far"], 90))
    out.append(ridge(horizon + 60, 46, p["hill_near"], 70))

    # Cast: gathered MIT icons, recolored and scaled
    rocket = inner("lucide/lucide-rocket.svg")
    planet = inner("tabler/tabler-planet.svg")
    star = inner("feather/feather-star.svg")
    moon_i = inner("feather/feather-moon.svg")

    out.append(place(planet, int(W * 0.2), int(H * 0.3), 5.2, p["planet"], sw=2.6))
    out.append(place(rocket, int(W * 0.52), int(H * 0.44), 9.0, p["rocket"], sw=2.2))
    out.append(place(star, int(W * 0.36), int(H * 0.16), 2.0, p["accent"], sw=2.4))
    out.append(place(star, int(W * 0.64), int(H * 0.6), 1.5, p["accent"], sw=2.4, op=0.8))
    out.append(place(star, int(W * 0.88), int(H * 0.52), 1.8, p["accent"], sw=2.4, op=0.9))
    out.append(place(moon_i, int(W * 0.1), int(H * 0.12), 2.4, p["moon_glow"], sw=2.2))

    out.append("</svg>")
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=5)
    ap.add_argument("--out", default=".sweep/starmap.svg")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(a.seed))
    print(a.out)
