# SDLC / CI

Every project in this repository is gated on its own terms: the VS Code extension (`src/`), the Rails fleet CMS (`rails/`), and the theme, image generator, books app, sites and barodybroject app imported under `packages/`, `sites/` and `apps/`. Each has one root workflow filtered to its own tree (named in its `ci:` entry in `workspace.yml`), and `zer0-workspace.yml` checks on every pull request that the registry and the tree still agree ([`MONOREPO.md`](MONOREPO.md)). `main` is not branch-protected and no check is required; still never push to it — branch and open a PR. Every workflow here declares `permissions: contents: read` at the top (a job widens it only where it must write) and a `concurrency` group — except the called `zer0-linkedin.yml`, which declares no permissions so that its caller's grant applies (`contents: write` to publish or read statistics, `contents: read` to check a token), and sets its concurrency per job.

## The workflows

| Workflow | Runs on | What green means |
|---|---|---|
| `extension.yml` | PR and push to `main`, unless every changed file is under `rails/**`, `packages/**`, `sites/**` or `apps/**`, or is `docker-compose.yml` | `npm ci`, type-check, lint, the five bundles, the VS Code test host under `xvfb-run`, `tools/check-config-docs.py`, `vsce package`, and the packaged file list diffed against `.vsix-manifest.txt`; the vsix is uploaded as an artifact named by commit |
| `abc-engine.yml` | PR and push to `main` touching `rails/**` or the workflow | `rails/bin/test-stdlib` — every `rails/test/zer0_cms/test_*.rb` — with **no** `bundle install`, on Ruby 3.3 and 4.0.5 (matrix, `fail-fast: false`) |
| `rails-app.yml` | PR and push to `main` touching `rails/**`, `docker-compose.yml` or the workflow | With the bundle (from `rails/.ruby-version` and `rails/Gemfile.lock`) and PyYAML: `bin/rails test`, `bin/rails zeitwerk:check`, then a production boot — `assets:precompile`, `db:prepare`, `bin/rails server` — that must answer `/up` and `/admin/sites` |
| `zer0-image-generator.yml` | PR and push to `main` touching `packages/zer0-image-generator/**` or the workflow | The package's old `test.yml`, run inside the package: the Python engine's unit tests on 3.9 and 3.12, the Ruby port's byte-identity tests against it, a gem build that must contain the engine and the rasterizer helper, and the fixture site's `jekyll preview-images` run with the deterministic `local` provider (real PNGs, idempotent second run) |
| `zer0-pages.yml` | PR and push to `main` touching `sites/zer0-pages/**` or the workflow | The site's Obsidian-bridge and graph-index minitest suites, its SCHEMA.md pyramid lint (`tools/schema_lint.py check .`) and a themed `bundle exec jekyll build` |
| `zer0-workspace.yml` | every PR and push to `main` | `tools/workspace/test/*.rb`, then `bin/zer0 check` (every directory under `packages/`, `sites/`, `apps/` registered; paths, workflows and vendored copies consistent); writes the affected projects and a report-only `bin/zer0 doctor` of every site to the job summary |
| `zer0-mistakes.yml` | PR and push to `main` touching `packages/zer0-mistakes/**` or the workflow | The theme's PR gate, ported from its own `ci.yml` with the composite actions inlined: version ↔ `Gemfile.lock` and ↔ theme manifest, `test/test_quality.sh`, the markdown-format check, `scripts/bin/validate --quick`; the core/quality/obsidian/features suites and `scripts/bin/test`; the Playwright `critical` tier; then a gem build that must install |
| `sites.yml` | PR and push to `main` touching `sites/zer0-pages-remote/**`, `sites/zer0-demo-cookbook/**`, `sites/zer0-demo-garden/**` or the workflow | `bundle exec jekyll build` for each changed site (a matrix planned by `bin/zer0 affected`) |
| `barodybroject.yml` | PR and push to `main` touching `apps/barodybroject/**` or the workflow | Django pre-checks and pytest on Python 3.10–3.12 against PostgreSQL, the frontend typecheck, Vitest and build, and lint, dependency-scan and quality analysis — all through the app's own `.github/scripts/*.sh` |
| `books.yml` | PR and push to `main` touching `packages/books/**` or the workflow | The bookshelf app's `pytest` and `ruff check src tests` on Python 3.10 and 3.12 |
| `drsai.yml` | PR and push to `main` touching `sites/drsai/**`, `packages/zer0-mistakes/**` or the workflow | The story engine's ruff, black and pytest on Python 3.10–3.12; `tools/import_abc_book.py --check` and the prose gate; and a Jekyll build of the site with `ZER0_THEME_LOCAL=../../packages/zer0-mistakes`, so a theme change that breaks drsai is caught on the theme's pull request |
| `zer0-doctor.yml` | `workflow_call` from a content repository; `workflow_dispatch` here | The zer0 stack consumer contract check on the caller's site (below); fails only when asked to |
| `zer0-linkedin.yml` | `workflow_call` from a content repository | The LinkedIn distribution lane on the caller's site at its branch tip, with no bundle: `publish` (a rehearsal, or live with `ZER0_LINKEDIN_PUBLISH=1` set for that one step; `ZER0_LINKEDIN_MERGED=1` on the default branch), `status` (fails on a dead token or one within `warn-days` of expiry) or `stats`; commits the ledger, the queue and `performance.json` back with `[skip ci]` and uploads them as `zer0-linkedin-results`; skips with a notice when the caller has no LinkedIn credential. Contract: [`DISTRIBUTION.md`](DISTRIBUTION.md#ci-the-reusable-workflow) |
| `ci.yml` | every PR and push to `main` | The hub's shared `standard-ci.yml` (a thin caller; the logic lives in bamr87/bamr87) |
| `markdown-oneline.yml` | PR and push to `main` touching markdown | On a same-repo PR it runs `tools/unwrap-prose.py --write` and pushes the repair to the PR branch; on a fork PR or a push to `main` it fails with the fix command instead |
| `codeql-analysis.yml` | push and PR to `main`, weekly (Fridays 14:24 UTC) | CodeQL over `javascript-typescript` and `ruby`, both `build-mode: none` |
| `release.yml` | push to `main` | The hub's release-please workflow maintains the release PR; when that PR merges, the repo-owned `marketplace` job packages the vsix at the tag, attaches it to the GitHub Release, and publishes to the Marketplace and Open VSX when their tokens exist (see [`RELEASING.md`](RELEASING.md)) |
| `claude.yml` | `@claude` in an issue, comment or review | The mention handler (`anthropics/claude-code-action@v1`), one run per thread; it never merges |

A change to `rails/` runs `abc-engine.yml` and `rails-app.yml` and not `extension.yml`; a change to `src/` runs `extension.yml` and neither Ruby workflow. The two Ruby workflows are split on purpose: `abc-engine.yml` proves the library under `rails/lib` needs no gem, and `rails-app.yml` is allowed the bundle. Do not add `bundle install` to `abc-engine.yml`; a gem reached from `lib/` is the bug that job exists to catch.

Nothing in CI builds the Docker image. `rails-app.yml` boots the app in the same `RAILS_ENV` and asset pipeline the image runs, and the image itself is verified by hand before a change to `rails/Dockerfile` or `docker-compose.yml` merges (the commands are below).

## The reusable doctor

`zer0-doctor.yml` is how a content repository runs `zer0 doctor` (the consumer contract, [`ZER0-STACK.md`](ZER0-STACK.md)) without vendoring anything:

```yaml
jobs:
  doctor:
    uses: bamr87/zer0-CMS/.github/workflows/zer0-doctor.yml@main
    with:
      site-path: "."          # the Jekyll root, relative to the caller repository
      fail-on-error: false    # report-only unless set
```

It checks out the caller repository and `bamr87/zer0-CMS` at `main` side by side, runs `ruby -I zer0-cms/rails/lib zer0-cms/rails/bin/zer0-cms doctor <site> --format findings` on plain Ruby 3.3 (the doctor is stdlib-only), writes a job summary — errors and non-content warnings as a table, content warnings counted per rule — and uploads the findings JSONL as the `zer0-doctor-findings` artifact. The job fails only when `fail-on-error` is true and the doctor reported an error, or when `site-path` is absolute, climbs out of the checkout, or is not a directory. The content repositories' callers run it on `workflow_dispatch` and a weekly schedule, never on `pull_request`, so a doctor change here cannot redden their pull requests.

## Commands to run before a PR

```bash
# extension
npm run compile && npm test
python3 tools/check-config-docs.py

# rails/lib — stdlib only, no bundler (what abc-engine.yml runs)
cd rails && bash bin/test-stdlib

# the Rails app (what rails-app.yml runs)
cd rails && bundle install && bin/rails test && bin/rails zeitwerk:check

# the image, when rails/Dockerfile or docker-compose.yml changed
docker compose -p zer0cms-check build cms
PORT=3021 docker compose -p zer0cms-check up -d cms
curl -fsS http://localhost:3021/up && curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:3021/admin/sites
docker compose -p zer0cms-check down -v --rmi local

# one paragraph per line
python3 tools/unwrap-prose.py --check
```

The image-engine tests run the locked `zer0-image-generator` gem's Python engine and skip without python3 and PyYAML. With `ZER0_IMAGE_GENERATOR_LIB` pointing at an image generator checkout's `lib/` that ships `Zer0ImageGenerator::Facade`, the facade path runs too.

## Specs that CI actually pins

- **Reader parity:** `rails/test/fixtures/jekyll-site` and its expected lists, generated by Jekyll 4.4.1 itself (`rails/bin/jekyll-parity`); `test_catalog.rb`.
- **Front-matter surgery:** `test_front_matter.rb` (table-driven) and, over the app, `test/integration/page_editing_test.rb` (an unchanged save of every indexed file writes nothing; a stale file is refused).
- **Confined writes:** `test_writer.rb`; `test/integration/files_test.rb` and `security_test.rb` (host allow-list, basic auth, loopback-only, CSP nonce, `/files` confinement).
- **Doctor:** `test_doctor.rb`.
- **ABC Book Spec:** `rails/schema/abc-book.schema.json` + `test_abc_engine.rb` and `test/integration/abc_books_test.rb`.
- **Image-engine bridge:** `test/integration/image_engine_test.rb`, `test/services/image_engine_settings_test.rb`.
- **Extension goldens** under `src/test/fixtures/golden/` — regenerate with their generators, never hand-edit.
