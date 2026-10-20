# SDLC / CI

Never push to `main`. Branch and open a PR.

| Workflow | What green means |
|---|---|
| `test.yml` | Python engine tests (3.9 + 3.12), Ruby port byte-identity (`test/ruby/test_*.rb`), gem build, fixture-site generate with `local` |
| `ci.yml` | Hub `standard-ci.yml` (shared baseline) |
| `markdown-oneline.yml` | One paragraph per line |
| `release.yml` | Gem / tag |
| `claude.yml` | `@claude` mentions; never merges |

## Commands before a PR

```bash
python3 test/test_preview_generator.py
ruby -Ilib test/ruby/test_cli.rb          # then the rest of test/ruby/test_*.rb
ruby test/test_command.rb
cd web && bin/rails test
```

Python `preview_generator.py` is the oracle. A Ruby-only behavior change that Python does not share is a bug unless both move together.

Grok OAuth (`XAI_OAUTH_TOKEN` / Kilo `~/.local/share/kilo/auth.json`) is local-dev only — never commit `.env`.
