# zer0-image-generator

[![Test](https://github.com/bamr87/zer0-image-generator/actions/workflows/test.yml/badge.svg)](https://github.com/bamr87/zer0-image-generator/actions/workflows/test.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

AI preview/social images for **any Jekyll site** — Claude directs and reviews,
an image model renders, and your front matter gets wired up automatically.

Extracted from the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes)
theme's consolidated engine and generalized: every theme-specific assumption
is now a config knob with zer0-compatible defaults, so the theme and this
plugin stay **separate but portable**.

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
| local       | deterministic template SVG → PNG           | none (CI-safe)      |

Claude never renders pixels (the Anthropic API has no image endpoint); without
a Claude credential the analyze/review stages degrade gracefully to a template
prompt and the renderer still runs.

## Install

### As a Jekyll plugin (recommended)

```ruby
# Gemfile
group :jekyll_plugins do
  gem "zer0-image-generator"
end
```

Requires `python3` (3.9+) with PyYAML — the command checks and tells you if
either is missing:

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

The engine is one dependency-light Python file. Copy it anywhere and run it
from your site root:

```bash
curl -o preview_generator.py \
  https://raw.githubusercontent.com/bamr87/zer0-image-generator/main/lib/zer0_image_generator/preview_generator.py
python3 preview_generator.py --dry-run
```

## Configuration

Everything lives under `preview_images:` in your `_config.yml`. Shown with
defaults:

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
  # --- portability knobs (the zer0-isms, now configurable) ---
  collections: [posts]        # list of collections, or 'auto' to discover
                              # them from Jekyll's own `collections:` map
  collections_dir: ''         # falls back to Jekyll's top-level collections_dir
  front_matter_key: preview   # key to read/write (jekyll-seo-tag sites: image)
  authors_file: _data/authors.yml  # per-author style overrides ('' disables)
  assets_prefix: /assets      # written paths omit this prefix ...
  auto_prefix: true           # ... and it is re-added for existence checks
```

Priority per file: author overrides → CLI flags → environment variables →
`_config.yml` → built-in defaults.

### Recipe: standard Jekyll site with jekyll-seo-tag

```yaml
preview_images:
  provider: openai
  collections: auto
  front_matter_key: image     # jekyll-seo-tag reads page.image
  assets_prefix: ''           # write full site-absolute paths
  authors_file: ''
```

Generated front matter: `image: /assets/images/previews/my-post.png` — exactly
what `jekyll-seo-tag` turns into `og:image`.

### Recipe: zer0-mistakes theme

```yaml
preview_images:
  provider: openai
  collections: [posts, docs, quickstart]
  # collections_dir comes from the theme's own `collections_dir: pages`
  # front_matter_key/preview + /assets prefixing are already the defaults
```

### Per-author style overrides

If `authors_file` points at a YAML map, an author's `preview:` block overrides
`style`, `style_modifiers`, `size`, `quality`, and `model` for their pages:

```yaml
# _data/authors.yml
cassandra:
  preview:
    style: >-
      noir graphic-novel, high-contrast ink
```

## Credentials

The renderer needs its own key (default: `OPENAI_API_KEY`). Claude
orchestration accepts any ONE of, in order — it is optional:

```bash
export CLAUDE_CODE_OAUTH_TOKEN="..."   # 1. from `claude setup-token` (Pro/Max)
export ANTHROPIC_AUTH_TOKEN="..."      # 2. short-lived bearer token
export ANTHROPIC_API_KEY="..."         # 3. console.anthropic.com
# 4. nothing — a logged-in `claude` CLI is used automatically
```

Keys are read from the environment or a git-ignored `.env` at the site root.
On a Claude Pro/Max subscription the orchestration costs nothing extra; only
the renderer bills per image.

## CLI reference

`jekyll preview-images` exposes the engine's flags (Jekyll claims `-s/-d/-p`
globally, so use long forms there; the Python CLI keeps all short flags):

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

The `local` provider rasterizes its SVG via the first available of
`rsvg-convert` (`brew install librsvg` / `apt install librsvg2-bin`),
`inkscape`, ImageMagick, or a vendored Playwright helper.

## CI usage

```yaml
- name: Generate preview images
  env:
    CLAUDE_CODE_OAUTH_TOKEN: ${{ secrets.CLAUDE_CODE_OAUTH_TOKEN }}
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
  run: bundle exec jekyll preview-images
```

Generation is script-driven on demand — it is never part of `jekyll build`
(builds stay fast, deterministic, and secret-free; GitHub Pages safe mode is
irrelevant to it).

## Relationship to zer0-mistakes

The [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme renders
`preview:` values with a pure-Liquid include (GitHub-Pages-safe, no plugin
needed) and currently vendors this engine at `scripts/lib/preview_generator.py`.
This repo is the portable home: the theme is expected to consume the gem (or
curl the engine from here) in a follow-up, so there is exactly ONE engine.

## Development

```bash
python3 test/test_preview_generator.py      # 98 unit tests, zero network
python3 -m py_compile lib/zer0_image_generator/preview_generator.py
gem build zer0-image-generator.gemspec
cd test/fixture-site && bundle install
bundle exec jekyll preview-images --dry-run # integration fixture
```

Conventional Commits drive releases via release-please. One concern per PR.

## License

[MIT](LICENSE) © Amr Abdel
