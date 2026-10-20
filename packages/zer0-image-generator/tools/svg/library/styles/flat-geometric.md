# Style: Flat Geometric

Poster/badge flatland: 3-5 solid inks, hard-edged overlap for depth, stepped silhouettes snapped to a strict grid — no strokes, no gradients, no filters, ever.

## Signature

- Zero strokes: searching the file for `stroke` returns nothing (or only `stroke="none"`); outlines and frames are concentric filled shapes, never stroked ones.
- Zero gradients, filters, or patterns: the file contains no `<linearGradient>`, `<radialGradient>`, `<filter>`, or `<pattern>` element.
- Depth is stacking order only: a shape reads as "in front" because it is painted later and hard-crops what is behind it — never via shadow, glow, or blur.
- Every ramp is quantized: any transition (sky glow, slope, reflection) is 2-4 discrete grid-snapped bands or stair-steps, never a smooth blend.
- Palette is 3-5 declared tokens; every fill is a token verbatim or a token at one of at most 3 quantized opacity stops file-wide (e.g. 0.15 / 0.3 / 0.6).
- Primitive vocabulary: `rect`, `circle`, and `polygon` with ≤16 vertices do 90%+ of the work; `path` appears only where no primitive can.
- One dominant silhouette that survives 64px, built from roughly a dozen major shapes or fewer.
- Exactly one deliberate symmetry/rhythm break (a pennant, an off-center notch): zero reads as a test pattern, two or more reads as noise.

## Geometry & grid

- Badge canvas is square (512×512 canonical, as in `dawn-badge.svg`); banner work composes for the engine's fixed `viewBox="0 0 1536 1024"` per `.claude/rules/svg.md`.
- Pick a module (8px on 512; 16-32px on the banner frame) and snap every x/y/width/height and polygon vertex to it; integer coordinates only.
- Stair-steps rise and run in 1-4 modules; smaller steps read as anti-aliasing artifacts at thumbnail size, not as deliberate stairs.
- Put the horizon and other major divisions on simple fractions of the frame (1/2, 2/3, 11/16) and size the focal disc as a simple fraction of frame width (~1/3).
- Frame rings are two nested filled rounded rects (outer rx 48, inner rx ≈ outer minus ring width), never a stroked rect.
- Minimum feature size is one module: nothing thinner than 8px on a 512 canvas.

## Palette

- 3-5 tokens with fixed roles: one ink (darkest, owns the largest area), one or two mids (landforms, structural bands), one light (paper/moon/highlight), one accent (hottest hue, smallest area, exactly one job).
- Tints come only from a token at a quantized opacity stop over ink, capped at 3 distinct stops per file — more and the palette dissolves into a simulated gradient.
- Example palette (engine ember family, as used by `dawn-badge.svg`): ink `#1a1423`, ember `#f24236`, gold `#f5a623`, cream `#f7e8d3`.
- Value check: desaturated, the tokens must sort into the skill's three tiers (ground, mid, accent) with clear separation between adjacent tiers.

## Do / Don't

Do:

- Paint back-to-front and let solid foreground shapes decapitate what is behind them — `dawn-badge.svg` sinks its sun behind a solid water rect instead of masking it.
- Quantize atmosphere into a handful of stacked bands: dawn-badge's sky glow is three wide rects at stepped opacities, not a gradient.
- Clip texture to the shape that owns it (dawn-badge clips its scanlines to the sun disc) so interior detail can never break the silhouette.
- Give the accent token exactly one job — focal marker, frame, or signal — and make it the smallest patch of color in the piece.

Don't:

- Don't stroke anything: dawn-badge's 4px gold stroked frame is its one off-style choice — a ring of two filled rects renders identically and keeps the rule absolute.
- Don't stack many opacity values to fake haze: dawn-badge's ladder of ~10 distinct opacities drifts toward gradient-simulation; hold the line at 3 stops.
- Don't add detail smaller than one grid module — it dies at 64px and muddies the silhouette that is the style's entire payload.
- Don't mint a sixth color by overlapping translucent mids; check what each blend resolves to and re-snap anything unnameable to a token.

## Critique add-ons

- Stroke sweep: grep the file for `stroke` — any hit besides `none` is an automatic fail before aesthetics are even discussed.
- Opacity census: list every distinct opacity value; more than 3 stops means the flat palette is dissolving into a fake gradient (dawn-badge's ten-value ladder is the cautionary tale).
- Stair legibility at 120px: stepped edges must still read as deliberate stairs at the squint-test render, not as jaggies.
- Occlusion honesty: every overlap must resolve to a hard edge between two nameable tokens; a soft or muddy boundary means opacity is doing depth's job.
- Flat-flood silhouette test: imagine the whole piece flooded to one ink — if the outline is not distinctive on its own, no palette will rescue it.

## Seed recipe

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" role="img">
  <title>Flat-geometric badge seed</title>
  <!-- tokens: ink #14212b | mid #2f7d6d | light #f2e9d8 | accent #e4573f -->
  <defs><clipPath id="field"><rect x="8" y="8" width="496" height="496" rx="42"/></clipPath></defs>
  <rect x="0" y="0" width="512" height="512" rx="48" fill="#f2e9d8"/>            <!-- frame ring: outer fill... -->
  <rect x="8" y="8" width="496" height="496" rx="42" fill="#14212b"/>            <!-- ...inner fill. No stroke. -->
  <g clip-path="url(#field)">
    <rect x="8" y="288" width="496" height="64" fill="#2f7d6d" opacity="0.15"/>  <!-- quantized glow band 1 -->
    <rect x="8" y="320" width="496" height="32" fill="#2f7d6d" opacity="0.3"/>   <!-- quantized glow band 2 -->
    <circle cx="320" cy="192" r="88" fill="#f2e9d8"/>                            <!-- focal disc -->
    <polygon points="144,352 144,320 192,320 192,256 224,256 224,192 256,192 256,160 288,160 288,192 320,192 320,256 352,256 352,320 400,320 400,352" fill="#2f7d6d"/>
    <rect x="8" y="352" width="496" height="152" fill="#14212b"/>                <!-- ground re-asserts ink -->
    <polygon points="276,112 308,124 276,136" fill="#e4573f"/>                   <!-- accent: one job, one place -->
  </g>
</svg>
```

Grow it on the 8px module: add one far ridge in a second mid, echo bars below the horizon at descending opacity stops, and pole the accent to the summit — then run the loop (`svg-check.py --strict`, render, read, name the flaw, change one variable).

## Library references

- `docs/samples/dawn-badge.svg` — the repo exemplar: on-style stepped hills, hard sun/water occlusion, disc-clipped texture, 4-token ember palette; off-style only in its stroked frame and its ~10-value opacity ladder (see `docs/samples/README.md` for what the loop caught).
- `tools/svg/library/styles/refs/flat-geometric.svg` — this card's mini exemplar: stepped peaks, occluded moon, two-rect ring frame, exactly 3 opacity stops, zero strokes.
- `tools/svg/library/MANIFEST.json` — when the manifest exists, search tags like `flat`, `geometric`, `badge`, `poster`, `stepped`, `solid-fill`, `hard-edge`.
- `tools/svg/library/external/` — fill-variant glyphs (e.g. `bootstrap/bootstrap-star-fill.svg`) drop into this style unmodified; outline sets (feather, lucide) do not.
