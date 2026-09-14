# SDLC / CI

Two products, two gates, one repo. `main` is not a required-check merge wall here; still never push to it — branch and open a PR.

| Workflow | When | What green means |
|---|---|---|
| `extension.yml` | PR/push that is **not** only `rails/**` | Type-check, lint, five bundles, VS Code test host (xvfb) |
| `abc-engine.yml` | PR/push that touches `rails/**` | Every stdlib test in `rails/test/zer0_cms/test_*.rb` with **no** `bundle install` |
| `ci.yml` | every PR/push | Hub `standard-ci.yml` (markdown one-line, shared baseline) |
| `markdown-oneline.yml` | markdown changes | `python3 tools/unwrap-prose.py --check` |
| `codeql-analysis.yml` | scheduled / push | CodeQL |
| `release.yml` | tags | VS Code Marketplace / vsix |
| `claude.yml` | `@claude` mentions | Mention handler only; never merges |

## Commands to run before a PR

```bash
# extension
npm run compile && npm test

# rails stdlib (ABC + CMS catalog/front-matter/writer)
cd rails && ./bin/test-stdlib

# one-line markdown
python3 tools/unwrap-prose.py --check
```

Do not add `bundle install` to `abc-engine.yml`. If a new CMS primitive needs a gem, it belongs in `app/`, not `lib/`.

The Dockerized Rails app (`docker compose up`) is a local/dev surface, not a required CI job. Keep it bootable: `rails/bin/db-prepare` must create `sites` on a blank volume.

## Specs that CI actually pins

- ABC Book Spec: `rails/schema/abc-book.schema.json` + `test_abc_engine.rb`
- Front-matter surgery: `test_front_matter.rb`
- Catalog walk of `collections_dir` + `_posts`: `test_catalog.rb`
- Writer dated-post path: `test_writer.rb`
- Extension goldens under `src/test/fixtures/golden/` — regenerate, never hand-edit
