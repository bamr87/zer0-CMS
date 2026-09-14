<!-- rails/README.md — fleet CMS platform + ABC generator. Never "the content engine": that phrase belongs to src/core/contract/. -->

# zer0-CMS — fleet CMS platform (Rails) + ABC generator

This is the **platform** half of zer0-CMS. The VS Code extension (`../src`) still *edits* content inside the editor. This Rails app is the browser control panel for every zer0-themed Jekyll site: register roots, scan collections, edit front matter in place, and generate ABC books.

The ABC generator remains a stdlib-only Ruby library (`lib/zer0_cms/abc`) with a CLI. The web UI wraps that plus the new `Zer0Cms::Cms` catalog / front-matter layer.

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

The generator is **stdlib-only Ruby** — the CLI and the tests run without `bundle install`:

```bash
cd rails
ruby bin/zer0-cms styles                      # list ABC art styles
ruby bin/zer0-cms themes                      # list bundled A–Z lexicons
./bin/test-stdlib                             # ABC + catalog + front-matter + writer, no bundler

# Draft the toddler "IT systems" book (A is for Automation) into a drsai checkout:
ruby bin/zer0-cms new --theme "IT systems" --slug it-alphabet \
     --art-style isometric-tech-toy --out ../../drsai

# Preview any theme without writing files:
ruby bin/zer0-cms new --theme "the ocean" --art-style watercolor-storybook --print
```

Bundled themes (`ruby bin/zer0-cms themes`) generate **offline and deterministically**. Any other theme falls back to Claude and needs `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`.

`./bin/test-stdlib` is exactly what CI runs in `.github/workflows/abc-engine.yml` — one job, no `bundle install`, triggered only by a change under `rails/`. Platform contract: [`docs/PLATFORM.md`](../docs/PLATFORM.md). Pipeline: [`docs/CICD.md`](../docs/CICD.md).

## The web platform (Rails)

The Rails app is the fleet CMS (sites, content, media, taxonomy, search) plus the ABC wizard. It is the only part of this directory that needs gems:

```bash
cd rails
bundle install
DRSAI_SITE_ROOT=../../drsai bundle exec puma -p 3000 config.ru   # http://localhost:3000
```

Docker (from the repository root; port 3001 so it can sit next to zer0-image-generator on 3000):

```bash
SITES_DIR=/path/to/your/jekyll/sites docker compose up --build   # → http://localhost:3001
```

The dashboard lists Jekyll sites under `/sites`. Register them (or **Register all**), then open Content to search, create, edit, duplicate, or delete pages. Media, taxonomy, and `_config.yml` are per-site tabs. Fleet-wide search is in the sidebar. ABC books stay at `/abc/new`.

The browser UI is Hotwire (Turbo + Stimulus) via importmap, paginated with Pagy, with Kramdown/GFM for markdown preview.

**Why `puma` and not `rails server`.** This app has no `bin/rails` binstub — `bin/` holds the headless CLI and nothing else. The `rails` executable searches upward for `bin/rails` and, finding none, decides you meant `rails new` and prints its usage; it never boots this app. `config.ru` requires `config/environment`, so any Rack server starts it, and `puma` is the one already in the `Gemfile`. Adding a `bin/rails` binstub is a reasonable follow-up; until someone does, this is the command that works.

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
| CLI | `bin/zer0-cms` | Headless ABC driver |
| CMS primitives | `lib/zer0_cms/cms/` | Catalog, front-matter surgery, writer (stdlib) |
| Web | `app/` + `config/` | Fleet CMS + ABC wizard (Hotwire, sqlite site registry) |
| Rake wrappers | `lib/tasks/abc.rake` | `abc:styles` / `abc:themes` / `abc:new` — **not reachable today** |

**About those rake tasks.** `lib/tasks/abc.rake` is written and correct, but this directory has no `Rakefile` and the app has no `bin/rails` to load one, so `rake abc:*` cannot be invoked from here. Use `bin/zer0-cms`, which drives the same classes. The `.rake` file is kept because it is what the tasks should look like once a `Rakefile` exists.

### The shared contract

- **`schema/abc-book.schema.json`** — the ABC Book Spec, the interchange format
  consumed by drsai.
- **`lib/zer0_cms/data/abc_art_styles.yml`** — a **byte-identical vendored copy**
of the source of truth in [zer0-image-generator](https://github.com/bamr87/zer0-image-generator) (`lib/zer0_image_generator/abc/art_styles.yml`). Each art-style `id` is a cross-repo contract (drsai front matter + the theme's CSS skin). Re-sync the copy whenever the gem's catalog changes.

## Conventions

- Conventional Commits; branch from `main`, open a PR.
- `lib/` is **stdlib-only** — no gems. Keep Rails-only code in `app/`. CI runs `bin/test-stdlib` with no `bundle install`, so a gem reached from `lib/` is exactly the regression that job catches.
- Never hand-edit a generated book (`pages/_books/**` in drsai) — re-run the wizard.
