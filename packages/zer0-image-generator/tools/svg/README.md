# tools/svg — the SVG authoring loop

Wiring for Claude Code (adapted from the svg-art-kit) so agents working on this repo's SVG code can make artwork that is actually looked at.

## The problem this solves

A model writing SVG is writing with its eyes closed. It emits coordinates, you open the file, and you become the feedback loop — describing in prose what the model could have seen for itself. Every fix costs a round trip through you.

Close the loop and the model critiques its own output. That is the whole design.

```
Write .svg ──▶ PostToolUse hook ──▶ lint (deterministic)
                     │                   │
                     │                   └─ fail ─▶ exit 2, reason back to Claude
                     │
                     └─ rasterize ──▶ PNG path back to Claude ──▶ Claude Reads it
```

This repo's *product* already closes this loop for end users: `preview_generator.py` sanitizes model SVG, rasterizes it, and has Claude vision-review the render. What lives here is the same loop for the *development* side — iterating on `render_local_svg`, the sanitizer, fixtures, or any hand-authored SVG in the repo.

## What each piece does, and why it is that piece

| File | Primitive | Why not something else |
| --- | --- | --- |
| `.claude/rules/svg.md` | Rule, path-scoped | `paths:` frontmatter means these constraints only enter context when an SVG (or the engine) is actually open. In CLAUDE.md they would be tax on every session. |
| `.claude/skills/svg-art/SKILL.md` | Skill | Art direction is reference material needed sometimes, loaded on demand. |
| `.claude/agents/svg-critic.md` | Subagent | Twenty render-and-look cycles will bury your main context in images. The subagent absorbs them and returns 200 words. |
| `.claude/settings.json` | Hook | "Remember to render after editing" in a prompt is a request. A `PostToolUse` hook is a guarantee. |
| `svg-check.py` | — | Everything checkable without eyes should be checked without eyes. Vision is for composition. |
| `banner-seed.py` | Generator adapter | Sweeps judge the engine's real `local` template (sanitized, exact banner geometry), not a lookalike. |
| `examples/flowfield.py` | Reference generator | The canonical shape of "generator with knobs" — tune numbers, never hand-author bezier soup. |
| `examples/lsystem.py` | Botanical generator | Recursive turtle over an L-system string; depth-shaded branches and bloom tips, four rulesets (bush/fern/tree/weed) × four palettes. |
| `examples/lowpoly.py` | Faceted-field generator | Jittered triangle grid with vertical-gradient + value-noise facet shading and an off-center sun glow; seams closed by per-facet stroke. |
| `examples/mandala.py` | Radial-symmetry generator | N-fold concentric motif bands via `<defs>`+`<use>` rotation, one phase-broken ring; dense mandalas stay a few KB. |
| `examples/starmap.py` | Composition demo | Inlines MIT library icons (recolored, scale-invariant stroke) over a generated starfield and low-poly hills — the "reuse gathered content" path. |
| `pixelkit.py` | Style library | The retro pixel style, codified: integer cell grid, `crispEdges`, ASCII-map sprites, 6-token engine-kin palettes, run-length-merged rects, optional CRT veil. |
| `library/` | Example + style library | Curated exemplar SVGs with tracked provenance and licenses, plus style cards (testable constraints + seed recipes + strict-lint mini refs). See [library/README.md](library/README.md). |
| `freesvg.py` | On-demand sourcing | FreeSVG.org API client with a tiered local cache (token / searches 7d / metadata 30d / immutable files) so repeat lookups cost zero API calls; `promote` graduates keepers into the library with provenance. |
| `.claude/workflows/svg-forge.js` | Saved workflow | The loop, multi-agent: style-diverse parallel drafts → `svg-critic` scoring → winner refined one variable per round → strict-lint finalize. |
| `examples/invaders.py` | Pixel generator | Procedural fixed-shooter scene; aliens are random half-grids mirrored (`hmirror`) — bilateral symmetry makes blobs read as creatures. |
| `examples/pixelquest.py` | Pixel generator | Side-scroller vignette from hand-designed ASCII sprites with seeded layout. |

## Rasterizer

`svg-render.sh` picks the first available of resvg, rsvg-convert, inkscape, cairosvg, headless Chromium, or `npx @resvg/resvg-js-cli`. Install one:

```bash
cargo install resvg          # fastest, most predictable
brew install librsvg         # rsvg-convert
pip install cairosvg
```

ImageMagick is deliberately not in the render chain: it shells out to a delegate that may not exist, and fails confusingly when it doesn't. (The engine's own runtime chain in `preview_generator.py` is separate and does include it, plus the vendored Playwright helper.)

## Use

```bash
python3 tools/svg/banner-seed.py --seed 7 --out .sweep/banner.svg   # one banner variant
python3 tools/svg/banner-seed.py --slug my-post --out banner.svg    # a specific post's banner
bash tools/svg/svg-sweep.sh tools/svg/banner-seed.py 12             # contact sheet of 12 seeds (needs ImageMagick montage)
python3 tools/svg/svg-check.py banner.svg --strict                  # deterministic lint
bash tools/svg/svg-render.sh banner.svg                             # SVG → .preview/banner.png
python3 tools/svg/examples/invaders.py --seed 3 --out .sweep/i.svg  # pixel-art scene
python3 tools/svg/examples/pixelquest.py --seed 7 --out .sweep/q.svg
```

In a session:

> Rework the terrain layers in render_local_svg. Sweep banner-seed before and after, read both contact sheets, and critique against the svg-art skill. The change must improve the population, not one lucky seed.

Finished pieces produced with this loop live in [docs/samples/](../../docs/samples/README.md) — each entry notes what the render-and-look cycle caught that the code alone did not. The [showcase walkthrough](../../docs/showcase/README.md) illustrates the whole pipeline stage by stage with the intermediate images each piece iterated through, including a real multi-agent forge run.

## Known sharp edges

- resvg, Chromium, and Safari disagree on filter primitives and blend modes. Render against whatever will actually consume the file.
- `<text>` depends on fonts present at render time. Convert to paths before shipping.
- The bounds check in `svg-check.py` samples absolute path commands only. It catches stray control points, not every geometry bug.
- A contact sheet beats N separate reads on token cost by roughly N-to-1, but loses fine detail. Sweep to shortlist, then render finalists full size.
- `.preview/` and `.sweep/` are scratch output, git-ignored.
