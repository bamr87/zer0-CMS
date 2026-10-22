# SDLC / CI

Every project in this repository is gated on its own terms: the VS Code extension (`src/`), the Rails fleet CMS (`rails/`), the platform (`content/`), and the image generator, books app, sites and the parodynews and aieo apps imported under `packages/`, `sites/` and `apps/`. The zer0-mistakes theme the sites build with is gated in its own repository ([ADR 0005](adr/0005-theme-goes-home.md)). Each has one root workflow filtered to its own tree (named in its `ci:` entry in `workspace.yml`), and `zer0-workspace.yml` checks on every pull request that the registry and the tree still agree ([`MONOREPO.md`](MONOREPO.md)). `main` is not branch-protected and no check is required; still never push to it — branch and open a PR. Every workflow here declares `permissions: contents: read` at the top (a job widens it only where it must write) and a `concurrency` group — except the called `zer0-linkedin.yml`, which declares no permissions so that its caller's grant applies (`contents: write` to publish or read statistics, `contents: read` to check a token), and sets its concurrency per job.

## The workflows

| Workflow | Runs on | What green means |
|---|---|---|
| `extension.yml` | PR and push to `main`, unless every changed file is under `rails/**`, `packages/**`, `sites/**`, `apps/**`, `content/**`, `web/**` or the content plane's schemas (`schemas/{events,graphql,content}/**`), or is `docker-compose.yml` | `npm ci`, type-check, lint, the five bundles, the VS Code test host under `xvfb-run`, `tools/check-config-docs.py`, `vsce package`, and the packaged file list diffed against `.vsix-manifest.txt`; the vsix is uploaded as an artifact named by commit |
| `content.yml` | PR and push to `main` touching `content/**`, `schemas/events/**`, `schemas/graphql/**`, `schemas/content/**`, `schemas/openapi/**` or the workflow | Two jobs, both inside `content/`. **sqlite** (Python 3.12 and 3.13): ruff lint and format, `makemigrations --check`, the full pytest suite (including the byte-for-byte round trips of zer0-pages and of the theme's docs site, checked out at a pinned tag into `.cache/zer0-mistakes` — that case skips where the checkout is absent), the committed GraphQL SDL, agent schema and OpenAPI document unchanged, and every agent's eval suite on the recorded models (`run_evals --all --recorded`). **postgres**: the fast tier against `pgvector/pgvector:pg16` and `redis:7`, where the vector column, `<=>` kNN and `SKIP LOCKED` are real. No job calls a model provider |
| `web.yml` | PR and push to `main` touching `web/**`, `schemas/openapi/**` or the workflow | Inside `web/` on Node 24: `npm ci` (the committed lockfile), ESLint (including the gate that keeps `@zer0/ui` free of routers, transports and page globals), `tsc --noEmit`, the Vitest suites, `npm run check:api` (the generated client regenerated from the committed OpenAPI document must equal `packages/api/src/schema.d.ts`) and the studio's production build |
| `abc-engine.yml` | PR and push to `main` touching `rails/**` or the workflow | `rails/bin/test-stdlib` — every `rails/test/zer0_cms/test_*.rb` — with **no** `bundle install`, on Ruby 3.3 and 4.0.5 (matrix, `fail-fast: false`) |
| `rails-app.yml` | PR and push to `main` touching `rails/**`, `docker-compose.yml` or the workflow | With the bundle (from `rails/.ruby-version` and `rails/Gemfile.lock`) and PyYAML: `bin/rails test`, `bin/rails zeitwerk:check`, then a production boot — `assets:precompile`, `db:prepare`, `bin/rails server` — that must answer `/up` and `/admin/sites` |
| `zer0-image-generator.yml` | PR and push to `main` touching `packages/zer0-image-generator/**` or the workflow | The package's old `test.yml`, run inside the package: the Python engine's unit tests on 3.9 and 3.12, the Ruby port's byte-identity tests against it, a gem build that must contain the engine and the rasterizer helper, and the fixture site's `jekyll preview-images` run with the deterministic `local` provider (real PNGs, idempotent second run) |
| `zer0-pages.yml` | PR and push to `main` touching `sites/zer0-pages/**` or the workflow | The site's Obsidian-bridge and graph-index minitest suites, its SCHEMA.md pyramid lint (`tools/schema_lint.py check .`) and a themed `bundle exec jekyll build` |
| `zer0-workspace.yml` | every PR and push to `main` | On Python 3.13 with PyYAML and the full history: the workspace tool's tests (`python -m unittest discover tools/workspace`, including the golden replay of its Ruby predecessor on a commit of that history), then `bin/zer0 check` (every directory under `packages/`, `sites/`, `apps/` registered; paths, workflows, Pages routes and vendored copies consistent), then the ADR 0006 absorption gate (`tools/tests` and `tools/check_absorption.py --report`); writes the affected projects and a report-only `bin/zer0 doctor` of every site to the job summary — the one step that installs Ruby, because the doctor is still `rails/bin/zer0-cms` until PLAN G4 |
| `pages.yml` | PR and push to `main` touching `sites/**`, `apps/parodynews/src/pages/**`, `workspace.yml`, the workspace tool (`bin/zer0`, `tools/workspace/**`), `tools/site_manifest.py`, the Jekyll-theme option (`tools/jekyll_theme.py`, `tools/jekyll/**`, `tools/obsidian/**`), `web/site/fixtures/**` or the workflow; `workflow_dispatch` (input `check`) | The one Pages deploy (ADR 0002 §4 as amended by ADR 0005, PLAN C4): `bin/zer0 routes --json` plans a matrix (Python and PyYAML), each routed site runs its own `pages` task with a generated config setting only `url`/`baseurl` for its route (in UTC) — for a site on the Jekyll-theme option (PLAN P2) that is `tools/jekyll_theme.py`, which builds it with the Jekyll server its `render:` setting names in Docker (GitHub Pages' own builder, or the jekyll-4 image, built from `tools/jekyll/Dockerfile` by `docker/build-push-action` with the GitHub Actions cache) and reports what it resolved; only zer0-pages's leg, still on its Gemfile, installs Ruby — must produce an `index.html`, and is warned on a Liquid warning; then `tools/site_manifest.py` records what it wrote and compares it with the site's recorded Jekyll build (`web/site/fixtures/<site>/manifest.json`, PLAN P1, [`web/site/fixtures/README.md`](../web/site/fixtures/README.md)) — the fresh recording is uploaded as the `site-manifest-<site>` artifact (commit it to re-record) and a difference is listed in the job summary; on a pull request a site on the Jekyll-theme option fails on a difference (the option reproduces its recording exactly, so the same pull request re-records an intended change), zer0-pages warns, a push to `main` only warns (a difference never blocks a deploy), and a dispatch with `check: true` fails on any; the parts are stitched into one artifact. PRs deploy nothing; a push to `main` deploys only while `vars.PAGES_DEPLOY_ENABLED` is `true`; the default target is this repository's project site (`vars.PAGES_URL`, `PAGES_BASE_PATH` aim it elsewhere) |
| `sites.yml` | PR and push to `main` touching `sites/zer0-pages-remote/**`, `sites/zer0-demo-cookbook/**`, `sites/zer0-demo-garden/**`, `sites/2005/**`, `sites/wargames/**`, `workspace.yml`, the workspace tool, the Jekyll-theme option (`tools/jekyll_theme.py`, `tools/jekyll/**`, `tools/obsidian/**`), `tools/site_manifest.py`, `web/site/fixtures/2005/**` or the workflow | Each changed site's `build` task (a matrix planned by `bin/zer0 affected`; every site when `workspace.yml`, the workspace tool, the option, the comparison or the 2005 recording changes): the Jekyll-theme option with the site's own `url` and `baseurl`, no Ruby; 2005, which nothing routes, is also compared with its recording — a difference fails, and the fresh recording is uploaded as `site-manifest-2005` to commit when the change is intended |
| `parodynews.yml` | PR and push to `main` touching `apps/parodynews/**` or the workflow | Django pre-checks and pytest on Python 3.10–3.12 against PostgreSQL, the frontend typecheck, Vitest and build, and lint, dependency-scan and quality analysis — all through the app's own `.github/scripts/*.sh` |
| `aieo.yml` | PR and push to `main` touching `apps/aieo/**` or the workflow | The app's own `ci.yml`, ported: the FastAPI backend's pytest against PostgreSQL 15 and Redis 7, the React frontend's eslint, smoke test and Vite build, and black + ruff (mypy advisory) over the backend |
| `irony-works.yml` | PR and push to `main` touching `sites/irony-works/**`, `workspace.yml`, the workspace tool, the Jekyll-theme option, `tools/site_manifest.py`, `web/site/fixtures/irony-works/**` or the workflow | The build half of the site's `publish.yml` through the Jekyll-theme option: its `build` task installs js-yaml at the version its recording publishes, renders the previews and transplants the vault into `_entries/` on a copy of the site, then builds it with GitHub Pages' own builder (the image `actions/jekyll-build-pages` runs) in Docker; the build is compared with its recording — a difference fails, and the fresh recording is uploaded as `site-manifest-irony-works`; nothing is deployed |
| `books.yml` | PR and push to `main` touching `packages/books/**` or the workflow | The bookshelf app's `pytest` and `ruff check src tests` on Python 3.10 and 3.12 |
| `drsai.yml` | PR and push to `main` touching `sites/drsai/**`, `workspace.yml`, the workspace tool, the Jekyll-theme option or the workflow | The story engine's ruff, black and pytest on Python 3.10–3.12; `tools/import_abc_book.py --check` and the prose gate; and the site's `build` task — the Jekyll-theme option, the theme at its pinned tag, GitHub Pages' own builder in Docker, no Ruby (the theme cannot move under it, so there is no weekly run) |
| `zer0-doctor.yml` | `workflow_call` from a content repository; `workflow_dispatch` here | The zer0 stack consumer contract check on the caller's site (below); fails only when asked to |
| `zer0-linkedin.yml` | `workflow_call` from a content repository | The LinkedIn distribution lane on the caller's site at its branch tip — the platform's `manage.py linkedin` on Python 3.13, which opens no database: `publish` (a rehearsal, or live with `ZER0_LINKEDIN_PUBLISH=1` set for that one step; `ZER0_LINKEDIN_MERGED=1` on the default branch), `status` (fails on a dead token or one within `warn-days` of expiry) or `stats`; commits the ledger, the queue and `performance.json` back with `[skip ci]` and uploads them as `zer0-linkedin-results`; skips with a notice when the caller has no LinkedIn credential. Contract: [`DISTRIBUTION.md`](DISTRIBUTION.md#ci-the-reusable-workflow) |
| `ci.yml` | every PR and push to `main` | The hub's shared `standard-ci.yml` (a thin caller; the logic lives in bamr87/bamr87) |
| `markdown-oneline.yml` | PR and push to `main` touching markdown | On a same-repo PR it runs `tools/unwrap-prose.py --write` (skipping `SCHEMA.md` and `CHANGELOG.md`) and pushes the repair to the PR branch; on a fork PR or a push to `main` it fails with the fix command instead |
| `codeql-analysis.yml` | push and PR to `main`, weekly (Fridays 14:24 UTC) | CodeQL over `javascript-typescript` and `ruby`, both `build-mode: none` |
| `release.yml` | push to `main` | The hub's release-please workflow maintains the release PR; when that PR merges, the repo-owned `marketplace` job packages the vsix at the tag, attaches it to the GitHub Release, and publishes to the Marketplace and Open VSX when their tokens exist (see [`RELEASING.md`](RELEASING.md)) |
| `claude.yml` | `@claude` in an issue, comment or review | The mention handler (`anthropics/claude-code-action@v1`), one run per thread; it never merges |

A change to `rails/` runs `abc-engine.yml` and `rails-app.yml` and not `extension.yml`; a change to `src/` runs `extension.yml` and neither Ruby workflow; a change to `content/` runs `content.yml` alone; a change to `web/` runs `web.yml` alone, and a change to the OpenAPI document runs both `content.yml` and `web.yml`, because the studio's client is generated from it. The two Ruby workflows are split on purpose: `abc-engine.yml` proves the library under `rails/lib` needs no gem, and `rails-app.yml` is allowed the bundle. Do not add `bundle install` to `abc-engine.yml`; a gem reached from `lib/` is the bug that job exists to catch.

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

# the platform (what content.yml runs)
cd content && pip install -r requirements-dev.txt
ruff check . && ruff format --check . && python manage.py makemigrations --check --dry-run
python -m pytest -q                                  # DATABASE_URL=postgres://… for the Postgres job
python manage.py wagtail_ai_schema --check ../schemas/content/ai-schema.json
python manage.py graphql_schema --out /tmp/s.graphql && diff ../schemas/graphql/schema.graphql /tmp/s.graphql
python manage.py spectacular --format openapi-json --urlconf ops.openapi --fail-on-warn --file /tmp/o.json && diff ../schemas/openapi/openapi.json /tmp/o.json

# the studio and its packages (what web.yml runs)
cd web && npm ci && npm run lint && npm run typecheck && npm test && npm run check:api && npm run build

# the platform's stack, when content/Dockerfile, web/ or docker-compose.yml changed (the image builds the studio)
GIT_SHA=$(git rev-parse --short HEAD) BUILT_AT=$(date -u +%FT%TZ) docker compose --profile content up -d --build --wait db redis content worker research-worker beat relay events
curl -fsS http://localhost:8000/healthz && curl -fsS http://localhost:8000/readyz && curl -fsS http://localhost:8000/version
curl -fsS -o /dev/null -w '%{http_code}\n' http://localhost:8000/studio/   # 200, with an enforced Content-Security-Policy
docker compose --profile content down -v

# the same checks as pre-commit hooks (pip install pre-commit && pre-commit install)
pre-commit run --all-files

# one paragraph per line, with the two excludes markdown-oneline.yml passes
python3 tools/unwrap-prose.py --check --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$'

# the workspace and the absorption gate (what zer0-workspace.yml runs; any Python with PyYAML,
# such as the repository's .venv — tools/workspace/README.md § PyYAML)
python3 -m unittest discover tools/workspace && bin/zer0 check
python3 -m unittest discover tools/tests && python3 tools/check_absorption.py
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
- **Event contracts:** `schemas/events/` (CloudEvents envelope, one data schema per type, one example each), checked from both planes — `content/tests/outbox/test_contracts.py` and `rails/test/zer0_cms/test_event_contracts.rb`.
- **The Jekyll bridge:** `content/tests/importers/test_jekyll.py` — every Jekyll site in the repository imports into Wagtail and exports back byte for byte.
- **Agent behaviour:** each definition's eval suite in `content/agents/definitions/*.yaml`, over recordings in `content/agents/recordings/`; a definition revision goes live only when its suite passes.
