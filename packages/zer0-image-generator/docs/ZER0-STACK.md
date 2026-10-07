# The zer0 stack

Three repos, one contract each: a theme that renders, an image engine that draws, a CMS that edits. A content repo is aligned when it consumes each pillar through its contract and nothing else — no vendored forks, no copied generators. This page is the image generator's side of that agreement: what it owns, the API and design tokens it publishes for zer0-CMS, and how the two web apps sit side by side. The decisions behind it were taken on 2026-09-14.

## The three pillars

| Pillar | Repo | Owns | A content repo consumes it as |
| --- | --- | --- | --- |
| Theme | [bamr87/zer0-mistakes](https://github.com/bamr87/zer0-mistakes) | layouts, includes, the front-matter contract (`.github/config/frontmatter_schema.yml`), the consumer kit (`templates/consumer/`), the consumer registry (`_data/consumers.yml`) | `remote_theme: bamr87/zer0-mistakes` (a floating ref is a deliberate posture in lifehacker.dev and it-journey; pinning stays the owner's call) |
| Image engine | [bamr87/zer0-image-generator](https://github.com/bamr87/zer0-image-generator) (this repo) | the preview pipeline (Python oracle + pure-Ruby port under `lib/zer0_image_generator/`), the `preview_images:` config, the `jekyll preview-images` command, the web image forge, the design tokens | the `zer0-image-generator` gem in `group :jekyll_plugins` plus one `preview_images:` block — no vendored `_plugins/preview_*` forks, no copied Python or bash generators |
| CMS | [bamr87/zer0-CMS](https://github.com/bamr87/zer0-CMS) | the Rails fleet CMS (`rails/`), the VS Code extension (`src/`), the stdlib content library (`rails/lib/zer0_cms/cms`), the consumer contract check (`zer0 doctor`), the `zer0.json` schema | a valid `zer0.json` (console dialect, with a `$schema` pointer) plus an optional report-only `zer0-doctor` workflow caller |

lifehacker.dev's Trace Bloom generator (`scripts/preview/`) is the one sanctioned exception: a deliberate offline style, recorded as a candidate to port upstream into this engine, not a drifted copy of it.

## The contracts

**Theme.** The theme renders `preview:` with a pure-Liquid include, so a site needs no plugin at build time and stays GitHub-Pages-safe. Front matter is validated against the theme's `frontmatter_schema.yml`; new consumers start from `templates/consumer/`.

**Image engine.** Generation is on demand (`bundle exec jekyll preview-images`), never part of `jekyll build`. The Python file is the behavioral oracle and the Ruby port is pinned byte-for-byte against it; the CLI, the web app and the facade all drive that one port. Two things are public: `Zer0ImageGenerator::Facade` for Ruby callers and `zer0-tokens.css` for Rails panels. Everything else under `lib/zer0_image_generator/` is internal and may move.

**CMS.** Git is the source of truth and zer0-CMS's database is only an index over it. A site is aligned when `ruby -I rails/lib rails/bin/zer0-cms doctor <site>` reports no errors. The doctor raises an error for a vendored `_plugins/preview_image_generator.rb` or `preview_generator.rb`, and a warning for a missing `preview_images:` block or a Gemfile without the gem.

## How zer0-CMS uses the image engine

### The facade

zer0-CMS needs two answers from the engine: which pages lack a preview, and "draw this one page". `lib/zer0_image_generator/facade.rb` answers both without Rails or Jekyll. It composes the engine's own objects (config, settings, `Runner`, `Content`, the CLI's credential check), so "missing" and "generate" mean exactly what `jekyll preview-images --list-missing` and `jekyll preview-images -f FILE` mean. `test/ruby/test_facade.rb` pins that parity against a real `--list-missing` run.

```ruby
# Gemfile — `require: false`; only the ImageEngine service loads it.
gem "zer0-image-generator", "~> 0.6", require: false
```

The facade ships in the first release after 0.7.0, so raise that floor to that version once release-please cuts it.

```ruby
require "zer0_image_generator/facade" # the whole engine; stdlib only

missing = Zer0ImageGenerator::Facade.missing_previews("/sites/my-site")
missing.map(&:relative) # => ["_posts/2026-01-01-hello-world.md", "_docs/getting-started.md"]

result = Zer0ImageGenerator::Facade.generate_one(
  "/sites/my-site", missing.first.relative,
  provider: "local", env: {}, dry_run: false
)
result.status  # => :generated
result.preview # => "/images/previews/hello-world.png"
```

| Call | Returns |
| --- | --- |
| `missing_previews(site_root)` | an Array of `MissingPreview` (`path` absolute, `relative` to the site root, `collection`, `title`, `preview` — the stale front-matter value, or `nil`), in the order a run visits them |
| `generate_one(site_root, file, provider: "local", env: {}, dry_run: false)` | a `Generation`: `status` (`:generated`, `:would_generate`, `:skipped`, `:error`), `file`, `provider`, `preview` (the front-matter value after the run), `image` (its path on disk), `stats`, `exit_code`, `error`, `log` (`[[level, text], ...]`), and `ok?` |

The rules a caller can rely on:

- Caller mistakes raise `Zer0ImageGenerator::Facade::Error`, a subclass of `Zer0ImageGenerator::Error`. That covers a site root that is not a directory, a file that does not exist, and a path, `source:`, `collections_dir:` or `output_dir:` that resolves outside the site root, symlinks included.
- Engine outcomes come back as a `Generation` with status `:error` and are never raised: an unknown provider, a missing credential, a failed render.
- `file` may be absolute, relative to the content root (`source:`), or relative to the site root, tried in that order as the CLI does. `provider: nil` uses the site's configured provider.
- `env:` is the credential environment handed to the providers; the process `ENV` is never mutated, so concurrent jobs cannot leak keys into each other. Settings precedence is the CLI's own: the site's `preview_images:` block, overridden by the documented process env vars (`AI_PROVIDER`, `OUTPUT_DIR`, ...).
- Each call builds its own `Runner`, logger and run context. The run's log comes back in `result.log`; slice-level messages (front-matter writes, rasterizer notes) still go to `Zer0ImageGenerator::Logging.logger`, which the facade never swaps.

zer0-CMS's `ImageEngine` service is the only file there that requires the engine. Anything bigger than one page (batch runs, compositions, the studio) links out to this repo's web panel at `ZER0_IMAGE_GENERATOR_URL` (default `http://localhost:3000`).

### The design tokens

`web/app/assets/stylesheets/zer0-tokens.css` is the `zer0-ui-tokens` kit: the palette, radii, spacing, shadow and font stacks as CSS custom properties, dark-first with a `prefers-color-scheme: light` override, plus the `box-sizing` reset. It holds nothing component-level. Its first comment line carries the stamp `kit: zer0-ui-tokens <version>`.

- **Vendoring rule.** zer0-CMS copies the file byte-identically into its own `app/assets/stylesheets/` and themes Administrate through `var(--accent)`, `var(--bg-raised)` and the rest. Never edit a vendored copy: change the kit here, bump its version, and re-vendor. `cmp` or `shasum -a 256` against this file is the whole check.
- **Versioning.** Bump major when a token is removed or renamed, minor when a token is added, and patch when a value changes.
- **Cascade.** Everything sits in `@layer zer0-tokens`. Unlayered rules beat any layer regardless of load order, so an app's own stylesheet overrides a token without a specificity fight. Propshaft's `stylesheet_link_tag :app` links every `app/assets/**/*.css` sorted by path, which loads the kit after `application.css`.
- **Pending consolidation.** `application.css` in this app still declares its own copy of the tokens: identical today, so splitting them out changes nothing on screen. It keeps that copy until the in-flight edit to `application.css` lands. Then the copy there is deleted, and the kit, already linked by `:app`, becomes the only declaration. Until then `test/ruby/test_zer0_tokens.rb` fails the moment the two copies drift.

## Ports and compose

| App | Repo | Start | URL | Sites mount |
| --- | --- | --- | --- | --- |
| Image generator (forge, runs, studio) | zer0-image-generator | `docker compose up --build` at the repo root | http://localhost:3000 | `${SITES_DIR:-..}:/sites` |
| Fleet CMS (admin, editor, ABC wizard) | zer0-CMS | `docker compose up --build` at the repo root | http://localhost:3001 | `${SITES_DIR:-..}:/sites` |

- Both apps mount the **same** `SITES_DIR` at `/sites`, so a site registered as `/sites/<name>` means the same checkout in both. Register container paths, never host paths.
- The default `..` works when both repos sit side by side in one fleet checkout. Otherwise export `SITES_DIR` once (for example `export SITES_DIR=~/github`) before starting either app.
- `PORT` moves the host port of either app. If you move the image generator, point zer0-CMS's `ZER0_IMAGE_GENERATOR_URL` at the new address.
