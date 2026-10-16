# Sample SVG artwork

Pieces produced with the [tools/svg authoring loop](../../tools/svg/README.md): each was written, linted (`svg-check.py --strict`), rasterized, *read*, critiqued against the `svg-art` skill's vocabulary, and refined — the render drove every edit.

For the full pipeline illustrated stage by stage — including the intermediate versions each piece went through and a real multi-agent forge run with its draft/refine artifacts — see the [showcase walkthrough](../showcase/README.md).

| File | Kind | What the loop caught |
| --- | --- | --- |
| `dawn-badge.svg` | Hand-authored badge mark, 512×512, engine ember palette | Scanline bars overhung the sun's edge (now clipped to the disk); hills smudged pink over the sun (now occluded behind it); dead ink in the top half (broken by three pixel-stars). |
| `ridgeline.svg` | Hand-authored banner, 1536×1024, moss palette | Flat mist rects rendered as hard banding stripes across the peaks — replaced with gradient-fade bands. |
| `constellation.svg` | Hand-authored night field, 800×800, `<defs>`+`<use>` star motif | The crescent faked with a background-colored stamp circle became a visible "eclipse ball" once a glow was added — replaced with a true two-arc crescent path. |
| `flowfield-moss-5.svg` | Generative, picked from `tools/svg/examples/flowfield.py` | Judged as a population: seeds 2/5/9 rendered side by side; seed 2 was even noise, seed 9 had two competing centers, seed 5 won on its single focal plume. |
| `invaders-cyanic-3.svg` | Pixel-art fixed shooter, `examples/invaders.py` (pixelkit) | The render exposed two layout bugs: the fifth alien column clipped off-canvas, and the player ship drawn through the middle bunker. |
| `invaders-magma-5.svg` | Palette variant of the same generator | Kept because the magma ranks descend in value (gold → ember → maroon), giving the wave the tiered structure the cyanic version gets from brightness. |
| `pixel-quest-dusk-7.svg` | Pixel-art side-scroller, `examples/pixelquest.py` (pixelkit) | The loop caught an invisible crate (body matched the bricks, leaving four floating rivets) and a snowman-shaped hero; the `svg-critic` agent then flagged the hero/slime hue collision — the knight is now the scene's only cream figure. |
| `forge-rocket-emblem.svg` | Space-explorer badge, produced by the `svg-forge` workflow | Three style-diverse drafts (flat-geometric beat retro-pixel and mono-line), two critic-driven refine rounds, strict-lint finalize; the critic's last note — ring bleeding into the icon-safe margin — was applied by hand as the closing one-variable fix. |

## Advanced generators

A second wave of generators, each iterated the same way — build, render, name the flaw, change one variable:

| File | Kind | What the loop caught |
| --- | --- | --- |
| `lsystem-tree-verdant-7.svg` | L-system flowering tree, `examples/lsystem.py` | First pass used the `bush` ruleset, which grows lopsided-right with dead space bottom-left; switching to the symmetric `tree` ruleset gave an upright, centered canopy. The `bush` render was also 270KB — over budget — so iterations dropped from 5 to 4 (tree to 3) with a longer step, holding the fill while landing at 54KB. |
| `lsystem-tree-sakura-7.svg` | Palette variant (cherry blossom) | Same generator, `sakura` palette — kept to show the depth-shaded trunk→branch→leaf ramp and bloom accent re-skin cleanly per palette without touching geometry. |
| `lsystem-tree-autumn-4.svg` | Palette variant (autumn gold) | Seed 4 chosen over 7 for this palette because its branch structure reads most tree-like; the population-judging habit applied to a single generator. |
| `lowpoly-dusk-5.svg` | Faceted low-poly gradient field, `examples/lowpoly.py` | The first render had hairline seams between triangles from float rounding — an artifact that renders as stray light/black lines. Fixed by stroking each facet with its own fill so the surface stays solid. |
| `lowpoly-cyanic-5.svg` | Palette variant | Same seed, `cyanic` palette; the vertical gradient + value-noise facet shading + off-center sun glow re-tone as a cool aurora. |
| `mandala-jewel-11.svg` | Radial-symmetry mandala, `examples/mandala.py` | The first design placed every motif emanating from the center, leaving a dead ring of empty space and dominant over-long spokes. Reworked so motifs sit on concentric bands at even radii that fill the frame, with spokes demoted to a short decorative tick ring. |
| `mandala-ocean-11.svg` | Palette variant | Same seed, `ocean` palette, to show the 3-role band coloring (ring-a / ring-b / accent) re-skin. |
| `starmap-5.svg` | Composed scene, `examples/starmap.py` | Reuses **gathered content**: MIT-licensed line icons (lucide rocket, tabler planet, feather star/moon) inlined and recolored over a generated seeded starfield, glowing moon, and low-poly hills. First render's hills were too dark to read as faceted — widened the shade spread and lifted the far ridge so the low-poly tie-in shows. Only MIT icons are used, so the composite carries no share-alike obligation. |

Regenerate any generative piece from its name, e.g.:

```bash
python3 tools/svg/examples/lsystem.py  --seed 7 --species tree --palette verdant --iters 3 --out docs/samples/lsystem-tree-verdant-7.svg
python3 tools/svg/examples/lowpoly.py  --seed 5 --palette dusk   --out docs/samples/lowpoly-dusk-5.svg
python3 tools/svg/examples/mandala.py  --seed 11 --palette jewel --out docs/samples/mandala-jewel-11.svg
python3 tools/svg/examples/starmap.py  --seed 5 --out docs/samples/starmap-5.svg
python3 tools/svg/examples/flowfield.py --seed 5 --palette moss --out docs/samples/flowfield-moss-5.svg
```

All pieces pass `svg-check.py --strict` (viewBox, `role="img"` + `<title>`, local refs only, size budget) and hold their silhouette at a 120px thumbnail — the squint test social cards impose.
