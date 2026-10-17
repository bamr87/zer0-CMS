# Style: Isometric Tech

Technical exploded-view illustration in pixel-friendly 2:1 isometric projection (26.57deg): flat matte solids with three fixed face tones, one accent hue, parts separated along a dashed vertical assembly axis.

## Signature

- Every non-vertical edge has screen slope exactly +-1/2 — it steps 2 pixels across per 1 down; any other diagonal is off-style.
- Every solid shows exactly three faces (top, left, right) in three distinct tones of one material, and the light never moves: top lightest, left mid, right darkest, in every solid in the piece.
- Faces are matte flat fills: no gradients, no filters, no strokes on faces — the only strokes allowed are ink guide lines (center axis, leaders, dimensions).
- Exactly one accent hue per piece, on a single component, covering under ~15% of drawn area; the accent solid's three derived face tones count as one token.
- Parts separate along the vertical assembly axis only, threaded by a dashed ink center line; nothing explodes sideways.
- Every vertex lands on the iso grid: with unit u, all screen coordinates are integer multiples of u/2 — no anti-grid points, no sub-pixel decimals.
- Parallel edges stay parallel: no perspective convergence, no scaling of far parts.

## Geometry & grid

- Projection basis with unit u (8-16px works): one cell along +X projects to (+2u, +u), along +Y to (-2u, +u), and +Z is screen-up (0, -1) per pixel; formula: P(a,b,z) = (ox + (a-b)*2u, oy + (a+b)*u - z).
- Keep cell coordinates a,b in multiples of 0.5 so every projected point is an integer pixel.
- Solids are slabs and boxes drawn as three polygons — top diamond plus the two viewer-facing sides; back faces are never drawn.
- Surface details stay in-system: top-face details are 2:1 parallelograms, side-face details use only vertical and 2:1 edges; cylinders, if unavoidable, get 2:1-ratio ellipses.
- Explode gaps must actually reveal: raise each cover until the parts beneath clear its front silhouette — as a starting rule, gap >= 2.5x the height of the tallest component it reveals, then verify in the render (the first draft of the ref SVG failed exactly this).
- Canvas roughly 4:3 to 1:1, assembly centered on the vertical axis, side margins at least one cell width.

## Palette

- 6-8 tokens: 1 paper background, 1 ink (guides and recesses), 1-2 material families of exactly 3 face tones each (light/mid/dark), and 1 accent hue whose 3 derived face tones count as a single token — declare them once per the house rules, never sample per-element.
- Example (the ref SVG's palette): bg `#EEF1F5`, ink `#2B3542`, steel `#B9C3CE`/`#8C97A3`/`#5F6975`, slate `#DAE1E9`/`#ABB7C4`/`#7C8895`, accent orange `#FF8A4D`/`#E85D1A`/`#AC4110`.
- Face-tone ladders within a family should hold roughly constant lightness steps (about 12-18 L* apart) so the light reads as one source, not three paints.

## Do / Don't

- Do generate coordinates from a small projection helper script (house rule: anything with math gets a parametric generator) — never hand-type polygon points.
- Do give the accent to the one component the explode exists to show, and place it in a gap where it is actually visible.
- Do break symmetry with component placement (off-center chips, uneven port spacing), never by bending the grid.
- Do ground the piece with a single low-opacity ink diamond directly below the bottom part.
- Don't use 30deg "true" isometric (slope 0.577) or dimetric mixes — this style is strictly the 2:1 pixel projection.
- Don't outline faces; depth comes from the three tones and occlusion, not strokes.
- Don't let a lid or cover fully occlude the contents — an exploded view that hides its payload has failed.
- Don't reuse a face tone across roles (a right-face dark used as a top reads as a hole) or flip the light between solids.

## Critique add-ons

- Slope audit: zoom any diagonal edge in the render; if it is not stepping 2-across-1-down it is off-grid.
- Light audit: pick three solids at random; the tone order top > left > right must match across all three.
- Reveal audit: name what each explode gap is supposed to show, then confirm it is visible in front of the covering part's silhouette.
- Accent audit: count components carrying the accent hue; more than one means the piece has no focal point.
- Axis audit: the dashed center line must pass through the projected center of every layer — a layer off-axis reads as a mistake, not a design choice.

## Seed recipe

One cube, canonical face order and tones (u=16, light upper-left); scale up by scripting `P(a,b,z)` per the Geometry section rather than editing points by hand:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" role="img">
  <title>iso cube seed</title>
  <!-- u=16; +X=(32,16) +Y=(-32,16) +Z=(0,-32) -->
  <polygon fill="#DAE1E9" points="80,36 112,52 80,68 48,52"/>
  <polygon fill="#ABB7C4" points="48,52 80,68 80,100 48,84"/>
  <polygon fill="#7C8895" points="80,68 112,52 112,84 80,100"/>
</svg>
```

For a full piece, start from a slab function (top diamond + two front faces from footprint a0..a1, b0..b1 and z-bottom/z-top), stack base/board/cover with explode gaps, then run the house render-and-critique loop.

## Library references

- `tools/svg/library/styles/refs/isometric-tech.svg` — the founding exemplar for this style (exploded three-layer device; this card's palette and grid are taken from it).
- When `tools/svg/library/MANIFEST.json` exists, search tags: `isometric`, `iso-2to1`, `exploded`, `technical-diagram`, `flat-shaded`.
- No other in-repo exemplar exists yet; the icon sets under `tools/svg/library/external/` are flat 2D marks and are not references for this style, but `tools/svg/examples/` shows the parametric-generator shape to imitate.
