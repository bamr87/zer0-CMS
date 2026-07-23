# ABC alphabet-book plugin

`zer0-image-generator` doubles as the **illustration plugin** for the fleet's
children's-book pipeline. Where the `jekyll preview-images` CLI renders one
social banner per page, the ABC plugin renders one plate **per alphabet
letter** of a toddler ABC book, in a chosen art style, from a shared spec.

```text
zer0-CMS (Rails wizard)  ──▶  ABC Book Spec  ──▶  drsai (books collection)
   picks art_style,              (JSON/YAML)          ships prompts, renders
   composes letters                  │                        │
                                     ▼                        ▼
              lib/zer0_image_generator/abc/*  ◀── art-style catalog + prompts
                    (THIS plugin — owns the look)
```

## What the plugin owns

- **`lib/zer0_image_generator/abc/art_styles.yml`** — the **source of truth**
  for ABC illustration styles (`isometric-tech-toy`, `chalkboard-doodle`,
  `soft-plush`, `crayon-primary`, `paper-cutout`, `watercolor-storybook`) and
  the option knobs (palette / background / lettering / mood). Each style `id`
  is a cross-repo contract: zer0-CMS writes it into book front matter and the
  zer0-mistakes theme maps it to a `abc-style--<id>` CSS skin. zer0-CMS carries
  a **byte-identical vendored copy**; re-sync it whenever this file changes:

  ```bash
  diff lib/zer0_image_generator/abc/art_styles.yml \
       ../zer0-CMS/rails/lib/zer0_cms/data/abc_art_styles.yml
  ```

- **`Zer0ImageGenerator::Abc::StylePack`** — loads the catalog and composes one
  deterministic, **text-free** raster prompt per letter (the big letter is HTML
  typography in the theme, never baked into the art, so models never garble
  spelling).

- **`Zer0ImageGenerator::Abc::Plugin`** — turns an ABC Book Spec into render
  work: `compose_prompts(book)` fills each letter's `prompt` (hand-authored
  prompts win), and `build_plan(book, root:)` returns the idempotent list of
  letters still missing art.

## Usage

```ruby
require "zer0_image_generator/abc"

pack = Zer0ImageGenerator::Abc::StylePack.default

pack.render_prompt(
  letter: "A", word: "Automation",
  subject: "a friendly robot arm stacking soft blocks",
  style:   "isometric-tech-toy"      # palette/background/mood optional
)
# => "cute isometric toy-technology illustration ... Subject: a friendly robot
#     arm ..., standing for the word AUTOMATION (letter A). ... no text ..."

book = YAML.safe_load_file("it-alphabet.abc.yml")   # an ABC Book Spec
plan = Zer0ImageGenerator::Abc::Plugin.build_plan(book, root: "../drsai")
plan.each { |job| puts "#{job.letter} → #{job.out_path}" }
```

## Rendering the plates

The plugin composes prompts and plans work; the actual pixels are produced by
whichever provider the publisher runs. In `drsai` that is
`tools/generate_illustrations.py`, which now understands an `alphabet:` front
matter block and renders each letter's `prompt` to its declared `image` path —
the same declared-path contract the story illustrator already uses. To render
with this gem's Ruby providers instead, feed each `RenderJob.prompt` to a
configured `Zer0ImageGenerator` provider.

## Design guarantees

- **Additive.** The plugin requires none of the byte-identity engine port and
  changes none of it; the deterministic `local` provider and every committed
  sample stay bit-for-bit unchanged.
- **Deterministic.** Same spec → same prompts → same committed book.
- **Stdlib only**, matching the `lib/` policy.

Tests: `ruby -Ilib test/ruby/test_abc_style_pack.rb`.
