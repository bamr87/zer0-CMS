# The SVG framework, end to end

This is the whole flow — style decision, sourcing, drafting, the lint/render/look loop, population judging, the multi-agent forge, and finalize/promote — illustrated at every stage with the framework's own artifacts. Nothing here is a mock-up: the forge intermediates in [forge-run/](forge-run/) are the untouched outputs of a real `svg-forge` run (critic quotes below are verbatim from that run's transcripts), the files in [iterations/](iterations/) are byte-faithful reconstructions of the hand-loop versions as originally written, and everything in [variants/](variants/) regenerates deterministically from the commands at the bottom.

## The pipeline at a glance

```mermaid
flowchart LR
    B[Brief] --> S0[Pick a style card]
    S0 --> S1[Source exemplars\nMANIFEST tags + FreeSVG cache]
    S1 --> D[Draft\nhand / generator / adapt CC0]
    D --> L[svg-check\ndeterministic lint]
    L -- errors --> D
    L -- clean --> R[svg-render → PNG]
    R --> LOOK[LOOK at the render\nname the flaw]
    LOOK -- change ONE variable --> D
    LOOK -- survives critique --> F[Finalize: strict lint,\nsquint test, svgo check]
    F --> P[Promote: library/,\nMANIFEST entry, license]
```

The loop in the middle is the entire trick: a model writing SVG is writing with its eyes closed, so every write gets linted (machine-checkable problems never reach vision) and rasterized (composition problems get *seen*, named, and fixed one variable at a time). The [svg-art skill](../../.claude/skills/svg-art/SKILL.md) holds the critique vocabulary; the `PostToolUse` hook enforces the loop on every `.svg` write; the [`svg-forge` workflow](../../.claude/workflows/svg-forge.js) runs the same loop multi-agent.

## Output options

One framework, many kinds of output — every cell links a real committed file:

| Option | Example | Produced by |
| --- | --- | --- |
| <img src="variants/banner-hello-world.svg" width="150" alt="engine banner"> | Preview banner, 1536×1024 | The engine's `local` provider template (`banner-seed.py --slug hello-world`) |
| <img src="../samples/dawn-badge.svg" width="110" alt="badge"> | Flat-geometric badge | Hand loop, [style card](../../tools/svg/library/styles/flat-geometric.md) |
| <img src="../samples/forge-rocket-emblem.svg" width="110" alt="emblem"> | App-icon emblem | `svg-forge` multi-agent run (walkthrough below) |
| <img src="../samples/ridgeline.svg" width="150" alt="atmospheric banner"> | Atmospheric banner | Hand loop, [organic-atmos](../../tools/svg/library/styles/organic-atmos.md) |
| <img src="../samples/constellation.svg" width="110" alt="night scene"> | Night scene, `<defs>`+`<use>` motif | Hand loop (iteration story below) |
| <img src="../samples/flowfield-moss-5.svg" width="110" alt="generative"> | Generative field | `flowfield.py`, seed-swept |
| <img src="../samples/lsystem-tree-sakura-7.svg" width="100" alt="L-system tree"> | Recursive botanical | `lsystem.py` (turtle L-system, depth-shaded, 4 species × 4 palettes) |
| <img src="../samples/lowpoly-cyanic-5.svg" width="150" alt="low-poly field"> | Faceted low-poly field | `lowpoly.py` (jittered triangle grid, value-noise shading, sun glow) |
| <img src="../samples/mandala-jewel-11.svg" width="110" alt="mandala"> | Radial-symmetry mandala | `mandala.py` (N-fold concentric bands via `<use>` rotation) |
| <img src="../samples/starmap-5.svg" width="150" alt="composed scene"> | Composed scene | `starmap.py` — MIT library icons over a generated starfield + low-poly hills |
| <img src="../samples/invaders-cyanic-3.svg" width="140" alt="pixel shooter"> | Pixel-art game scene | `pixelkit.py` + `invaders.py` (procedural sprites) |
| <img src="../samples/pixel-quest-dusk-7.svg" width="150" alt="pixel platformer"> | Pixel-art platformer | `pixelkit.py` + `pixelquest.py` (ASCII sprites) |
| <img src="../../tools/svg/library/styles/refs/mono-line.svg" width="110" alt="mono-line icons"> | Mono-line icon sheet | [mono-line card](../../tools/svg/library/styles/mono-line.md) mini exemplar |
| <img src="../../tools/svg/library/styles/refs/engraved-hatch.svg" width="140" alt="engraving"> | Engraved plate shading | [engraved-hatch card](../../tools/svg/library/styles/engraved-hatch.md) mini exemplar |
| <img src="../../tools/svg/library/styles/refs/isometric-tech.svg" width="130" alt="isometric"> | Isometric exploded diagram | [isometric-tech card](../../tools/svg/library/styles/isometric-tech.md) mini exemplar |
| <img src="../../tools/svg/library/external/twemoji/twemoji-1f47e.svg" width="80" alt="twemoji"> <img src="../../tools/svg/library/external/wikimedia/wikimedia-fox-silhouette-nih-bioart.svg" width="90" alt="fox"> | Reused external art | License-vetted [library](../../tools/svg/library/README.md) + FreeSVG CC0 sourcing |

## Advanced generator gallery

Each generator is one algorithm with knobs; the same code re-skins across palettes and seeds, and every frame below was rendered and read before it was kept. The house rule holds — anything with repetition math (recursion, tiling, radial symmetry, triangulation) is a generator, never hand-authored path data.

**`lsystem.py`** — a recursive turtle over an L-system string, branches depth-shaded thick-dark-trunk → thin-bright-twig, blooms dropped at growth tips. One `tree` ruleset, three palettes:

| verdant | sakura | autumn |
| --- | --- | --- |
| <img src="../samples/lsystem-tree-verdant-7.svg" width="200"> | <img src="../samples/lsystem-tree-sakura-7.svg" width="200"> | <img src="../samples/lsystem-tree-autumn-4.svg" width="200"> |

**`lowpoly.py`** and **`mandala.py`** — a jittered Delaunay-ish triangle field with value-noise facet shading, and N-fold concentric motif bands:

| low-poly dusk | low-poly cyanic | mandala jewel | mandala ocean |
| --- | --- | --- | --- |
| <img src="../samples/lowpoly-dusk-5.svg" width="150"> | <img src="../samples/lowpoly-cyanic-5.svg" width="150"> | <img src="../samples/mandala-jewel-11.svg" width="130"> | <img src="../samples/mandala-ocean-11.svg" width="130"> |

**`starmap.py`** — the composition path: MIT-licensed library icons (lucide rocket, tabler planet, feather star/moon) inlined and recolored over a generated starfield, glowing moon, and low-poly hills. This is how "gather content and create" works when the API catalog or the local library already has the pieces:

<img src="../samples/starmap-5.svg" width="440" alt="composed star map">

## Stage 0 — pick a style

Every request starts by matching the brief against a [style card](../../tools/svg/library/styles/): each card is a set of *testable* constraints (grid, palette roles, stroke rules), style-specific critique checks, and a seed recipe. Each ships with a strict-lint mini exemplar:

| retro-pixel | flat-geometric | mono-line |
| --- | --- | --- |
| <img src="../../tools/svg/library/styles/refs/retro-pixel.svg" width="170"> | <img src="../../tools/svg/library/styles/refs/flat-geometric.svg" width="150"> | <img src="../../tools/svg/library/styles/refs/mono-line.svg" width="150"> |

| engraved-hatch | isometric-tech | organic-atmos |
| --- | --- | --- |
| <img src="../../tools/svg/library/styles/refs/engraved-hatch.svg" width="170"> | <img src="../../tools/svg/library/styles/refs/isometric-tech.svg" width="160"> | <img src="../../tools/svg/library/styles/refs/organic-atmos.svg" width="150"> |

## Stage 1 — source before you draw

The second question is always "does good art already exist?" — [`MANIFEST.json`](../../tools/svg/library/MANIFEST.json) is tag-searchable across 55+ entries (icons, emoji, illustrations, first-party pieces), and [`freesvg.py`](../../tools/svg/freesvg.py) reaches FreeSVG's CC0 catalog cache-first so repeat lookups cost zero API calls:

```bash
grep -l '"rocket"' tools/svg/library/MANIFEST.json          # tag search, no tooling needed
python3 tools/svg/freesvg.py search "rocket"                 # CC0 catalog, cached 7 days
python3 tools/svg/freesvg.py fetch 12345                     # into the immutable file cache
```

<img src="../../tools/svg/library/external/feather/feather-zap.svg" width="60" alt="feather zap"> <img src="../../tools/svg/library/external/lucide/lucide-rocket.svg" width="60" alt="lucide rocket"> <img src="../../tools/svg/library/external/twemoji/twemoji-1f680.svg" width="60" alt="twemoji rocket"> <img src="../../tools/svg/library/external/openmoji/openmoji-1F47E.svg" width="60" alt="openmoji alien"> <img src="../../tools/svg/library/external/wikimedia/wikimedia-jumping-fish.svg" width="90" alt="wikimedia fish">

Every external file carries provenance and license in the manifest; MIT/ISC/CC0 sources are safe to modify, share-alike sources are for as-is use ([the rules](../../tools/svg/library/README.md#licensing-rules)).

## Stage 2 — draft

Three entry points, in order of preference: adapt a sourced exemplar; run a parametric generator (house rule: anything with tiling, spirals, packing, or repetition gets a generator, never hand-authored path soup); or start from the style card's seed recipe.

```bash
python3 tools/svg/banner-seed.py --slug my-post --out draft.svg      # the engine's own template
python3 tools/svg/examples/flowfield.py --seed 5 --palette moss ...  # generative field
python3 tools/svg/examples/invaders.py --seed 3 ...                  # procedural pixel scene
python3 tools/svg/examples/pixelquest.py --seed 7 ...                # ASCII-sprite pixel scene
```

## Stage 3 — the deterministic gate

Everything checkable without eyes is checked without eyes. `svg-check.py` catches structural problems before any token is spent on vision — and the `PostToolUse` hook feeds failures straight back as exit-2 errors:

```text
$ python3 tools/svg/svg-check.py bad.svg
WARN  no <title> as first child (screen readers, and it shows as a tooltip)
WARN  missing role="img" on root
ERROR no viewBox on root — the art will not scale. Add viewBox="0 0 W H".
ERROR reference(s) to missing id(s): nope — gradient or clipPath will silently render as black/none
```

## Stage 4 — render and look

The hook rasterizes every clean `.svg` write and hands the PNG path back: *"Read the PNG now and critique the composition before making further edits."* The first grading axis is always the squint test — social cards and icon grids show art small, so the same file is judged at full size **and** at 120px:

| Full size | 120px squint test |
| --- | --- |
| <img src="../samples/ridgeline.svg" width="480"> | <img src="../samples/ridgeline.svg" width="120"> |

If the silhouette is mush at thumbnail size, nothing downstream matters.

## Stage 5 — name the flaw, change one variable

The hand loop, illustrated with the actual iterations. The rule: say what is wrong *out loud* before touching the file, then change one thing.

### Dawn badge: v1 → final

| v1 | final |
| --- | --- |
| <img src="iterations/dawn-badge-v1.svg" width="230"> | <img src="../samples/dawn-badge.svg" width="230"> |

Named flaws in v1, each visible in the render and invisible in the code: the scanline bars overhang the sun's edge and read as floating sticks (fix: clip them to the sun disc); the right hill overlaps the sun at 0.35 opacity leaving pink smudges (fix: draw hills *behind* the sun); the top half is dead ink (fix: three pixel-stars).

### Constellation: v1 → v2 → final

| v1 | v2 — the fix that backfired | final |
| --- | --- | --- |
| <img src="iterations/constellation-v1.svg" width="200"> | <img src="iterations/constellation-v2.svg" width="200"> | <img src="../samples/constellation.svg" width="200"> |

v1's moon glow was a flat translucent circle — flagged as a "conspicuous dark plate". v2 softened it to a radial gradient, which *exposed the real defect*: the crescent was faked with a background-colored stamp circle, and against the gradient it renders as an eclipse ball. The final version replaces the stamp with a true two-arc crescent path. That is the loop working as designed: each render names the next flaw, and some fixes only become visible after the previous one lands.

## Stage 6 — judge populations, not one lucky seed

For generative work a single output proves nothing. Sweep seeds, then pick:

| seed 2 — rejected | seed 5 — winner | seed 9 — rejected |
| --- | --- | --- |
| <img src="variants/flowfield-moss-2.svg" width="200"> | <img src="../samples/flowfield-moss-5.svg" width="200"> | <img src="variants/flowfield-moss-9.svg" width="200"> |

Verdicts from the session: seed 2 is even noise with no subject; seed 9 has two competing focal centers; seed 5 wins on its single feathered plume. The same discipline applies to palettes — a template change must improve the *population*:

| invaders: cyanic | magma | dusk |
| --- | --- | --- |
| <img src="../samples/invaders-cyanic-3.svg" width="200"> | <img src="../samples/invaders-magma-5.svg" width="200"> | <img src="variants/invaders-dusk-3.svg" width="200"> |

| pixel-quest: dusk | cyanic | moss |
| --- | --- | --- |
| <img src="../samples/pixel-quest-dusk-7.svg" width="200"> | <img src="variants/pixel-quest-cyanic-7.svg" width="200"> | <img src="variants/pixel-quest-moss-7.svg" width="200"> |

## Stage 7 — the multi-agent loop: a real `svg-forge` run

Brief: *"A space-explorer emblem: a small rocket arcing over a ringed planet, starfield behind, suitable as a 512×512 badge or app icon. Confident silhouette that survives 64px."* Three drafts in three styles, scored by the `svg-critic` agent (verbatim quotes, trimmed):

| draft-0 · flat-geometric · **5/10** | draft-1 · mono-line · **1/10** | draft-2 · retro-pixel · **4/10** |
| --- | --- | --- |
| <img src="forge-run/draft-0.svg" width="200"> | <img src="forge-run/draft-1.svg" width="200"> | <img src="forge-run/draft-2.svg" width="200"> |

- **draft-0:** "Ringed-planet occlusion trick reads cleanly … [but] the flame polygon plunges into the disc with zero negative-space gap, so it reads as fused, not arcing."
- **draft-1:** "The ring path slashes straight through the planet circle … reads as a 'blocked/muted' prohibition icon … the rocket is a disconnected paper-airplane in the top-left corner."
- **draft-2:** "The darker teal patches inside the planet body read as craters/continents, not a ring … the exhaust trail fuses directly into the planet's silhouette."

The winner refines one variable per round, and the critic re-scores each round (regressions would be discarded):

| round 1 · **5/10** | round 2 · **6/10** | shipped (after the hand fix) |
| --- | --- | --- |
| <img src="forge-run/round-1.svg" width="200"> | <img src="forge-run/round-2.svg" width="200"> | <img src="../samples/forge-rocket-emblem.svg" width="200"> |

- **round 1** applied the required change — moving the rocket up-left so starfield separates flame from planet — and the critic promptly named the next flaw: "the ring is two axis-aligned rects, not an ellipse … reads as a belt/sash."
- **round 2** replaced the bar with a tilted ellipse annulus that genuinely passes behind then in front of the disc via clip-paths: "nails Saturn-style occlusion … a real three-tier value structure."
- **the closing fix** came from the critic's final note — the ring bled into the icon-safe margin — applied by hand as one more one-variable edit (outer ring 184×56 → 150×45). The loop hands off cleanly between agents and humans because every critique ends with exactly one actionable change.

Score trajectory: 5 → 5 → 6 with three concrete defects retired; "stingy scoring" is calibrated so 8+ means shippable-as-is.

## Stage 8 — finalize, promote, provenance

Before anything ships: `svg-check.py --strict` must pass (title/role, size budget, precision); the squint test must hold; and `svgo` output is only accepted if it *still* passes strict — in the run above the finalize agent found svgo's default preset strips `role="img"`/`<title>` and correctly kept the unoptimized file. Externally sourced pieces enter git only through `freesvg.py promote`, which lints, copies into `library/external/freesvg/`, and appends a provenance-carrying manifest entry.

## Reproduce everything

```bash
# variants (deterministic)
python3 tools/svg/banner-seed.py --slug hello-world --out docs/showcase/variants/banner-hello-world.svg
python3 tools/svg/examples/flowfield.py --seed 2 --palette moss --out docs/showcase/variants/flowfield-moss-2.svg
python3 tools/svg/examples/flowfield.py --seed 9 --palette moss --out docs/showcase/variants/flowfield-moss-9.svg
python3 tools/svg/examples/pixelquest.py --seed 7 --palette cyanic --out docs/showcase/variants/pixel-quest-cyanic-7.svg
python3 tools/svg/examples/pixelquest.py --seed 7 --palette moss --out docs/showcase/variants/pixel-quest-moss-7.svg
python3 tools/svg/examples/invaders.py --seed 3 --palette dusk --out docs/showcase/variants/invaders-dusk-3.svg

# a fresh forge run (needs an agent session; intermediates land in .sweep/forge/)
#   Workflow svg-forge with args: {brief: "...", out: "out.svg", drafts: 3, rounds: 2}
```

The forge-run intermediates are one-of-a-kind run artifacts (agent output is not seeded); they are committed here precisely because they cannot be regenerated.
