# Style: Mono-line

Single-weight stroke icons in the feather/lucide family: one 2px round-capped line of `currentColor` on a 24px integer grid, no fills, legible at 16px.

## Signature

- Exactly one stroke width in the file: `stroke-width="2"` declared once on the root and never overridden — grepping for a second `stroke-width` value must return nothing.
- `fill="none"` on the root and no element sets a fill; every shape is an empty outline that survives on any background.
- One ink: `stroke="currentColor"` on the root and zero hex/rgb color literals anywhere in the file.
- `stroke-linecap="round"` and `stroke-linejoin="round"` on the root; no butt caps, no miter spikes at any zoom.
- All coordinates land on integers or halves of the 24-grid; anything finer (max 2 decimals) must be a deliberate optical correction you can name.
- Stroke centerlines stay inside the 1..23 box so the 2px stroke never clips flat against the viewBox edge.
- Where strokes pass near each other without joining, keep a gap of at least one stroke width (2px) so counters stay open at 16px.
- No gradients, filters, masks, opacity, or `<text>`; primitives (`circle`, `rect`, `line`) before `path`, and paths use the fewest commands that draw the idea.

## Geometry & grid

- Canvas is `viewBox="0 0 24 24"` per icon; a sheet of N icons is N translated 24x24 tiles on a shared gutter (see the ref, which uses 24px tiles with an 8px gutter on a 60x60 canvas).
- Live area is effectively 22x22 (centerlines 1..23); big enclosing shapes use r=10 or a 20x20 rect, medium features r=3..5, details 2..4px long.
- Default corner radius for rects is 2 (`rx="2"`); arc joins in paths use radius 2-4 so curvature reads consistent across the family.
- Translate tiles into place but never scale them — `stroke-width` scales with `transform`, which silently breaks the single-weight signature (or opt into `vector-effect="non-scaling-stroke"` on purpose, per house rules).
- Budget roughly 2-3 ideas per tile (mug + handle + steam); past that, drop detail rather than shrinking features below the 2px-gap floor.

## Palette

- One token: `ink`, carried entirely by `currentColor` so the embedding page themes the icon via CSS `color`; the icon file itself names no colors.
- Example palette: ink `#1f2937` on light backgrounds (`#ffffff`), ink `#e5e7eb` on dark (`#111827`) — set on the consumer, never in the SVG.
- If a design demands a second accent color, that is a wrapper-level decision (a `<g>` with `color` overridden by the consumer), not a second literal in the icon.

## Do / Don't

- Do build from primitives first: `<circle>`, `<rect rx="2">`, `<line>`, then short paths for what remains.
- Do connect related strokes into one continuous line where the subject allows (a two-peak ridge as one polyline beats two overlapping triangles).
- Do check every icon at 16px; the 24-grid and 2px stroke are engineered for exactly that floor.
- Do keep family consistency: same optical weight, same corner radius, same edge margin across every icon in a set.
- Don't fill anything — no solid dots bigger than a round cap, no filled badges or silhouettes.
- Don't mix stroke widths for hierarchy; hierarchy comes from size and placement of shapes.
- Don't hardcode a stroke color; `currentColor` is the theming contract consumers rely on.
- Don't let strokes cross or nearly-touch incidentally — every intersection is either a deliberate join or separated by a full stroke width.

## Critique add-ons

- Weight parity: squint at the whole set — any tile reading darker or lighter than its neighbors has too much or too little ink, not a style variation.
- 16px collapse test: render at 16px and check every counter (enclosed white space); gaps under ~2px in grid units mush shut.
- Terminal audit: zoom to each line ending and junction — one flat cap or miter spike anywhere breaks the family signature.
- Edge clipping: verify no centerline sits at 0 or 24, where the 2px stroke would render half-clipped and flat.
- Off-grid census: list every coordinate that is not an integer or half and demand an optical justification for each (diagonal balance, circle tangency); unexplained decimals are drift.

## Seed recipe

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
     stroke="currentColor" stroke-width="2" stroke-linecap="round"
     stroke-linejoin="round" role="img">
  <title>Icon name</title>
  <!-- centerlines inside 1..23; integers/halves; primitives before paths -->
  <circle cx="12" cy="12" r="10"/>
  <path d="M8 12h8"/>
</svg>
```

Then run the house loop (svg-check strict, render, read the PNG) plus the 16px collapse test above.

## Library references

- Ref for this card: `tools/svg/library/styles/refs/mono-line.svg` — a four-tile sheet showing tile layout, gap discipline, and the connected-ridge idiom.
- Exemplars: `tools/svg/library/external/feather/` (`feather-sun.svg` for ray gaps and edge-touching centerlines, `feather-compass.svg` for primitive-plus-polygon economy) and `tools/svg/library/external/lucide/` (`lucide-rocket.svg` for curve-heavy paths with optical corrections).
- MANIFEST: search `tools/svg/library/MANIFEST.json` (if present) for tags like `mono-line`, `icon`, `stroke`, `feather`, `lucide`.
