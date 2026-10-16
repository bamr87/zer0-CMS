# SDLC / CI

Never push to `main`. Branch and open a PR.

This package lives in the zer0-CMS monorepo at `packages/zer0-image-generator/`, and only the root `.github/workflows/` runs (see the root `docs/MONOREPO.md`).

| Workflow | What green means |
|---|---|
| root `zer0-image-generator.yml` | Python engine tests (3.9 + 3.12), Ruby port byte-identity (`test/ruby/test_*.rb`), gem build, fixture-site generate with `local` — the old `test.yml`, run inside this package |
| root `markdown-oneline.yml` | One paragraph per line, for the whole repository |
| root `claude.yml` | `@claude` mentions; never merges |
| `.github/workflows/release.yml` (here) | Gem / tag — not yet ported, so it does not run from the monorepo; releases still happen from the original repository |

`bin/zer0 run test zer0-image-generator` from the repository root runs the same suite locally.

## Commands before a PR

```bash
python3 test/test_preview_generator.py
ruby -Ilib test/ruby/test_cli.rb          # then the rest of test/ruby/test_*.rb
ruby test/test_command.rb
cd web && bin/rails test
```

Python `preview_generator.py` is the oracle. A Ruby-only behavior change that Python does not share is a bug unless both move together.

Grok OAuth (`XAI_OAUTH_TOKEN` / Kilo `~/.local/share/kilo/auth.json`) is local-dev only — never commit `.env`.
