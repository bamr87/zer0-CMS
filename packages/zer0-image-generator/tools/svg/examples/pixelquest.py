#!/usr/bin/env python3
"""
pixelquest.py — side-scroller vignette in the pixelkit style: a knight,
a slime, coins, a crate, and a goal flag under a blocky sunset.

Hand-designed sprites, seeded layout: the seed drives terrain, star and
coin placement, and where the cast stands.

    python3 tools/svg/examples/pixelquest.py --seed 7 --out .sweep/quest.svg
"""
import argparse
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), os.pardir))
from pixelkit import Canvas, PALETTES

HERO = [
    "...cc...",
    "..cccc..",
    ".hhhhhh.",
    ".hfefeh.",
    ".hffffh.",
    "..aaaa..",
    ".gaaaag.",
    ".gaaaag.",
    "..a..a..",
    "..b..b..",
    "..b..b..",
]

SLIME = [
    "..ssss..",
    ".ssssss.",
    "ssssssss",
    "ss.ss.ss",
    "ssssssss",
]

COIN = [
    ".##.",
    "#oo#",
    "#oo#",
    ".##.",
]

CRATE = [
    "######",
    "#o##o#",
    "######",
    "######",
    "#o##o#",
    "######",
]

FLAG = [
    "pff.",
    "pfff",
    "pff.",
    "p...",
    "p...",
    "p...",
    "p...",
    "p...",
    "p...",
    "p...",
]


def build(seed: int, palette: str) -> str:
    rng = random.Random(seed)
    pal = PALETTES[palette]
    c = Canvas(64, 40, px=16, bg=pal[0])
    ground_top = 34

    # Stars, thinning toward the horizon
    for _ in range(60):
        col, row = rng.randrange(64), rng.randrange(24)
        if rng.random() < (1.0 - row / 24):
            c.set(col, row, pal[1] if rng.random() < 0.7 else pal[2])

    # Blocky setting sun
    sun_x = 40 + rng.randrange(12)
    c.disc(sun_x, 9, 5.2, pal[4])
    c.disc(sun_x, 9, 3.4, pal[5])

    # Stepped far hills, then near hills (random walk, engine-style)
    for base, color in ((26, pal[1]), (30, pal[2])):
        col, level = 0, base - rng.randrange(3)
        while col < 64:
            width = 3 + rng.randrange(5)
            c.fill(col, level, width, ground_top - level, color)
            col += width
            level = max(base - 6, min(base, level + rng.choice((-2, -1, 1, 2))))

    # Brick ground with staggered mortar and a lit cap row
    c.fill(0, ground_top, 64, 6, pal[2])
    for row in range(ground_top, 40):
        for col in range(64):
            if row % 2 == 1 and (col + 3 * (row // 2)) % 6 == 0:
                c.set(col, row, pal[1])
    c.fill(0, ground_top, 64, 1, pal[4])

    # The cast
    hero_col = 10 + rng.randrange(6)
    c.blit(HERO, {"c": pal[3], "h": pal[5], "f": pal[4], "e": pal[0],
                  "a": pal[5], "g": pal[5], "b": pal[3]}, hero_col, ground_top - 11)
    c.blit(SLIME, {"s": pal[3]}, 38 + rng.randrange(6), ground_top - 5)
    crate_col = 27
    c.blit(CRATE, {"#": pal[4], "o": pal[1]}, crate_col, ground_top - 6)
    c.blit(FLAG, {"p": pal[5], "f": pal[3]}, 58, ground_top - 10)
    # Coin arc over the crate, not confetti
    for dx, dy in ((-6, 10), (0, 12), (6, 10)):
        c.blit(COIN, {"#": pal[4], "o": pal[5]}, crate_col + 1 + dx, ground_top - dy - 4)

    return c.to_svg(f"Pixel quest, seed {seed}, palette {palette}", crt=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", default=".sweep/quest.svg")
    p.add_argument("--palette", choices=list(PALETTES), default="dusk")
    a = p.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        f.write(build(a.seed, a.palette))
    print(a.out)
