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

- `render_local_svg` must stay deterministic: same ARTICLE → byte-identical banner, in Python and Ruby alike. All randomness goes through the seeded LCG (`banner_lcg`); never call `random` or clock/time functions there. Trig comes from the Taylor-built lookup tables, not `math`/`Math` — libm rounds the last bit differently across platforms and the Ruby port is pinned byte-for-byte.
- Banner art is CONTENT-AWARE: `banner_theme_for` picks the composition and palette from the page's section/tags/title/body, and `banner_seed_for` hashes that content. Changing the keyword table, the field weights, or a composition re-skins existing banners on regeneration — do it deliberately.
- Compositions are authored AT 1536×1024. One written for another aspect gets squashed by the forced `viewBox`, not rejected, so there is no error to catch — check the render.
- The legacy `seed_for` / `palette_for` / `composition_for` trio is still shared contract: `composition_for` feeds the AI providers' prose art brief, and is unrelated to the local compositions above.

## Workflow

Anything with math in it — tiling, spirals, packing, noise, repetition — gets a parametric generator (see `tools/svg/banner-seed.py` and `tools/svg/examples/`), not hand-authored path data. Then tune the knobs and re-run. Hand-writing bezier control points is how drift starts.
