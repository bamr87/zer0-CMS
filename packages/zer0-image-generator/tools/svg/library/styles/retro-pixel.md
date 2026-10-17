# Style: Retro Pixel

8-bit sprite scenes on a hard integer grid — six flat tokens, mirrored creatures, run-length rects, and a CRT veil, exactly as `tools/svg/pixelkit.py` implements them.

## Signature

- Integer grid: every rect's `x`/`y`/`width`/`height` is a whole multiple of the cell size `px`; nothing lives off-grid, so nothing can be half a pixel wrong.
- `shape-rendering="crispEdges"` on the root; no renderer anti-aliases the art into mush.
- Exactly 6 palette tokens per piece — `[bg, shadow, low-mid, mid, accent, highlight]` — plus `#000` for the CRT veil; no other fill value appears anywhere.
- Flat fills only: zero gradients, filters, strokes, or curved paths; circles are cell-quantized discs (`Canvas.disc`).
- Horizontal same-color runs merge into single `<rect>`s, so a 64x48 scene stays a few KB instead of thousands of one-cell rects.
- Sprites are bilaterally symmetric (`hmirror`), with exactly one deliberate break somewhere in the scene — and the break is the subject.
- The protagonist is the sole user of one token (usually highlight): grep that hex and every match must belong to the protagonist.
- CRT veil: 1-unit-high black scanline rects every 6 units at 0.10 opacity, plus one darker full-width bar at top and bottom — the only opacity in the file.

## Geometry & grid

- The canvas is `cols x rows` integer cells drawn at `px` units per cell; `viewBox="0 0 cols*px rows*px"` and no bare `width`/`height`.
- House scene grid is 64x48 at `px=12` (768x576); mini refs go 32x24; for kinship with the engine's 1536x1024 banner frame use 96x64 at `px=16`.
- Sprites are ASCII maps (`.` and space transparent, other chars mapped to tokens) blitted whole; scale only by integer factors (2x = each sprite cell becomes a 2x2 fill), never fractional.
- The protagonist spans roughly a quarter to a third of canvas width and stands on the ground; the ground occupies the bottom 2-4 rows as a lit line over a dark mass.
- Density gradient, not even spread: starfield probability decays top-to-bottom, scene weight sits low, and the middle band stays open for the subject.
- Random creatures: fill a half-grid at ~0.55 density, `hmirror` it, and reject any sprite whose mass falls outside 35-75% of the half-grid — that band is what makes blobs read as bodies.

## Palette

Six tokens with fixed roles, declared once — `pixelkit.PALETTES` ships four rows (`dusk`, `cyanic`, `moss`, `magma`) in the same shape as the engine's `RETRO_PALETTES`, so pieces read as kin to the local banners.

| Role | Index | Job in the scene | Example (`cyanic`) |
| --- | --- | --- | --- |
| bg | `pal[0]` | frame fill, punched-out sprite eyes | `#0b132b` |
| shadow | `pal[1]` | dim stars, ground mass, far props | `#1c2541` |
| low-mid | `pal[2]` | bright stars, ground line, bunkers, HUD | `#1c7293` |
| mid | `pal[3]` | secondary objects: moon, rear ranks, ship trim | `#5bc0be` |
| accent | `pal[4]` | the one event — explosion, beacon, shot origin | `#9fd8d6` |
| highlight | `pal[5]` | the protagonist, and the protagonist only | `#e8f1f2` |

## Do / Don't

- Do build with `pixelkit.Canvas` + ASCII sprites and `blit`; an unmapped sprite char raises `KeyError` on purpose — keep typos failing loudly.
- Do mirror random half-grids with `hmirror` and re-roll until the mass check passes; symmetry is what turns noise into creatures.
- Do break symmetry exactly once — an explosion, a raised beacon, a missing limb — and give that break the accent token so it becomes the focal point.
- Do keep the whole scene a few KB: trust run-length merging, and shrink the grid before shrinking the idea.
- Don't hand-write rect coordinates or path data; every scene comes from a seeded generator script (see `tools/svg/examples/`).
- Don't shade with gradients, partial opacity, or filters — depth comes from token value steps and overlap, and the only opacity allowed is the veil's.
- Don't let any other element borrow the protagonist's token, and don't exceed the 6-token budget "just for one detail".
- Don't place anything off-grid; a half-cell offset or non-integer `px` reads as a bug, and `crispEdges` will not hide it.

## Critique add-ons

- Grid audit: divide a sampled rect's `x`/`y`/`width`/`height` by `px` — any non-integer result fails the piece outright.
- Token audit: count distinct `fill` values; anything beyond the 6 palette tokens plus veil `#000` is palette drift.
- Creature read: at 64px, do the mirrored blobs read as bodies with limbs and antennae, or as glyph noise? Re-roll the seed, not the style.
- Symmetry-break count: exactly one break in the scene; zero reads as a test pattern, two or more reads as damage.
- Veil weight: scanlines should read as texture at full size and vanish at thumbnail; a muddy thumbnail means the veil opacity or bar height is too heavy.

## Seed recipe

The repo implements the style — start from the shipped generator and sweep seeds rather than hand-authoring:

```bash
python3 tools/svg/examples/invaders.py --seed 3 --palette cyanic --out .sweep/invaders.svg
bash tools/svg/svg-render.sh .sweep/invaders.svg 600   # then READ the PNG before editing anything
```

For a new scene, the minimal skeleton is a short script on top of pixelkit (this is how `refs/retro-pixel.svg` was made):

```python
import sys; sys.path.insert(0, "tools/svg")
from pixelkit import Canvas, PALETTES, hmirror

pal = PALETTES["dusk"]                     # [bg, shadow, low-mid, mid, accent, highlight]
c = Canvas(32, 24, px=12, bg=pal[0])       # integer cell grid, viewBox 384x288
c.fill(0, 20, 32, 1, pal[2])               # ground line
c.fill(0, 21, 32, 3, pal[1])               # ground mass
c.disc(24, 5, 3.2, pal[3])                 # blocky moon
body = hmirror(["..#.", ".##.", "####", "#.#."])   # bilateral creature, 7x4
c.blit(body, {"#": pal[5]}, 13, 16)        # protagonist owns highlight, feet on ground
c.set(25, 13, pal[4])                      # accent spark: the one symmetry break
open("out.svg", "w").write(c.to_svg("Sentinel", crt=True))  # CRT veil on
```

## Library references

- `tools/svg/pixelkit.py` — the implementation: `Canvas`, `PALETTES`, `hmirror`, run-length `to_svg`, CRT veil.
- `tools/svg/examples/invaders.py` and `tools/svg/examples/pixelquest.py` — full seeded scene generators in this style.
- `docs/samples/invaders-cyanic-3.svg`, `docs/samples/invaders-magma-5.svg`, `docs/samples/pixel-quest-dusk-7.svg` — rendered exemplars at scene scale.
- `tools/svg/library/styles/refs/retro-pixel.svg` — this card's mini exemplar (generated, dusk palette, seed 1).
- MANIFEST: search `tools/svg/library/MANIFEST.json` (once it exists) for tags like `retro-pixel`, `pixel`, `8-bit`, `sprite`, `crt`.
