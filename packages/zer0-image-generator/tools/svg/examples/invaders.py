#!/usr/bin/env python3
"""
invaders.py — procedural fixed-shooter scene in the pixelkit style.

Each wave's alien species are *generated*: random cells in a half-grid,
mirrored (hmirror) — bilateral symmetry is what makes random blobs read
as creatures. One alien is mid-explosion; the symmetry break is the
subject.

    python3 tools/svg/examples/invaders.py --seed 3 --out .sweep/invaders.svg
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
from pixelkit import Canvas, PALETTES, hmirror

SHIP = [
    ".....#.....",
    "....l#l....",
    ".l.l###l.l.",
    "###########",
    "l#l#l#l#l#l",
]

BUNKER = [
    ".########.",
    "##########",
    "##########",
    "###....###",
    "##......##",
]

MINI_SHIP = [
    "..#..",
    ".###.",
    "#####",
]

BOOM = [
    "#..#.#..#",
    ".#..#..#.",
    "..#####..",
    ".#..#..#.",
    "#..#.#..#",
]


def alien(rng: random.Random, half_w: int = 6, height: int = 8) -> list:
    """Random half-grid, mirrored. Reject sprites too sparse or too dense
    to read as a creature; force antennae-ish top corners off."""
    while True:
        rows = []
        for r in range(height):
            row = "".join("#" if rng.random() < 0.55 else "." for _ in range(half_w))
            rows.append(row)
        mass = sum(row.count("#") for row in rows)
        if 0.35 * half_w * height <= mass <= 0.75 * half_w * height:
            return hmirror(rows)


def build(seed: int, palette: str) -> str:
    rng = random.Random(seed)
    pal = PALETTES[palette]
    c = Canvas(64, 48, px=12, bg=pal[0])

    # Starfield, sparse and uneven — heavier toward the top
    for _ in range(70):
        col, row = rng.randrange(64), rng.randrange(44)
        if rng.random() < (1.0 - row / 44) * 0.8:
            c.set(col, row, pal[1] if rng.random() < 0.6 else pal[2])

    # Three ranks of aliens, one species per rank, 5 across
    species = [alien(rng) for _ in range(3)]
    rank_color = [pal[5], pal[4], pal[3]]
    hit = (rng.randrange(3), rng.randrange(5))  # one alien mid-explosion
    for rank in range(3):
        for i in range(5):
            col, row = 1 + i * 13, 5 + rank * 10
            if (rank, i) == hit:
                c.blit(BOOM, {"#": pal[4]}, col + 1, row + 1)
            else:
                c.blit(species[rank], {"#": rank_color[rank]}, col, row)

    # A shot on its way up from the player
    shot_col = 1 + rng.randrange(5) * 13 + 5
    c.fill(shot_col, 33, 1, 3, pal[5])

    # Bunkers, ship, ground, lives
    for i in range(3):
        c.blit(BUNKER, {"#": pal[2]}, 5 + i * 22, 36)
    c.blit(SHIP, {"#": pal[4], "l": pal[3]}, 26, 41)
    c.fill(0, 46, 64, 1, pal[2])
    for i in range(3):
        c.blit(MINI_SHIP, {"#": pal[2]}, 2 + i * 7, 1)

    return c.to_svg(f"Invader wave, seed {seed}, palette {palette}", crt=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default=".sweep/invaders.svg")
    p.add_argument("--palette", choices=list(PALETTES), default="cyanic")
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(a.seed, a.palette))
    print(a.out)
