#!/usr/bin/env python3
"""
lsystem.py — L-system botanical generator. Stdlib only.

Turtle-interprets an expanded L-system string into branch segments plus
leaf/bloom markers, then shades by branch depth (thick dark trunk ->
thin bright twigs) and drops foliage at growth tips. Multiple rulesets
give distinct species; a small per-turn angle jitter (seeded) keeps the
plant organic instead of mechanically self-similar.

    python3 tools/svg/examples/lsystem.py --seed 7 --species bush --out .sweep/plant.svg

The point is the *shape* of the work: repetition with math goes through
a generator (house rule), you tune the ruleset/angle/iters knobs and
re-run — you never hand-author a thousand bezier twigs.
"""
import argparse
import math
import os
import random

# [bg, trunk, branch, leaf, bloom, sky-glow]
PALETTES = {
    "verdant": ["#0e1a12", "#4a3327", "#3e6b48", "#8bbf6f", "#f2e9c9", "#1b3326"],
    "autumn":  ["#1a1410", "#4a2f20", "#8a4b2f", "#d98324", "#f2c14e", "#2a1d14"],
    "sakura":  ["#171320", "#3d2b3d", "#5a4466", "#c98bb9", "#f7d6e6", "#241b2e"],
    "frost":   ["#0b1420", "#2a3b4a", "#3e6b7a", "#8bbfd6", "#e8f1f2", "#152532"],
}

# axiom, rules, base angle (deg), iterations, step length
RULESETS = {
    "bush": ("X", {"X": "F+[[X]-X]-F[-FX]+X", "F": "FF"}, 22.5, 4, 13.0),
    "fern": ("X", {"X": "F-[[X]+X]+F[+FX]-X", "F": "FF"}, 20.0, 4, 13.0),
    "tree": ("F", {"F": "FF+[+F-F-F]-[-F+F+F]"}, 25.0, 4, 9.0),
    "weed": ("F", {"F": "F[+F]F[-F][F]"}, 22.0, 4, 8.0),
}


def expand(axiom, rules, iters):
    s = axiom
    for _ in range(iters):
        s = "".join(rules.get(c, c) for c in s)
    return s


def interpret(s, angle, step, jitter, rng):
    x, y, a = 0.0, 0.0, -90.0
    stack, segs, tips = [], [], []
    for c in s:
        if c == "F":
            na = a + rng.uniform(-jitter, jitter)
            nx = x + step * math.cos(math.radians(na))
            ny = y + step * math.sin(math.radians(na))
            segs.append((x, y, nx, ny, len(stack)))
            x, y, a = nx, ny, na
        elif c == "+":
            a += angle + rng.uniform(-jitter, jitter)
        elif c == "-":
            a -= angle + rng.uniform(-jitter, jitter)
        elif c == "[":
            stack.append((x, y, a))
        elif c == "]":
            tips.append((x, y, len(stack)))
            x, y, a = stack.pop()
        elif c == "X":
            tips.append((x, y, len(stack)))
    return segs, tips


def build(seed, species, palette, iters_override=None):
    rng = random.Random(seed)
    axiom, rules, angle, iters, step = RULESETS[species]
    if iters_override:
        iters = iters_override
    pal = PALETTES[palette]
    jitter = 3.0 + rng.random() * 5.0
    segs, tips = interpret(expand(axiom, rules, iters), angle, step, jitter, rng)
    if not segs:
        segs = [(0, 0, 0, -10, 0)]

    xs = [p for s in segs for p in (s[0], s[2])]
    ys = [p for s in segs for p in (s[1], s[3])]
    minx, maxx, miny, maxy = min(xs), max(xs), min(ys), max(ys)
    W, H, M = 900, 1100, 90
    span = max(maxx - minx, 1e-6), max(maxy - miny, 1e-6)
    scale = min((W - 2 * M) / span[0], (H - 2 * M) / span[1])
    ox = (W - span[0] * scale) / 2 - minx * scale
    oy = H - M - maxy * scale  # base sits near the bottom margin

    def tx(x): return round(ox + x * scale, 1)
    def ty(y): return round(oy + y * scale, 1)

    maxd = max((s[4] for s in segs), default=1)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" role="img" '
        f'stroke-linecap="round">',
        f"<title>L-system {species}, seed {seed}, palette {palette}</title>",
        f'<rect width="{W}" height="{H}" fill="{pal[0]}"/>',
        f'<ellipse cx="{W//2}" cy="{int(H*0.34)}" rx="{W//2}" ry="{int(H*0.34)}" '
        f'fill="{pal[5]}" opacity="0.6"/>',
        f'<ellipse cx="{W//2}" cy="{H-40}" rx="{int(W*0.42)}" ry="34" '
        f'fill="{pal[1]}" opacity="0.5"/>',
    ]

    # Branches back-to-front: deep twigs first would occlude the trunk, so
    # draw trunk-first (shallow depth) — shallow segments are the trunk.
    for x1, y1, x2, y2, d in sorted(segs, key=lambda s: s[4]):
        t = d / maxd
        color = pal[1] if t < 0.28 else (pal[2] if t < 0.62 else pal[3])
        w = round(max(0.6, 11 * (1 - t) ** 1.7), 2)
        parts.append(
            f'<line x1="{tx(x1)}" y1="{ty(y1)}" x2="{tx(x2)}" y2="{ty(y2)}" '
            f'stroke="{color}" stroke-width="{w}"/>'
        )

    # Foliage at tips: most leaves, a seeded fraction blooms in the accent.
    for x, y, d in tips:
        if d < 2:
            continue
        r = round(rng.uniform(3.5, 7.0) * min(scale, 1.0) * 3, 1)
        if rng.random() < 0.16:
            parts.append(f'<circle cx="{tx(x)}" cy="{ty(y)}" r="{r*1.1:.1f}" '
                         f'fill="{pal[4]}" opacity="0.95"/>')
        else:
            parts.append(f'<circle cx="{tx(x)}" cy="{ty(y)}" r="{r:.1f}" '
                         f'fill="{pal[3]}" opacity="0.75"/>')

    parts.append("</svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--species", choices=list(RULESETS), default="bush")
    p.add_argument("--palette", choices=list(PALETTES), default="verdant")
    p.add_argument("--iters", type=int, default=None, help="override ruleset iterations")
    p.add_argument("--out", default=".sweep/lsystem.svg")
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(a.seed, a.species, a.palette, a.iters))
    print(a.out)
