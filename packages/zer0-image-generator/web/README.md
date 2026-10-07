# web — the zer0-image-generator control panel

A Rails 8 app that puts the whole engine behind a browser. The dashboard and sidebar expose every surface — nothing is URL-only:

- **Sites** — register Jekyll sites (or import whatever is mounted under
`/sites`), scan missing previews, edit `preview_images:` config, and run generation (dry-run / list-missing / generate / enhance) with a live-streaming log. Site pages share Overview / Content / Config / Runs tabs; any content file can queue a single-file generate.
- **Image forge** — create a standalone image interactively: Claude reads your
brief and directs the art, a renderer produces it, Claude reviews it, and you can then process any version further with OpenAI. Not tied to a site.
- **SVG studio** — drive the parametric `tools/svg/` generators from knob forms
with live render + inline lint, save/favorite, reopen a saved recipe, and queue seed sweeps.
- **Library** — browse the curated `tools/svg/library/` with provenance, search
  and tag-filter, and source new pieces from **FreeSVG.org**.
- **Runs** — cross-site audit trail, filterable by kind and status.
- **Credentials** — encrypted per-provider keys, including the Claude Code OAuth
  token that powers the art-direction/review stages.

## One engine, in Ruby

The image engine was ported from the single Python file to pure Ruby under [`../lib/zer0_image_generator/`](../lib/zer0_image_generator/). The app loads it off `$LOAD_PATH` (see [config/application.rb](config/application.rb)) and drives the same `Runner` the CLI drives — there is exactly one engine, so the web app and the CLI can never diverge. The port is pinned byte-for-byte against the Python original: the generators reproduce every committed sample in `docs/samples/` exactly (see [`../test/ruby/`](../test/ruby/), 327 tests / 9.6k assertions), backed by a bit-exact reimplementation of CPython's Mersenne Twister in [support/py_random.rb](../lib/zer0_image_generator/support/py_random.rb).

## Run it

```bash
# From the repository root:
SITES_DIR=/path/to/your/jekyll/sites docker compose up --build
# → http://localhost:3000
```

`SITES_DIR` is bind-mounted into the container at `/sites`; register a site using its **container** path (e.g. `/sites/my-blog`). Provider keys can be set in the UI (encrypted at rest) or exported into the container's environment. Every AI-using job (generation, forge, enhance) reads the same snapshot (`AiEnv`): process ENV, then stored credentials. `CLAUDE_CODE_OAUTH_TOKEN` drives Claude art direction; `OPENAI_API_KEY` drives rendering and enhance. The Grok OAuth token (`XAI_OAUTH_TOKEN` / **xai_oauth** slot) authenticates the xAI renderer *and* Grok art-direction/review when `prompt_engine` / `review_engine` is `xai`. `XAI_API_KEY` is the renderer fallback. The `local` provider needs no keys and is fully deterministic.

Without Docker:

```bash
cd web
bundle install
bin/rails db:prepare
SOLID_QUEUE_IN_PUMA=true bin/rails server
```

Requires a rasterizer for the `local` provider and studio PNGs — the Docker image ships `librsvg2-bin` and ImageMagick; locally, `brew install librsvg`.

## What's where

| Area | Files |
| --- | --- |
| Engine seam | [app/services/engine_bridge.rb](app/services/engine_bridge.rb) — the only place that knows the engine's module layout |
| Preview runs | [app/jobs/generation_job.rb](app/jobs/generation_job.rb), [app/controllers/runs_controller.rb](app/controllers/runs_controller.rb), [app/services/run_log_sink.rb](app/services/run_log_sink.rb) (streams the log over Turbo) |
| Image forge | [app/services/forge.rb](app/services/forge.rb) (analyze → produce → review → enhance), [app/jobs/compose_job.rb](app/jobs/compose_job.rb), [app/jobs/enhance_job.rb](app/jobs/enhance_job.rb) |
| Site scan / config | [app/services/site_scanner.rb](app/services/site_scanner.rb), [app/services/site_config_editor.rb](app/services/site_config_editor.rb) (surgically rewrites just the `preview_images:` block) |
| SVG studio | [app/services/studio_catalog.rb](app/services/studio_catalog.rb) (knob metadata), [app/services/studio_renderer.rb](app/services/studio_renderer.rb) (maps forms → generators), [app/jobs/sweep_job.rb](app/jobs/sweep_job.rb) |
| Library / sourcing | [app/services/library_sync.rb](app/services/library_sync.rb), [app/services/freesvg_source.rb](app/services/freesvg_source.rb) |
| AI env | [app/services/ai_env.rb](app/services/ai_env.rb) — single credential snapshot for generation, forge, and enhance |
| Credentials | [app/models/credential.rb](app/models/credential.rb) — encrypted; renderer keys, the xAI ladder (Grok OAuth token → API key) and the Claude credential chain (OAuth token → auth token → API key) |

## Data model

- **Site** — a Jekyll site on disk, registered by path.
- **Run** — one engine invocation (generate / dry_run / list_missing / enhance /
  studio / sweep), with its parameters, streamed log, and stats.
- **Artifact** — an image a run wrote, recorded by path (the bytes stay in the
  site's assets, not the app).
- **Composition** / **CompositionImage** — an image-forge session and its
versions (render / Claude revision / OpenAI enhanced), each recording how it was produced.
- **StudioRender** — a saved generator piece: generator + params + seed
  reproduce it exactly.
- **LibraryEntry** — a projection of `tools/svg/library/MANIFEST.json`.
- **Credential** — an encrypted provider key or Claude OAuth token.

## Tests

```bash
cd web && bin/rails test            # app models, services, requests
ruby -Ilib ../test/ruby/test_*.rb   # the engine port (byte-identity)
```

## Safety notes

- Generation writes into your site in place and rewrites front matter — the
  engine leaves no `.bak` files and dry-run writes nothing (both asserted).
- [app/controllers/files_controller.rb](app/controllers/files_controller.rb)
serves generated images only after confirming the resolved path is inside a registered site or the scratch dir — the allow-list is the security boundary.
- Host authorization is relaxed to loopback/private ranges in development so a
  Docker-published port is reachable, without opening it to arbitrary hosts.
