# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
