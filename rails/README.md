# zer0-CMS — ABC content engine (Rails)

This is the **content-generation** half of zer0-CMS: a Ruby on Rails application and a stdlib-only Ruby engine that draft children's **ABC / alphabet books**. It lives alongside the VS Code extension (`../src`) — the extension *edits* content, this engine *generates* it.

It is the first stage of the fleet's children's-book pipeline:

```text
zer0-CMS (this app) ── ABC Book Spec ──▶ drsai ──▶ GitHub Pages (zer0-mistakes theme)
   wizard writes the words + composes        publishes the books collection
   text-free art prompts per letter          renders with the book-abc layout
        │
        └── art styles + prompt composition shared with the
            zer0-image-generator plugin (the illustrator)
```

## Quick start (no Rails needed)

The engine is **stdlib-only Ruby** — the CLI, rake tasks, and tests run without `bundle install`:

```bash
cd rails
ruby bin/zer0-cms styles                     # list ABC art styles
ruby bin/zer0-cms themes                      # list bundled A–Z lexicons
ruby -Ilib test/zer0_cms/test_abc_engine.rb   # 15 tests, zero network

# Draft the toddler "IT systems" book (A is for Automation) into a drsai checkout:
ruby bin/zer0-cms new --theme "IT systems" --slug it-alphabet \
     --art-style isometric-tech-toy --out ../../drsai

# Preview any theme without writing files:
ruby bin/zer0-cms new --theme "the ocean" --art-style watercolor-storybook --print
```

Bundled themes (`ruby bin/zer0-cms themes`) generate **offline and deterministically**. Any other theme falls back to Claude and needs `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`.

## The web wizard (Rails)

```bash
cd rails
bundle install
DRSAI_SITE_ROOT=../../drsai bin/rails server    # http://localhost:3000
```

The wizard form drives the exact same `Zer0Cms::Abc::Wizard` + `JekyllExporter` the CLI drives — **Preview** renders the book markdown, **Export to drsai** writes it into `DRSAI_SITE_ROOT`.

## Architecture

| Piece | Where | Role |
|---|---|---|
| Domain / spec | `lib/zer0_cms/abc/spec.rb` | The ABC Book Spec value object (mirrors `schema/abc-book.schema.json`) |
| Themed lexicons | `lib/zer0_cms/abc/lexicons/*.yml` | A–Z word/subject/tagline per theme (offline content) |
| Content providers | `lib/zer0_cms/abc/providers/` | `deterministic` (lexicon) · `anthropic` (Claude, any theme) |
| Art styles | `lib/zer0_cms/abc/art_styles.rb` + `data/abc_art_styles.yml` | Style catalog + text-free prompt composition |
| Wizard | `lib/zer0_cms/abc/wizard.rb` | theme → plan → art direction → per-letter → cover → validated Spec |
| Exporter | `lib/zer0_cms/abc/jekyll_exporter.rb` | Spec → `pages/_books/<slug>/index.md` + `_data/abc_books/<slug>.json` |
| CLI | `bin/zer0-cms` | Headless driver |
| Web | `app/` + `config/` | Thin Rails wrapper over the engine |

### The shared contract

- **`schema/abc-book.schema.json`** — the ABC Book Spec, the interchange format
  consumed by drsai.
- **`lib/zer0_cms/data/abc_art_styles.yml`** — a **byte-identical vendored copy**
of the source of truth in [zer0-image-generator](https://github.com/bamr87/zer0-image-generator) (`lib/zer0_image_generator/abc/art_styles.yml`). Each art-style `id` is a cross-repo contract (drsai front matter + the theme's CSS skin). Re-sync the copy whenever the gem's catalog changes.

## Conventions

- Conventional Commits; branch from `main`, open a PR.
- The engine is **stdlib-only** — no gems in `lib/`. Keep Rails-only code in `app/`.
- Never hand-edit a generated book (`pages/_books/**` in drsai) — re-run the wizard.
