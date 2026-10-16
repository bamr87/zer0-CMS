#!/usr/bin/env python3
"""
mandala.py — radial-symmetry mandala generator. Stdlib only.

Concentric rings of a motif repeated with N-fold rotational symmetry.
Each ring's motif, radius, count, and palette role is seeded; one ring
is deliberately offset in phase so the piece isn't a perfect test
pattern (house rule: break symmetry in one place). Motifs are defined
once in <defs> and instanced with <use> + rotate, so a dense mandala
stays a few KB.

    python3 tools/svg/examples/mandala.py --seed 7 --palette jewel --out .sweep/mandala.svg
"""
import argparse
import math
import os
import random

# [bg, ring-a, ring-b, accent, highlight]
PALETTES = {
    "jewel":  ["#120a24", "#3d2c8d", "#00a8a8", "#f25f5c", "#ffe066"],
    "solar":  ["#1a1005", "#7a3b12", "#e08a1e", "#f2c14e", "#fff3d6"],
    "ocean":  ["#04121f", "#0b3a5b", "#1c88a8", "#5bc0be", "#e8f1f2"],
    "rose":   ["#1a0f16", "#5a2244", "#a83e6f", "#e58fb0", "#f7e0e8"],
}


def motif_def(mid, kind, h, w, color, stroke):
    """Motif centered at the local origin, long axis radial (±y)."""
    sw = 'stroke="{}" stroke-width="1.5"'.format(stroke) if stroke != "none" else ""
    if kind == "petal":
        return f'<ellipse id="{mid}" rx="{w:.1f}" ry="{h:.1f}" fill="{color}" {sw} opacity="0.92"/>'
    if kind == "diamond":
        return (f'<path id="{mid}" d="M0 {-h:.1f} L {w:.1f} 0 L 0 {h:.1f} L {-w:.1f} 0 Z" '
                f'fill="{color}" {sw} opacity="0.92"/>')
    if kind == "dot":
        return f'<circle id="{mid}" r="{max(3.0, w*0.8):.1f}" fill="{color}" {sw}/>'
    # spoke: a short radial tick, decorative between bands
    return (f'<path id="{mid}" d="M0 {-h:.1f} L 0 {h:.1f}" stroke="{color}" '
            f'stroke-width="{max(1.5, w*0.35):.1f}" stroke-linecap="round"/>')


def build(seed, palette):
    rng = random.Random(seed)
    pal = PALETTES[palette]
    S = 800
    cx = cy = S / 2
    defs, layers = [], []

    fold = rng.choice([12, 16, 18, 20, 24])
    n = rng.randint(5, 7)
    r_max = 356
    gap = r_max / (n + 1)
    radii = [gap * (i + 1) for i in range(n)]  # even bands, no dead space
    quirk = rng.randrange(n)  # the one band that breaks phase

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {S} {S}" role="img">',
        f"<title>Mandala, seed {seed}, {fold}-fold, palette {palette}</title>",
        f'<rect width="{S}" height="{S}" fill="{pal[0]}"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r_max+22}" fill="none" stroke="{pal[1]}" stroke-width="3"/>',
        f'<circle cx="{cx}" cy="{cy}" r="{r_max+12}" fill="none" stroke="{pal[3]}" stroke-width="1.5" opacity="0.7"/>',
    ]

    kinds = ["petal", "diamond", "dot", "spoke"]
    for i, r in enumerate(radii):
        kind = rng.choice(kinds)
        count = fold if i % 2 == 0 else fold * 2  # denser alternating bands
        color = pal[(i % 3) + 1]
        stroke = pal[4] if rng.random() < 0.6 else "none"
        h = gap * 0.5 * (0.95 if kind != "dot" else 0.5)
        w = gap * (0.3 if kind in ("petal", "diamond") else 0.22)
        mid = f"m{i}"
        defs.append(motif_def(mid, kind, h, w, color, stroke))
        phase = (180.0 / count) if i == quirk else 0.0
        uses = [f'<g transform="translate({cx} {cy})">']
        for k in range(count):
            ang = phase + k * 360.0 / count
            uses.append(f'<use href="#{mid}" transform="rotate({ang:.2f}) translate(0 {-r:.1f})"/>')
        uses.append("</g>")
        layers.append("\n".join(uses))

    # Center rosette: a small ring of petals, then concentric discs
    defs.append(motif_def("mc", "petal", gap * 0.55, gap * 0.22, pal[3], pal[4]))
    center = [f'<g transform="translate({cx} {cy})">']
    for k in range(fold):
        center.append(f'<use href="#mc" transform="rotate({k*360.0/fold:.2f}) translate(0 {-gap*0.6:.1f})"/>')
    center.append("</g>")
    layers.append("\n".join(center))
    layers.append(f'<circle cx="{cx}" cy="{cy}" r="{gap*0.42:.1f}" fill="{pal[3]}"/>')
    layers.append(f'<circle cx="{cx}" cy="{cy}" r="{gap*0.24:.1f}" fill="{pal[4]}"/>')
    layers.append(f'<circle cx="{cx}" cy="{cy}" r="{gap*0.09:.1f}" fill="{pal[0]}"/>')

    parts.append("<defs>\n" + "\n".join(defs) + "\n</defs>")
    parts.extend(layers)
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--palette", choices=list(PALETTES), default="jewel")
    p.add_argument("--out", default=".sweep/mandala.svg")
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(a.seed, a.palette))
    print(a.out)
