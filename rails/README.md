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
./bin/test-stdlib                             # ABC + catalog + front-matter + writer + doctor, no bundler
ruby bin/zer0-cms doctor ../../lifehacker.dev  # zer0 stack alignment (RFC §4); exit 1 on any error
ruby bin/jekyll-parity ../../lifehacker.dev    # catalog vs Jekyll's own reader (needs the jekyll gem)

# Draft the toddler "IT systems" book (A is for Automation) into a drsai checkout:
ruby bin/zer0-cms new --theme "IT systems" --slug it-alphabet \
     --art-style isometric-tech-toy --out ../../drsai

# Preview any theme without writing files:
ruby bin/zer0-cms new --theme "the ocean" --art-style watercolor-storybook --print
```

Bundled themes (`ruby bin/zer0-cms themes`) generate **offline and deterministically**. Any other theme falls back to Claude and needs `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`.

`./bin/test-stdlib` is exactly what CI runs in `.github/workflows/abc-engine.yml` — one job, no `bundle install`, triggered only by a change under `rails/`. Platform contract: [`docs/PLATFORM.md`](../docs/PLATFORM.md). Pipeline: [`docs/CICD.md`](../docs/CICD.md).

## The web platform (Rails)

The Rails app is the fleet CMS: **Administrate 1.0 dashboards** over an index of every registered Jekyll site, plus the ABC wizard. It is the only part of this directory that needs gems (Ruby 4.0.5, Rails 8.1):

```bash
cd rails
bundle install
bin/rails db:prepare                       # creates storage/development.sqlite3
SITES_DIR=$HOME/github bin/rails server    # http://localhost:3000/admin
bin/rails test                             # integration tests (bundler); bin/test-stdlib stays bundler-free
```

Docker (from the repository root; port 3001 so it can sit next to zer0-image-generator on 3000; published on 127.0.0.1 only):

```bash
SITES_DIR=/path/to/your/jekyll/sites docker compose up --build   # → http://localhost:3001/admin
```

**Git is the source of truth; the database is an index.** `Site#sync!` walks a site with `Zer0Cms::Cms::Catalog` (Jekyll 4.4's reader rules) and `Catalog.media`, and upserts `Page`, `Asset` and `Term` rows in one transaction. Nothing is edited through ActiveRecord:

| Surface | Where | What it does |
|---|---|---|
| Sites | `/admin/sites` | Register (or **Register and sync all** under `SITES_DIR`), **Sync**, per-collection counts, the read-only `_config.yml` |
| Pages | `/admin/pages` | Search title/description/author/path; filters `draft:` `live:` `future:` `error:` `collection:<name>` `site:<id>` `kind:` `tag:` `category:` `author:`; newest first, undated last |
| Page edit | `app/services/page_editor.rb` | Re-reads the file, refuses when its digest differs from the index (sync first), sends `FrontMatter.update_keys` only the keys you changed (emptying a present key deletes it), optionally replaces the body, writes atomically, re-syncs that path. An unchanged save writes nothing |
| New / duplicate / delete | `Zer0Cms::Cms::Writer`, `PageEditor` | Create in a declared collection and existing section; duplicate as a draft; delete after a Turbo confirm. Every path is realpath-confined and symlinks are refused (`app/services/site_path.rb`) |
| Images, terms | `/admin/assets`, `/admin/terms` | Read-only; thumbnails are served by `/files/*path`, images inside a registered site only |
| ABC books | `/abc/new` | The wizard; **Export** needs an explicit target directory holding `_config.yml` (`DRSAI_SITE_ROOT` prefills it; there is no default) |

Custom Administrate fields live in `app/fields` + `app/views/fields`: `MarkdownField` (textarea with a debounced Stimulus preview), `TagListField` (comma input to a list), `PreviewImageField` (thumbnail through `/files`), `StateField` (error / draft / unpublished / future / live). The look is the zer0 sidebar frame themed by `app/assets/stylesheets/zer0-tokens.css`, a **byte-identical vendored copy** of zer0-image-generator's `web/app/assets/stylesheets/zer0-tokens.css` (kit `zer0-ui-tokens 1.0.0`; re-vendor with `cp` and check with `cmp`), mapped onto Administrate's markup by `administrate-theme.css`. Administrate's own compiled CSS/JS bundle is not loaded: it ships a second Turbo, jQuery, Trix and Selectize; importmap loads Turbo and Stimulus instead.

**Access.** Only `localhost`, `127.0.0.1` and `[::1]` are accepted Host headers unless `ZER0_CMS_HOSTS` (comma-separated) names more. With `ZER0_CMS_PASSWORD` set every request needs HTTP basic auth (user `ZER0_CMS_USER`, default `zer0`); without it, any request whose TCP peer is not loopback gets a 403 (`ZER0_CMS_TRUST_DOCKER_GATEWAY=1`, set by compose, also accepts the container's default gateway, which is where a 127.0.0.1-published port arrives from). The CSP allows scripts and styles from the app only, plus a per-request nonce that the importmap tags carry.

## Architecture

| Piece | Where | Role |
|---|---|---|
| Domain / spec | `lib/zer0_cms/abc/spec.rb` | The ABC Book Spec value object (mirrors `schema/abc-book.schema.json`) |
| Themed lexicons | `lib/zer0_cms/abc/lexicons/*.yml` | A–Z word/subject/tagline per theme (offline content) |
| Content providers | `lib/zer0_cms/abc/providers/` | `deterministic` (lexicon) · `anthropic` (Claude, any theme) |
| Art styles | `lib/zer0_cms/abc/art_styles.rb` + `data/abc_art_styles.yml` | Style catalog + text-free prompt composition |
| Wizard | `lib/zer0_cms/abc/wizard.rb` | theme → plan → art direction → per-letter → cover → validated Spec |
| Exporter | `lib/zer0_cms/abc/jekyll_exporter.rb` | Spec → `pages/_books/<slug>/index.md` + `_data/abc_books/<slug>.json` |
| CLI | `bin/zer0-cms` | Headless ABC driver and `doctor PATH [--format text\|findings] [--schema FILE]` |
| CMS primitives | `lib/zer0_cms/cms/` | Catalog (Jekyll 4.4 reader rules), front-matter line surgery, confined writer — stdlib; see [`lib/zer0_cms/cms/README.md`](lib/zer0_cms/cms/README.md) |
| Doctor | `lib/zer0_cms/doctor.rb` | The consumer contract check: theme, image engine, `zer0.json`, `fleet.manifest.yml`, front matter against the theme's schema; findings in lifehacker.dev's `findings.jsonl` shape |
| Parity proofs | `bin/jekyll-parity`, `bin/front-matter-roundtrip`, `test/fixtures/` | The catalog diffed against Jekyll's reader; the front-matter round-trip property over real sites |
| Web | `app/` + `config/` + `db/` | Fleet CMS on Administrate: `Site`/`Page`/`Asset`/`Term` index, `SiteSync`, `PageEditor`, custom fields, the ABC wizard |
| Rake wrappers | `lib/tasks/abc.rake` | `bin/rails abc:styles` / `abc:themes` / `abc:new` |

**Rake tasks.** `lib/tasks/abc.rake` is loaded by the `Rakefile`, so `bin/rails abc:themes` works; `bin/zer0-cms` drives the same classes without bundler.

### The shared contract

- **`schema/abc-book.schema.json`** — the ABC Book Spec, the interchange format consumed by drsai.
- **`lib/zer0_cms/data/abc_art_styles.yml`** — a **byte-identical vendored copy**
of the source of truth in [zer0-image-generator](https://github.com/bamr87/zer0-image-generator) (`lib/zer0_image_generator/abc/art_styles.yml`). Each art-style `id` is a cross-repo contract (drsai front matter + the theme's CSS skin). Re-sync the copy whenever the gem's catalog changes.
- **`lib/zer0_cms/data/frontmatter_schema.yml`** — a **byte-identical vendored copy** of the theme's front-matter contract, [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) `.github/config/frontmatter_schema.yml`; the source commit is recorded in [`lib/zer0_cms/data/README.md`](lib/zer0_cms/data/README.md). `doctor` prefers a site's own copy, and `--schema FILE` over both.

## Conventions

- Conventional Commits; branch from `main`, open a PR.
- `lib/` is **stdlib-only** — no gems. Keep Rails-only code in `app/`. CI runs `bin/test-stdlib` with no `bundle install`, so a gem reached from `lib/` is exactly the regression that job catches.
- Never hand-edit a generated book (`pages/_books/**` in drsai) — re-run the wizard.
