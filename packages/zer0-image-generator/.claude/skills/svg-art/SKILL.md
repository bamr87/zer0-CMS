---
name: svg-art
description: Art-direction playbook and iteration loop for producing SVG artwork. Use when generating, refining, or critiquing vector illustrations, banner templates, generative pieces, logos, icons, or diagram art.
---

# SVG art

## Before drawing anything

Check the library first: `tools/svg/library/` has style cards (testable constraints + seed recipes) and license-vetted exemplar SVGs searchable by tag in `MANIFEST.json`. Match the brief to a card, read 1-3 exemplars, then draw. For a fully automated draft→critique→refine run, use the `svg-forge` saved workflow with `args: {brief, out}`.

When the brief names a concrete subject, also ask whether the art already exists: `python3 tools/svg/freesvg.py search "<subject>"` queries FreeSVG's CC0 catalog cache-first (zero API cost on repeat lookups), `fetch <id>` pulls a candidate into the local cache, and adapting good existing art to the style card usually beats drawing the subject from scratch. Skip silently if `freesvg.py status` reports missing credentials.

## The loop

You cannot see what you wrote. That is the entire problem. Every cycle:

1. Write or regenerate the SVG.
2. The PostToolUse hook lints and rasterizes it. **Read the PNG.**
3. Say out loud what is wrong with it before you touch the file again.
4. Change one variable. Repeat.

Skipping step 3 produces confident garbage. Name the flaw first.

When the SVG comes from engine code rather than a hand-edited file (this repo's usual case), close the loop manually: `python3 tools/svg/banner-seed.py --seed N --out .sweep/x.svg`, then `bash tools/svg/svg-render.sh .sweep/x.svg`, then Read the PNG.

## Critique vocabulary

When you read the render, grade it against these, in order:

- **Read at thumbnail size.** Squint. If the silhouette is mush at 64px, nothing downstream matters. Social cards show banners around 500px wide — render at 120px for the squint test.
- **Value structure.** Three tiers minimum: ground, mid, accent. Most bad generative output is one tier of noise.
- **Negative space.** Is it doing work, or is it just leftovers?
- **Focal hierarchy.** Where does the eye land first, second, third? If the answer is "everywhere," the piece has no subject.
- **Edge quality.** Uniform stroke weight throughout reads as clip art. Vary it.
- **Density gradient.** Even distribution is the signature of an algorithm that was not art-directed.

## Techniques that hold up

- Constrain the palette to 3-5 tokens declared once at the top as CSS custom properties or a `<defs>` block. Sampling arbitrary hex values per element is what makes output look machine-made. (The engine already does this: `RETRO_PALETTES` keyed by seed.)
- Overlap and occlusion create depth far more cheaply than gradients.
- Layer opacity beats layer count. 200 strokes at 0.3 opacity reads richer than 600 at 1.0.
- Break symmetry deliberately in one place. Perfect symmetry reads as a test pattern.
- Pixel art: build on `tools/svg/pixelkit.py` — integer cell grid, `crispEdges`, ASCII-map sprites, run-length-merged rects, CRT veil. Bilateral symmetry (`hmirror`) is what makes random blobs read as creatures; give the protagonist sole ownership of one palette token.

## Variation

For generative work, never judge a single output. Run `bash tools/svg/svg-sweep.sh tools/svg/banner-seed.py 12`, read the one contact sheet, and pick winners. Then narrow the parameter range around the winners and sweep again. For a template change in `render_local_svg`, sweep before and after — the change must improve the *population*, not one lucky seed.

## Before calling it done

- `python3 tools/svg/svg-check.py <file> --strict` passes
- Renders identically in at least two engines if it will ship on the web
- `npx svgo <file>` run, and the result re-checked
- For engine template changes: `python3 test/test_preview_generator.py` still passes (determinism and sanitizer tests cover the template)
