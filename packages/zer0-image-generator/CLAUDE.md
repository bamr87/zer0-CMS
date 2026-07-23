# CLAUDE.md

Guidance for AI coding agents (Claude Code, Copilot, Cursor) working in **zer0-image-generator**.

AI preview/social-image generation for any Jekyll site. It ships in three forms that share ONE behavior: the `jekyll preview-images` gem/CLI, the standalone Python engine (`lib/zer0_image_generator/preview_generator.py`), and a Dockerized Rails web app (`web/`). The web app drives a **pure-Ruby port** of the engine under `lib/zer0_image_generator/*.rb`; that port is pinned **byte-for-byte** against the Python original (see below). "Done" means all three stay in lockstep and the byte-identity tests stay green.

## Stack & commands

```bash
# engine port (pure-Ruby) tests — byte-identity vs the Python oracle:
ruby -Ilib test/ruby/test_*.rb          # 327 tests / 9.6k assertions
# original Python engine tests:
python3 test/test_preview_generator.py  # zero network
# the gem's CLI translation layer:
ruby test/test_command.rb
# the web app:
cd web && bin/rails test                # models, services, requests, jobs
SITES_DIR=.. docker compose up --build  # run the app → localhost:3000
```

## The pure-Ruby port (`lib/zer0_image_generator/*.rb`)

- The Python file `preview_generator.py` is the **oracle**, not scratch — never
  edit it as part of a port change; port TO Ruby and diff against it.
- Determinism is a hard contract: the generators reproduce every committed
sample in `docs/samples/` exactly. Ruby's built-in `Random` does NOT match CPython — always route seeded randomness through `Zer0ImageGenerator::Support::PyRandom` (a bit-exact MT19937 + CPython seeding). Draw values in the same order as the Python.
- The engine is stdlib-only by policy (no Nokogiri/ActiveSupport in `lib/`).
- The web app loads the engine via `lib/zer0_image_generator/all.rb` and drives
the same `Runner` the CLI drives, through the single seam `web/app/services/engine_bridge.rb`. Keep engine-coupling in that one file.

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`).
- Default branch is `main` — branch from it and open a PR; never push to it directly.
- README-First, README-Last: read the nearest `README.md` before changing a
  directory, and update it after.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or
  leave empty exception handlers.
- SVG work (banner template, sanitizer, any `.svg`): use the authoring loop in `tools/svg/` — the PostToolUse hook lints + renders every `.svg` write; read the PNG before editing further. Playbook: `.claude/skills/svg-art`.

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents.
