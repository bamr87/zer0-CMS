# Fleet CMS platform (`rails/`)

The VS Code extension in `src/` edits one workspace. The Rails app in `rails/` is the **fleet control panel**: it registers every zer0-themed Jekyll site under `/sites`, lists and edits markdown in place, and still hosts the ABC book wizard.

This document is the contract for continued development of that panel. The extension architecture (D1–D14) stays in [`ARCHITECTURE.md`](ARCHITECTURE.md).

## Two surfaces, one disk

| Surface | Process | Writes |
|---|---|---|
| VS Code extension | Extension Host | Front-matter line surgery via `updateFrontMatterKeys` |
| Rails CMS | Puma in Docker (`:3001`) | Front-matter line surgery via `Zer0Cms::Cms::FrontMatter.update_keys` |

Both operate on the same files. Neither owns a copy of the content. A save in the browser is a save on disk; the editor sees it on the next read.

Do not fold the extension into Rails. Do not call the Rails app "the content engine" — that name is `.cms/` in `src/core/contract/`.

## Layout

```
rails/
  lib/zer0_cms/abc/     ABC generator (stdlib-only; CLI + tests; no gems)
  lib/zer0_cms/cms/     Catalog, front-matter surgery, writer (stdlib-only)
  app/                  Rails host: HTTP, SQLite site registry, Hotwire UI
  schema/               Interchange specs (ABC Book Spec, …)
```

Gems (Rails, Puma, sqlite3, Hotwire, Pagy, Kramdown) stay in `app/` + `Gemfile`. A gem required from `lib/` is a CI failure: `abc-engine.yml` runs `rails/bin/test-stdlib` with no `bundle install`.

## Product surface (browser)

The UI follows zer0-image-generator (sidebar, tokens, tabs). Required routes:

- `/` dashboard — registered sites, unregistered `/sites` roots, ABC entry
- `/search` — fleet-wide title/path/author/tag search
- `/sites` — register, import-all, filter
- `/sites/:id` — overview counts + recent files
- `/sites/:id/pages` — collection/status/tag/author filters, pagination, create
- `/sites/:id/pages/item?file=` — preview art, markdown render, front-matter form, duplicate, delete
- `/sites/:id/media` — images under `assets/` and `images/`
- `/sites/:id/taxonomy` — tags, categories, authors
- `/sites/:id/config` — read-only `_config.yml`
- `/abc/new` — ABC wizard (preview / export)

Hotwire (Turbo + Stimulus via importmap) is the JS stack. Do not add Webpack or a CSS framework.

## On-disk contracts

- **Jekyll root** — a directory with `_config.yml`. `collections_dir` / `source` are honoured. Collection folders are `_<name>/`.
- **Front matter** — YAML between `---` fences. Updates rewrite only changed keys; comments and untouched lines stay byte-identical; dates stay strings.
- **New posts** — `YYYY-MM-DD-<slug>.md` under the posts collection directory.
- **ABC Book Spec** — [`rails/schema/abc-book.schema.json`](../rails/schema/abc-book.schema.json). Art-style ids are a byte-identical vendored copy of zer0-image-generator's catalog.

## SDLC

See [`CICD.md`](CICD.md). Green `abc-engine` means every `rails/test/zer0_cms/test_*.rb` passed without bundler. Green `extension` means the VS Code half compiled and tested. A `rails/`-only PR should not download VS Code.

## Local run

```bash
SITES_DIR=/path/to/github docker compose up --build   # http://localhost:3001
```

Sites are container paths (`/sites/lifehacker.dev`). The SQLite registry lives in the `sqlite` volume; deleting a Site row does not delete files.
