---
name: run-zer0-image-generator
description: Build, run, test, and drive zer0-image-generator — the AI preview-banner Jekyll plugin/engine. Use to run the smoke harness, launch `jekyll preview-images` against the fixture site, generate real banners with a provider key, or verify a change end-to-end.
---

# Run zer0-image-generator

A Ruby gem (`jekyll preview-images` command) wrapping a single-file Python
engine (`lib/zer0_image_generator/preview_generator.py`) that generates AI
preview banners for Jekyll sites and wires `preview:` front matter. There is
no GUI/server: the app IS the CLI, and the way to drive it is the committed
smoke harness plus the fixture site. All paths below are relative to the repo
root.

## Prerequisites

- `python3` (3.9+) with PyYAML — the engine. `python3 -m pip install pyyaml`
  if missing.
- Ruby ≥ 2.7 + bundler for the gem CLI path. On macOS the **system Ruby 2.6
  cannot run the CLI** (it can `gem build`, nothing more) — use
  `export PATH="/opt/homebrew/opt/ruby/bin:$PATH"` (Homebrew Ruby 4.x works;
  the fixture pins jekyll ~> 4.3 which runs fine there).
- No rasterizer is required: without `rsvg-convert`/`inkscape`/`magick` the
  local provider keeps `.svg` banners (a documented fallback the harness
  accepts). `brew install librsvg` upgrades output to PNG.

## Run (agent path) — the smoke harness

This is the primary way to verify the app works end-to-end. It runs the unit
suites, copies `test/fixture-site/` to a temp dir (repo stays clean), drives
the **real** `bundle exec jekyll preview-images` CLI through list-missing →
dry-run → generate (free deterministic `local` provider, no keys, no network)
→ idempotent rerun, and asserts files + front matter at each stage:

```bash
export PATH="/opt/homebrew/opt/ruby/bin:$PATH"   # macOS: skip system Ruby 2.6
.claude/skills/run-zer0-image-generator/smoke.sh          # ~60s, exit 0 = pass
.claude/skills/run-zer0-image-generator/smoke.sh --keep   # keep the tmp site to poke at
```

With `--keep`, cd into the printed tmp site and drive the CLI directly:

```bash
cd <printed tmp>/site && export BUNDLE_PATH=<printed tmp>/bundle
bundle exec jekyll preview-images --list-missing
bundle exec jekyll preview-images --provider local --force -f _posts/2026-01-01-hello-world.md
```

Generated banners land in `assets/images/previews/`; front matter gets
`preview: /images/previews/<slug>.(png|svg)`.

## Direct invocation (the layer most PRs touch)

The engine is pure Python + PyYAML; the Ruby layer is a thin argv translator.
Both have zero-network unit suites:

```bash
python3 test/test_preview_generator.py    # 108 tests, <1s
ruby test/test_command.rb                 # 5 tests — Mercenary→argv translation
```

The engine also runs standalone against any Jekyll site (no Ruby at all) —
cwd must be (or be under) a dir whose root has `_config.yml`:

```bash
python3 lib/zer0_image_generator/preview_generator.py --list-missing
```

## Real renders (needs a key)

The `local` provider is deterministic and free. For actual AI banners, run
from a real site with the gem installed and a key in the environment or a
`.env` at the site root (the engine loads it):

```bash
OPENAI_API_KEY=... bundle exec jekyll preview-images --provider openai -f <file.md>
```

Claude orchestration (art brief + vision review) engages automatically when
any of `CLAUDE_CODE_OAUTH_TOKEN` / `ANTHROPIC_AUTH_TOKEN` / `ANTHROPIC_API_KEY`
or a logged-in `claude` CLI is present, and degrades to template prompts
without one. Batches: use ONE `--collection <name>` invocation (4 parallel
workers, `--parallel N` to change) — a per-file `-f` loop is serial and pays
process startup per file.

## Build the gem

```bash
gem build zer0-image-generator.gemspec    # works even on system Ruby 2.6
```

Releases go through release-please + the shared publish workflow
(`.github/workflows/release.yml`); manual publish is `gem push <file>.gem`
with `~/.gem/credentials`.

## Gotchas

- **The fixture Gemfile pins the gem by relative path** (`path: "../.."`),
  so a copied fixture site breaks bundler until the path is rewritten to the
  absolute repo path — the smoke harness does this with `sed`.
- **`--dry-run` writing files is the bug signature of Mercenary flag
  dropping** (fixed in 0.2.2: options are keyed by *symbol*, not string, in
  `command.rb`). The harness asserts dry-run writes nothing specifically to
  catch regressions here — CI's end-state assertions alone missed it.
- **Jekyll's `source:` key** re-roots all disk paths (0.2.0,
  `apply_source_root`): on a `source: pages` site, banners land in
  `pages/assets/...` while front matter keeps the `/images/previews/...` URL
  form. The fixture site has no `source:`, so don't use it to test that path
  — use a site like zer0-pages.
- **No rasterizer → `.svg` output with a WARNING**, not an error. The SVG is
  a real 10KB deterministic template banner. Front matter then points at
  `.svg` — fine for browsers, weak for og:image.
- **System Ruby 2.6 (macOS)**: `bundle exec jekyll` dies on `cannot load
  such file -- csv` or `tainted?` errors. Not the gem's fault — put Homebrew
  Ruby first on PATH.
- **The engine finds the site root by walking up from cwd** looking for
  `_config.yml` — running from an unrelated directory scans nothing and
  reports 0 files, silently.

## Troubleshooting

- `Could not find gem 'zer0-image-generator ... path: ../..'` → you copied
  the fixture without rewriting the Gemfile path (see Gotchas).
- `OPENAI_API_KEY environment variable is required` on `--list-missing` or
  `--dry-run` → you are on gem ≤ 0.2.1 (flags never reached the engine).
  Upgrade; the smoke harness fails stage 4 on such a build.
- `preview-images: python3 not found` → the Ruby layer probes `python3`
  (`PYTHON=/path/to/python3` overrides).
- HTTP 429 from a provider mid-batch → normal; the engine retries with
  backoff honoring `Retry-After`. A long quiet spell in a batch is usually
  this, not a hang.
