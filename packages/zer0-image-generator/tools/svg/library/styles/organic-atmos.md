# Style: Organic Atmos

Layered translucent organic shapes build atmospheric depth: opacity stacking instead of element count, soft gradients that dissolve rather than end, art-directed density clusters, and exactly one deliberate symmetry break.

## Signature

- Depth comes from 3-5 stacked bands of ONE hue whose opacities step monotonically toward the viewer (e.g. 0.35 → 0.55 → 0.80 → 1.0); a mid band more opaque than a nearer band is a defect.
- Every non-background shape carries opacity below 1.0 except the foreground anchor and the single break element — count the full-opacity elements; more than two fails.
- At least one gradient fades to `stop-opacity="0"` on at least one end, so mist or glow dissolves into the layer beneath; no gradient may terminate at a visible rectangle edge.
- Density is art-directed: the densest quadrant of the canvas holds at least 3x the element count of the emptiest quadrant — uniform scatter is disqualifying.
- Exactly one deliberate symmetry break: a single element that violates the ruling rhythm (leans the other way, sits off-axis, or owns full opacity) and has sole ownership of one palette token.
- Element count stays under ~60; richness must come from translucency and overlap, not repetition — if deleting 30% of elements changes the read, the piece is over-counted.
- Contours are irregular: band tops and strand curves vary vertex spacing and amplitude — no two adjacent peaks at the same height, no perfect geometric primitives except one celestial anchor (sun/moon/star).
- All fills and strokes draw from a 3-5 token palette declared once in `<defs>` or at the top of the file; any hex value appearing only once (outside the break element) is a smell.

## Geometry & grid

- Ship at the banner frame `viewBox="0 0 1536 1024"` (`sanitize_svg` forces it); square 800x800 is the study format — both appear in the exemplars.
- Divide vertically into horizontal register bands: sky owns the top 40-55%, 2-4 translucent mid bands stack below, and a near-black ground silhouette anchors the bottom 5-15%.
- Adjacent depth bands overlap 15-25% vertically so occlusion carries most of the depth; the gradient veils only soften the seams.
- Place the celestial anchor and the break element near rule-of-thirds intersections, never centered, and never both on the same vertical third.
- Bleed every band 20px past the viewBox on left, right, and bottom so no edge seam is ever visible.

## Palette

- 4 tokens, 5 with an accent: **ground** (near-black, the only fully-opaque silhouette), **body** (the mid organic hue, reused at 3+ opacities — it does the layering), **haze** (desaturated pale kin of body, for mist and sky), **light** (near-white, for the celestial anchor and highlights), optional **accent** (owned exclusively by the symmetry break).
- The moss family from the repo exemplars: `#16211b` ground, `#3e6b48` body, `#a3c9a8` haze, `#e9edc9` light, `#f4f6e4` accent.
- A second working family (used by this card's ref): `#101c22` ground, `#2e5e63` body, `#8fb8ae` haze, `#eef3e9` light, `#f2e8c9` accent.

## Do / Don't

- **Do** reuse one hue at three or more opacities before adding a new hex — ridgeline.svg builds all four mountain ranges from a single `#3e6b48`.
- **Do** feather every mist veil with `stop-opacity="0"` at both ends so it reads as air, not as a tinted rectangle.
- **Do** cluster: pack strands or points near the focal region and let the far corner go nearly empty, like constellation.svg's star falloff.
- **Do** give the darkest fully-opaque silhouette the bottom edge so the eye has a floor.
- **Don't** reach for filters (`feGaussianBlur`, `feTurbulence`) to get softness — gradients plus opacity render identically in resvg, Chromium, and Safari; filters do not.
- **Don't** distribute elements uniformly; even spacing is the signature of an algorithm nobody art-directed.
- **Don't** stack more than 5 discrete depth bands — past that they merge into a single tier of mud and the value structure collapses.
- **Don't** add a second symmetry break; two exceptions read as noise, one reads as intent.

## Critique add-ons

- **Opacity ladder**: read the band opacities off the file — do they step strictly toward the viewer? Any inversion flattens the depth illusion.
- **Dissolve check**: trace each gradient edge in the render — if you can point at where a veil rectangle ends, it needs `stop-opacity="0"` feathering.
- **Density map**: quarter the render; the densest quadrant should carry at least 3x the emptiest — near-equal quadrants mean re-cluster, don't add elements.
- **Break audit**: count rhythm violations — zero reads as a test pattern, one is the style, two or more is noise.
- **Hue economy**: count distinct hex values in fills/strokes; more than 5 means opacity stopped doing the work and the palette is leaking.

## Seed recipe

Start from this skeleton (study format), then art-direct: roughen the band tops, cluster the strands, place the break.

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 800 800" role="img">
  <title>Organic atmos seed</title>
  <defs>
    <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#eef3e9"/>
      <stop offset="1" stop-color="#8fb8ae"/>
    </linearGradient>
    <linearGradient id="mist" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#eef3e9" stop-opacity="0"/>
      <stop offset="0.5" stop-color="#eef3e9" stop-opacity="0.25"/>
      <stop offset="1" stop-color="#eef3e9" stop-opacity="0"/>
    </linearGradient>
  </defs>
  <rect width="800" height="800" fill="url(#sky)"/>
  <circle cx="265" cy="300" r="58" fill="#eef3e9"/>
  <!-- one hue, opacity ladder: far to near -->
  <polygon points="-20,500 210,455 470,490 700,450 820,480 820,800 -20,800" fill="#2e5e63" opacity="0.32"/>
  <rect y="445" width="800" height="90" fill="url(#mist)"/>
  <polygon points="-20,610 260,555 540,600 820,560 820,800 -20,800" fill="#2e5e63" opacity="0.55"/>
  <rect y="555" width="800" height="85" fill="url(#mist)"/>
  <polygon points="-20,780 300,745 640,775 820,750 820,800 -20,800" fill="#101c22"/>
  <!-- clustered strands here; then ONE break element owning the accent token -->
</svg>
```

There is no dedicated generator for this style yet; for flow-field-like strand work, adapt the parametric approach in `tools/svg/examples/` rather than hand-writing curves (house rule: math gets a generator).

## Library references

- `docs/samples/ridgeline.svg` — the canonical banded atmosphere: four ranges from one hue, mist veils, birds as the break.
- `docs/samples/constellation.svg` — density gradient and opacity falloff on `<use>` stars, crescent moon as the off-axis break.
- `docs/samples/flowfield-moss-5.svg` — opacity-over-count strokes (0.25-0.80) with art-directed convergence instead of uniform fill.
- `tools/svg/library/styles/refs/organic-atmos.svg` — this card's mini exemplar.
- MANIFEST tags (`tools/svg/library/MANIFEST.json`, may not exist yet): search `organic`, `atmospheric`, `layered`, `translucent`, `landscape`, `moss`.
