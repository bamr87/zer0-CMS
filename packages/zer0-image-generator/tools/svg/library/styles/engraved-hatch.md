# Style: Engraved Hatch

Engraving / woodcut plate shading: all tone built from parallel stroke banks that follow form, cross-hatch reserved for the deepest shadow, a single ink on a paper tone, and line weight doing the edge hierarchy.

## Signature

- Exactly two color tokens — one ink, one paper; every stroke is the ink token at opacity 1, with no gradients, no grays, no alpha.
- All tone is line work: the only filled element is the paper background rect; zero shapes carry a tonal fill.
- Hatch lines travel in banks that follow form — on a curved surface the bank is a family of ellipse arcs around one axis, on a flat plane it runs with the plane's recession — and no line crosses a neighbor inside its own bank.
- Cross-hatch is a second bank crossing the first at 30-90 degrees and appears only in the darkest tonal tier, covering under ~20% of the subject's area; midtones are single-bank only.
- At least one reserved paper highlight sits on the subject: a region with zero strokes, not a lighter fill.
- Line weight is hierarchical: contour 2-4x the median hatch weight, shadow-side contour heavier than light-side, and hatch weight ramps with tone (about 0.35 to 1.6 on a 360-unit canvas).
- Within a bank, spacing changes smoothly and the gap never drops below the line width — lines must never fuse into solid black.
- Round or tapered caps on every hatch stroke; no dash arrays, no filters, no blur.

## Geometry & grid

- Reference canvas is 360x270 (a 4:3 plate); any ratio works, and banner work composes for the sanitizer's fixed 1536x1024 frame.
- Double-rule plate frame: a heavy outer rule inset ~3% of the short side, a fine inner rule ~2% further in; all hatching stops before the inner rule.
- Banks are parametric families, never hand-drawn paths: house rule — repetition math goes through a generator, and you tune the ramp constants, not individual lines.
- Sphere-form banks are latitude ellipse arcs around an axis pointed at the light, with minor/major ratio equal to the axis z-tilt (0.4-0.55 reads well) and arc span plus weight keyed to distance-from-light.
- Background rules are horizontal, spacing widening away from the frame edge (sky dense at top, ground widening toward the viewer), broken with a 6-10 unit halo gap around the subject so the silhouette stays crisp.
- Round all coordinates to 1 decimal.

## Palette

- Exactly 2 tokens: `ink` (every stroke) and `paper` (the single background fill).
- Example plate: ink `#2A2118` (warm umber-black) on paper `#F3ECDC` (cream laid stock).
- Alternate plates that stay in-style: blue-black `#1C2430` on `#EDE8DB`, or sanguine `#6B3020` on `#F2E7D4`; changing the ink hue is allowed, adding a second simultaneous ink is not.

## Do / Don't

- Do generate every bank from a loop over one parameter (latitude angle, y-step) and fix flaws by retuning the ramp, never by nudging one line.
- Do reserve the highlight first and protect it — untouched paper is the brightest value available and anchors the composition.
- Do ramp both spacing and weight toward shadow, using interleaved half-step bands to reach the dark tier.
- Do give background rules a halo gap around the subject instead of running them underneath it.
- Don't fake midtones with opacity, gray fills, or gradients — spacing and weight are the only tone controls.
- Don't cross-hatch a midtone or stack three or more banks anywhere; it reads as mud, not shadow.
- Don't use one uniform stroke width — the generic critique already flags it as clip art, and in this style it is fatal.
- Don't simulate plate texture with dashes, `feTurbulence` grain, or blur.

## Critique add-ons

- Tier count: mentally posterize to four values — paper, light hatch, dense hatch, cross-hatch; if any tier is missing on the subject, the ramp failed.
- Bank coherence: inside one bank, any line crossing its neighbor is a defect; crossings may only occur between banks.
- Cross-hatch budget: point at every crossing region and ask "is this the darkest 20%?" — crossing visible in a midtone means the second bank must be cut back.
- Highlight purity: zoom the highlight; it must be clean paper bounded by thinning arcs, not a lighter gray patch.
- Clot and moire: at full render size shadow-tier lines must still resolve as separate lines, and at 120px the banks must gray out evenly — fusing means widen spacing, shimmer means break the spacing regularity.

## Seed recipe

Skeleton (paper, plate frame, weighted contour) — the banks are then emitted into the group by a generator loop:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 360 270" role="img">
  <title>Engraved-hatch seed</title>
  <rect width="360" height="270" fill="#F3ECDC"/>
  <g fill="none" stroke="#2A2118" stroke-linecap="round">
    <rect x="10" y="10" width="340" height="250" stroke-width="1.5"/>
    <rect x="15.5" y="15.5" width="329" height="239" stroke-width="0.5"/>
    <circle cx="148" cy="122" r="66" stroke-width="2.2"/>
    <!-- bank A: latitude arcs around the light axis (generator loop) -->
    <!-- bank B: cross-hatch arcs, deepest-shadow crescent only -->
  </g>
</svg>
```

Bank-generator core (the math the exemplar was built from):

```python
# axis: unit 2D vector d pointing at the light; tilt AZ ~ 0.45 toward the viewer
# per latitude band phi (degrees), high phi = near the light pole:
u  = (58 - phi) / 140          # 0 at light pole -> 1 at dark limb
w  = 0.35 + 1.25 * u ** 1.5    # stroke-width ramp
t0, t1 = 38 - 46 * u, 148 + 40 * u   # arc span: short near light, long in shadow
# ellipse arc P(t) = center + Mj*rM*cos(t) + Mi*rm*sin(t)
#   center = C + d*sqrt(1-AZ^2)*R*sin(phi); rM = R*cos(phi); rm = rM*AZ
#   Mj = perp(d); Mi = -d (bulge away from the light)
# emit as cubic beziers with kappa = 4/3 * tan(span_radians / 4)
# dark tier: repeat phi range [-34..-74] at half-step offset, wscale 0.75
# cross-hatch: same construction around an axis rotated ~50 deg, span 25..95 deg
```

## Library references

- `tools/svg/library/styles/refs/engraved-hatch.svg` — first exemplar: sphere study showing both banks, the weighted contour, the plate frame, and halo-broken background rules.
- `tools/svg/library/MANIFEST.json` (may not exist yet) — search tags: `engraving`, `hatching`, `cross-hatch`, `woodcut`, `monochrome`, `line-shading`.
- The line-icon sets under `tools/svg/library/external/` (feather, tabler) are not exemplars — their uniform stroke weight is the opposite of this style; use them only as silhouette sources to hatch over.
