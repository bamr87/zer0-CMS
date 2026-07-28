# zer0-image-generator

[![Test](https://github.com/bamr87/zer0-image-generator/actions/workflows/test.yml/badge.svg)](https://github.com/bamr87/zer0-image-generator/actions/workflows/test.yml) [![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AI preview/social images for **any Jekyll site** — Claude directs and reviews, an image model renders, and your front matter gets wired up automatically.

Extracted from the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme's consolidated engine and generalized: every theme-specific assumption is now a config knob with zer0-compatible defaults, so the theme and this plugin stay **separate but portable**.

Three ways to drive it: the `jekyll preview-images` **Gem/CLI**, the standalone **Python engine**, and a **web app** ([web/](web/README.md)) — a Dockerized Rails control panel that runs a pure-Ruby port of the engine ([lib/zer0_image_generator/](lib/zer0_image_generator/), pinned byte-for-byte against the Python original), so all three share one behavior. In the browser you can:

- register sites, edit their `preview_images:` config, and run generation with a
  live-streaming log;
- **forge a standalone image** — Claude directs the art (via a Claude Code OAuth
token), a renderer produces it, Claude reviews it, and you can process any version further with OpenAI;
- drive the `tools/svg/` generators from knob forms and browse the example
  library.

```bash
SITES_DIR=/path/to/your/jekyll/sites docker compose up --build   # → localhost:3000
```

## How it works

Each post/page without a preview goes through a three-stage pipeline:

| stage   | role                                                        | engine / credential                    |
| ------- | ----------------------------------------------------------- | -------------------------------------- |
| analyze | Claude reads the article and writes a vivid art brief       | Claude credential chain (see below)    |
| produce | an image model renders the brief                            | the selected provider                  |
| review  | Claude inspects the render (vision); one refined regen max  | same Claude credential chain           |

| provider    | renderer                                   | credential          |
| ----------- | ------------------------------------------ | ------------------- |
| **openai** (default) | gpt-image-2 / dall-e-3 (+ `--enhance`) | `OPENAI_API_KEY`    |
| xai         | grok-2-image                               | `XAI_API_KEY`       |
| stability   | Stable Diffusion XL                        | `STABILITY_API_KEY` |
| gemini      | gemini-2.5-flash-image                     | `GEMINI_API_KEY`    |
| local       | content-aware deterministic SVG            | none (CI-safe)      |

Claude never renders pixels (the Anthropic API has no image endpoint); without a Claude credential the analyze/review stages degrade gracefully to a template prompt and the renderer still runs.

## Install

### As a Jekyll plugin (recommended)

```ruby
# Gemfile
group :jekyll_plugins do
  gem "zer0-image-generator"
end
```

Requires `python3` (3.9+) with PyYAML — the command checks and tells you if either is missing:

```bash
python3 -m pip install pyyaml
```

Then, from your site root:

```bash
bundle exec jekyll preview-images --list-missing   # what needs a banner?
bundle exec jekyll preview-images --dry-run        # what would be generated?
bundle exec jekyll preview-images                  # generate them
```

### Standalone (no Ruby required)

The engine is one dependency-light Python file. Copy it anywhere and run it from your site root:

```bash
curl -o preview_generator.py \
  https://raw.githubusercontent.com/bamr87/zer0-image-generator/main/lib/zer0_image_generator/preview_generator.py
python3 preview_generator.py --dry-run
```

## Configuration

Everything lives under `preview_images:` in your `_config.yml`. Shown with defaults:

```yaml
preview_images:
  enabled: true
  provider: openai            # openai | xai | stability | gemini | local
  model: ''                   # empty = provider default (gpt-image-2, ...)
  size: 1536x1024
  quality: auto               # auto (GPT Image) | standard/hd (DALL-E 3)
  style: "retro pixel art, 8-bit video game aesthetic, vibrant colors"
  style_modifiers: "pixelated, retro gaming style, CRT screen glow effect"
  output_dir: assets/images/previews
  prompt_engine: claude       # claude analyzes each article | template
  review_engine: claude       # claude vision-reviews each render | none
  claude_effort: low          # output_config.effort for the brief/review calls
                              # (low = fastest, right-sized for short briefs;
                              #  high = deepest; '' sends no effort parameter)
  rasterizer: auto            # SVG→PNG tool for the SVG providers (local,
                              # claude): auto | rsvg | inkscape | magick |
                              # playwright | none. `none` = SVG-only (below).
  # --- portability knobs (the zer0-isms, now configurable) ---
  collections: [posts]        # list of collections, or 'auto' to discover
                              # them from Jekyll's own `collections:` map
  collections_dir: ''         # falls back to Jekyll's top-level collections_dir
  front_matter_key: preview   # key to read/write (jekyll-seo-tag sites: image)
  authors_file: _data/authors.yml  # per-author style overrides ('' disables)
  collection_styles: {}       # per-collection style/theme overrides (below)
  assets_prefix: /assets      # written paths omit this prefix ...
  auto_prefix: true           # ... and it is re-added for existence checks
```

Priority per file: author overrides → collection styles → CLI flags → environment variables → `_config.yml` → built-in defaults.

Jekyll's own top-level `source:` key is honored automatically: on a site with `source: pages` (content, assets, and `_data` under `pages/`), every disk path above resolves inside `pages/` while front-matter values keep their site-URL form. No extra configuration needed.

### Recipe: standard Jekyll site with jekyll-seo-tag

```yaml
preview_images:
  provider: openai
  collections: auto
  front_matter_key: image     # jekyll-seo-tag reads page.image
  assets_prefix: ''           # write full site-absolute paths
  authors_file: ''
```

Generated front matter: `image: /assets/images/previews/my-post.png` — exactly what `jekyll-seo-tag` turns into `og:image`.

### Recipe: zer0-mistakes theme

```yaml
preview_images:
  provider: openai
  collections: [posts, docs, quickstart]
  # collections_dir comes from the theme's own `collections_dir: pages`
  # front_matter_key/preview + /assets prefixing are already the defaults
```

### Recipe: children's book collections (drsai)

The [drsai storybook platform](https://github.com/bamr87/drsai) publishes picture books through the zer0-mistakes `books` collection and uses this gem for each story's social/preview banner. Match the banner style to the book's illustration bible so cards and pages read as one book:

```yaml
preview_images:
  provider: openai
  collections: [books]
  # each story's `preview` starts as its first illustration plate; this gem
  # fills banners for pages that don't have one yet
  style: >-
    cozy warm digital watercolor storybook art, soft colored-pencil outlines,
    rounded friendly shapes, sun-baked desert palette, gentle golden-hour light
  style_modifiers: kid-friendly, never photorealistic, never dark or scary
```

Note the division of labor: this gem renders **one banner per page** keyed on front matter; the *in-story* illustration plates (several per story, tracked in each page's `illustrations:` list) are rendered by drsai's own `tools/generate_illustrations.py` against the same OpenAI credential.

### Batch performance

The engine parallelizes **within one invocation** (4 workers by default, `-j N` to change). For many files, one collection run beats a loop of single-file runs — the loop pays process startup per file and never engages the pool:

```bash
bundle exec jekyll preview-images --collection posts --parallel 6   # ✓ parallel
for f in ...; do jekyll preview-images -f "$f"; done                # ✗ serial
```

Claude orchestration runs at `claude_effort: low` by default — right-sized for a short art brief and a render verdict. Raise it (or set `claude_model`) if you want deeper art direction at the cost of latency.

### Per-collection styles

Give each collection its own visual identity — tutorials render differently from field notes, docs differently from reviews. Any of `style`, `style_modifiers`, `size`, `quality`, and `model` can be set per collection; everything else inherits the global config. A file's collection comes from its `_<name>` directory; author overrides still win over collection styles.

```yaml
preview_images:
  style: "retro pixel art"          # global fallback
  collection_styles:
    posts:
      style: "hand-inked editorial illustration, warm print tones"
    docs:
      style: "clean isometric technical diagram"
      style_modifiers: "matte surfaces, labeled parts, blueprint accents"
    hacks:
      style: "circuit-board schematic, glowing traces"
```

### Per-author style overrides

If `authors_file` points at a YAML map, an author's `preview:` block overrides `style`, `style_modifiers`, `size`, `quality`, and `model` for their pages:

```yaml
# _data/authors.yml
cassandra:
  preview:
    style: >-
      noir graphic-novel, high-contrast ink
```

## Credentials

The renderer needs its own key (default: `OPENAI_API_KEY`). Claude orchestration accepts any ONE of, in order — it is optional:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="..."   # 1. from `claude setup-token` (Pro/Max)
export ANTHROPIC_AUTH_TOKEN="..."      # 2. short-lived bearer token
export ANTHROPIC_API_KEY="..."         # 3. console.anthropic.com
# 4. nothing — a logged-in `claude` CLI is used automatically
```

Keys are read from the environment or a git-ignored `.env` at the site root. On a Claude Pro/Max subscription the orchestration costs nothing extra; only the renderer bills per image.

## CLI reference

`jekyll preview-images` exposes the engine's flags (Jekyll claims `-s/-d/-p` globally, so use long forms there; the Python CLI keeps all short flags):

```text
--dry-run --verbose --force --list-missing
-f/--file FILE          --collection NAME|all       --provider NAME
--model NAME            --output-dir DIR            -j/--parallel N
--style TEXT            --prompt-engine claude|template
--review claude|none    --rasterizer auto|rsvg|inkscape|magick|playwright|none
-e/--enhance            --enhance-prompt/-model/-quality/-fidelity/-format
--collections-dir DIR   --front-matter-key KEY      --authors-file FILE
--assets-prefix PREFIX  --no-auto-prefix            --batch N  --log-file FILE
```

### Content-aware local banners

The `local` renderer does not draw one template in six colours. It reads the page's own context — its **section**, **tags**, **title**, **description** and **body** — and picks both the composition and the palette from it, so a shell hack and a narrative essay do not come out looking like siblings.

| composition | reads as | selected by |
| --- | --- | --- |
| `circuit` | orthogonal traces, pads, vias, chips | `hacks`, shell/docker/git/ci vocabulary |
| `pixelscene` | pixel-art side-scroller | `tools`, reviews, editors, games |
| `flowfield` | streamlines through a noise field | `field-notes`, essays, AI/automation |
| `lowpoly` | faceted gradient field | `docs`, guides, architecture, schemas |
| `starfield` | constellations over layered ridges | security, secrets, audits, exploration |

Fields are **weighted, not pooled**: a section name is a deliberate editorial choice and tags and titles are hand-written, so they carry most of the signal, while the long incidental body is capped. Matching is on whole words — a bare substring test fires `ci` inside "de**ci**sion" and drags an entire dev blog toward one look. With no keyword hit anywhere the seed picks, so every page still gets art.

Determinism is unchanged and remains a hard contract: the same article renders the same bytes on both engines. The seed comes from the article's **content** rather than its filename, so retitling or re-tagging a piece re-rolls its art — and two posts whose filenames merely sort next to each other no longer come out kin.

Every composition is authored at the banner frame (1536×1024), so the sanitizer's forced `viewBox` is a no-op rather than a squash, and each emits `role="img"` plus a `<title>`.

The `local` provider rasterizes its SVG via the first available of `rsvg-convert` (`brew install librsvg` / `apt install librsvg2-bin`), `inkscape`, ImageMagick, or a vendored Playwright helper.

### SVG-only sites

`rasterizer: none` makes the vector banner the deliverable: the SVG providers (`local`, `claude`) write the sanitized `.svg`, skip rasterization entirely, and stamp `preview: /assets/images/previews/<slug>.svg` into front matter. No PNG is produced and none is expected — the engine says "SVG-only mode" instead of nagging about a missing librsvg.

```yaml
preview_images:
  provider: local             # the deterministic, key-free SVG renderer
  rasterizer: none            # ... and keep its output as SVG
```

It is a site-level policy, so it belongs in `_config.yml` — every entry point (the `jekyll preview-images` CLI, a bare `python3 preview_generator.py`, the web app, CI) picks it up with no per-invocation flag. `--rasterizer` and `IMAGE_RASTERIZER` still override it for a one-off run.

Banners land at roughly 10–15 KB each instead of 1–2 MB, they diff as text in review, and they scale to any viewport. The trade-off: some social-card scrapers still prefer a raster `og:image`, so keep `rasterizer: auto` if link-preview cards matter more than repository weight.

## CI usage

```yaml
- name: Generate preview images
  env:
    CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  run: bundle exec jekyll preview-images
```

Generation is script-driven on demand — it is never part of `jekyll build` (builds stay fast, deterministic, and secret-free; GitHub Pages safe mode is irrelevant to it).

## ABC alphabet-book plugin

Beyond one-banner-per-page previews, this gem is the **illustration plugin** for the fleet's children's-book pipeline: it owns the art-style catalog and composes one text-free plate per alphabet letter of a toddler ABC book. The [zer0-CMS](https://github.com/bamr87/zer0-CMS) Rails wizard picks an `art_style` and emits an *ABC Book Spec*; [drsai](https://github.com/bamr87/drsai) ships it into the `books` collection and renders each letter's prompt.

```ruby
require "zer0_image_generator/abc"
Zer0ImageGenerator::Abc::StylePack.default.render_prompt(
  letter: "A", word: "Automation",
  subject: "a friendly robot arm stacking soft blocks",
  style: "isometric-tech-toy")
```

The style catalog (`lib/zer0_image_generator/abc/art_styles.yml`) is the source of truth shared, by vendored copy, with zer0-CMS and the theme. See [docs/abc-plugin.md](docs/abc-plugin.md).

## Relationship to zer0-mistakes

The [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme renders `preview:` values with a pure-Liquid include (GitHub-Pages-safe, no plugin needed) and currently vendors this engine at `scripts/lib/preview_generator.py`. This repo is the portable home: the theme is expected to consume the gem (or curl the engine from here) in a follow-up, so there is exactly ONE engine.

## Development

```bash
python3 test/test_preview_generator.py      # 108 unit tests, zero network
python3 test/test_freesvg.py                # FreeSVG client/cache tests, network mocked
python3 -m py_compile lib/zer0_image_generator/preview_generator.py
gem build zer0-image-generator.gemspec
cd test/fixture-site && bundle install
bundle exec jekyll preview-images --dry-run # integration fixture
```

When touching SVG code (the local template, sanitizer, rasterizer chain), use the authoring loop in [tools/svg/](tools/svg/README.md): a PostToolUse hook lints and rasterizes every `.svg` write so the agent sees what it drew, `banner-seed.py` sweeps the engine's real template across seeds into a contact sheet, and the `svg-critic` subagent keeps render/critique churn out of the main context. The [showcase](docs/showcase/README.md) walks the whole pipeline with the intermediate images each piece iterated through.

Conventional Commits drive releases via release-please. One concern per PR.

## License

[MIT](LICENSE) © Amr Abdel
