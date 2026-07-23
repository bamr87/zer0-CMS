---
description: SVG authoring constraints, loaded only when SVG files are in play
paths:
  - "**/*.svg"
  - "**/*svg*.py"
  - "**/*svg*.js"
  - "**/preview_generator.py"
---

# SVG house rules

- Always set `viewBox`. Never set a bare `width`/`height` without one.
- `role="img"` on root, `<title>` as the first child. Non-negotiable — `svg-check.py` warns on it and the engine's own template must pass.
- No `<image>`, no `data:` raster payloads, no network `href`s. The engine's `sanitize_svg` strips or rejects all of these anyway (plus `<script>`, `foreignObject`, event handlers, non-local `url()`, and any DOCTYPE/ENTITY) — write SVG that survives it untouched.
- Banner geometry is fixed: `sanitize_svg` forces `viewBox="0 0 1536 1024"` (`SVG_WIDTH`×`SVG_HEIGHT`). Compose for that frame; anything else gets squashed into it.
- Round path coordinates to 0-2 decimals. Sub-pixel precision is invisible and triples file size.
- Reuse via `<defs>` + `<use>`. If a motif appears more than three times it is a `<symbol>`.
- `stroke` scales with `transform` unless you set `vector-effect="non-scaling-stroke"`. Decide which you want on purpose.
- `<text>` will not survive on a machine without your font. Convert to paths for anything shipped.
- Filters (`feGaussianBlur`, `feTurbulence`) render differently in resvg vs Chromium vs Safari. Pick the target engine and validate against it.
- Prefer `currentColor` for single-accent marks so CSS can theme them.

## Engine-specific

- `render_local_svg` must stay deterministic: same slug → byte-identical banner. All randomness goes through the seeded LCG (`nxt`); never call `random` or clock/time functions there.
- The seed → palette/composition scheme is shared contract (`seed_for`, `palette_for`, `composition_for`). Changing it re-skins every existing local banner on regeneration — do it deliberately.

## Workflow

Anything with math in it — tiling, spirals, packing, noise, repetition — gets a parametric generator (see `tools/svg/banner-seed.py` and `tools/svg/examples/`), not hand-authored path data. Then tune the knobs and re-run. Hand-writing bezier control points is how drift starts.
