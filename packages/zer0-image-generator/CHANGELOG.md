# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-07-15

### Added

- `claude_effort` knob (default `low`): the Claude art-brief and vision-review
  calls now send `output_config: {effort: ...}` — short creative tasks don't
  need deep reasoning, and `low` substantially cuts per-image orchestration
  latency. Configurable per site (`preview_images.claude_effort`); `''`
  disables. Gracefully retries without the parameter on models that reject it.

### Changed

- README documents the batch-performance contract: one `--collection` run
  parallelizes across files (`--parallel N`, default 4); per-file loops don't.

## [0.3.0] - 2026-07-14

### Added

- Per-collection style/theme overrides: a `collection_styles:` map under
  `preview_images:` lets each collection (`posts`, `docs`, `hacks`, …) carry
  its own `style`, `style_modifiers`, `size`, `quality`, and `model` — so
  field notes, docs, and hacks render with distinct visual identities. A
  file's collection is derived from its `_<name>` directory; precedence is
  author overrides → collection styles → CLI flags → env → config → defaults.

## [0.2.2] - 2026-07-14

### Fixed

- `jekyll preview-images` CLI flags were silently dropped: Mercenary keys the
  options hash by the symbol given to `c.option`, but the argv translator
  looked up the string form — so `--dry-run`, `--list-missing`,
  `--provider`, etc. never reached the engine. Added a Ruby unit test for the
  translation and a CI assertion that `--dry-run` writes nothing.

## [0.2.1] - 2026-07-13

### Fixed

- `--file` on `source:` sites now accepts repo-root-relative paths
  (`pages/_notes/x.md`) as well as source-relative ones (`_notes/x.md`).

## [0.2.0] - 2026-07-13

### Added

- Honor Jekyll's top-level `source:` key: on sites like
  [zer0-pages](https://github.com/bamr87/zer0-pages) (`source: pages`), the
  engine now resolves collections, the output directory, `_data/authors.yml`,
  and existence checks inside the source dir automatically — front-matter
  values keep their site-URL form (`/images/previews/…`), so no path
  configuration is needed.

## [0.1.0] - 2026-07-13

### Added

- Initial extraction of the AI preview-image engine from the
  [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme
  (`scripts/lib/preview_generator.py`, PR bamr87/zer0-mistakes#296) as a
  standalone, portable project.
- `zer0-image-generator` Ruby gem: a `jekyll preview-images` command
  (`Jekyll::Command`) that launches the vendored single-file Python engine —
  the Ruby layer is a thin argv translator so gem and standalone usage can
  never drift.
- Universality knobs (all new, all with zer0-compatible defaults):
  - `collections_dir` — honored from Jekyll's own top-level key, the
    `preview_images:` block, or `--collections-dir` (the theme hardcoded
    `pages/`).
  - `front_matter_key` — read/write any key (`preview` default; `image` for
    jekyll-seo-tag sites) via config or `--front-matter-key`.
  - `authors_file` — per-author style overrides from any YAML path; empty
    disables (was hardcoded `_data/authors.yml`).
  - `collections: auto` — discover collections from Jekyll's `collections:`
    map instead of listing them.
- Vendored Playwright SVG→PNG rasterizer helper next to the engine (gem
  layout), keeping the rsvg → inkscape → magick → playwright chain intact.
- Unit suite (98 tests, zero network) plus a standard-layout fixture site
  exercised end-to-end in CI with the free `local` provider.

### Changed

- Default `collections` is now `[posts]` (universal) instead of the theme's
  `[posts, quickstart, docs]` — zer0-mistakes lists its collections
  explicitly, so theme behavior is unchanged when it adopts this engine.
- `resolve_settings(args, config)` now takes the FULL `_config.yml` dict
  (it extracts the `preview_images:` block itself) so top-level Jekyll keys
  (`collections_dir`, `collections`) can participate in resolution.
