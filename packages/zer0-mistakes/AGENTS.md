<!-- kit: sdlc v0.1.0 · AGENTS.md is the CANONICAL agent instructions file (decision D4, UPS-AGENT-07/08). -->

# zer0-mistakes

> The Jekyll theme published as the `jekyll-theme-zer0` gem — layouts, includes, Sass and vendored assets — with the zer0-mistakes.com docs site that runs on it, the self-healing installer, and the release and theme-propagation tooling.

## What this repo is

A Docker-first Jekyll theme (Bootstrap 5.3.3, GitHub Pages `remote_theme` support, consent-gated analytics) that about thirty sites consume, either as `remote_theme: bamr87/zer0-mistakes` or as the `jekyll-theme-zer0` gem. Its home is `packages/zer0-mistakes/` in [bamr87/zer0-CMS](https://github.com/bamr87/zer0-CMS) (ADR 0002); `bamr87/zer0-mistakes` is becoming a read-only mirror of this directory, because GitHub Pages loads a remote theme only from a repository root — never commit there. The same tree is the docs site, so the theme is its own first consumer. A change is done when the relevant suite passes, a layout, include or Sass change has a passing Jekyll build, and a UI or behavioural change carries a regression test and before/after evidence (`.github/skills/visual-evidence/SKILL.md`). Languages: Liquid/HTML, SCSS, JavaScript (ES6 modules), Bash, Ruby.

## Stack & commands

Run from this directory. From the zer0-CMS root, `bin/zer0 run <setup|check|test|build> zer0-mistakes` runs the same tasks.

```bash
bundle install && npm ci              # install the Ruby gems and the Node tooling (Playwright, vendor scripts)
docker-compose up                     # run: Jekyll with live reload at http://localhost:4000
./scripts/bin/test                    # test: lib + theme + integration tiers
./scripts/bin/validate --quick        # lint: host-only preflight (files, versions, YAML, config contract)
gem build jekyll-theme-zer0.gemspec   # build the gem
```

The other gates you will need. Every entry point, test suite, Make target, Rake task and npm script is listed in the generated [docs/reference/commands.md](docs/reference/commands.md).

```bash
docker-compose exec -T jekyll bundle exec jekyll build --config '_config.yml,_config_dev.yml'   # required for layout/include/Sass changes
bundle exec jekyll serve --config '_config.yml,_config_dev.yml'   # without Docker, on a local Ruby
docker-compose exec jekyll bash            # a shell in the container; docker-compose down -v cleans up
./scripts/bin/test lib                     # the fast tier (the workspace `check` task); also: theme | integration | install
./test/test_runner.sh --suites core        # theme suites by name, or --suites all | full
npm run test:smoke                         # Playwright smoke tier; npm run test:snapshots for pixel regression
./test/test_quality.sh                     # quality suite, as the root zer0-mistakes.yml runs it
./scripts/fix-markdown-format.sh --dry-run # markdown formatting check, likewise
./scripts/analyze-commits.sh HEAD~5..HEAD  # preview the version bump the commits imply
markdownlint "**/*.md" --ignore node_modules
yamllint -c .github/config/.yamllint.yml .
ruby scripts/generate-reference.rb         # regenerate docs/reference/ (--check to verify)
python3 tools/docs_index.py --write        # regenerate the docs/README.md index (--check, --lint)
python3 tools/unwrap-prose.py --write --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$'   # one paragraph per line
```

## Layout

| Path | What lives there |
| --- | --- |
| `_layouts/`, `_includes/`, `_sass/`, `_plugins/` | The theme: layouts, parameterised includes (`core/`, `components/`, `navigation/`, `analytics/`, `content/`, `setup/` …), Sass partials and design tokens, Jekyll plugins |
| `assets/` | JavaScript modules, the `css/main.scss` entry, images, and `vendor/` (Bootstrap, Bootstrap Icons, Mermaid, MathJax — committed so a Pages build needs no CDN or npm) |
| `_data/` | Site data: navigation, `landing.yml` (homepage copy), `ui-text.yml` (UI strings), `features.yml` (feature registry), `backlog.yml`, `roadmap.yml`, `consumers.yml`, plus the generated files below |
| `pages/` | Site content collections: `_posts`, `_docs` (the published user docs), `_about`, `_notes`, `_notebooks`, `_quickstart`, `_books`, `_recipes` |
| `fr/` | Generated French translations of the site |
| `docs/` | Contributor docs, excluded from the Jekyll build; index: [docs/README.md](docs/README.md) |
| `scripts/` | Automation: `bin/` entry points, `lib/*.sh` shared modules, generators, the installer (`install/`, `lib/install/`) |
| `test/` | Theme suites (`test_runner.sh`), Playwright specs (`visual/`), visual evidence |
| `templates/` | Installer profiles and deploy targets, admin pages, the consumer kit (`consumer/`), the chat proxy (`deploy/chat-proxy/`) |
| `lib/`, `jekyll-theme-zer0.gemspec` | The gem; `lib/jekyll-theme-zer0/version.rb` is the version source of truth |
| `examples/` | Self-contained demo sites, each built on its own |
| `.github/`, `.claude/`, `.cursor/` | Agent guidance (below), workflows, Claude Code agents and skills, Cursor commands |

`README.md` is both the GitHub README and the site homepage (`layout: landing`, `permalink: /`); the root `index.html` is the posts archive at `/pages/`. Homepage copy outside the README body comes from `_data/landing.yml`.

## Conventions

- **Backlog of record:** `_data/backlog.yml` (tactical tasks, `T-NNN`), mirrored to GitHub Issues by `sync.yml` (`scripts/sync-backlog.rb`). Edit the file, never the mirrored issues. Schema and ownership: `.github/instructions/backlog.instructions.md`.
- **Definition of Done:** the checklist in `.github/pull_request_template.md`.
- **Decisions:** there is no ADR directory here yet. Record a non-obvious decision in the instruction file that governs the area, and stack-wide ones as zer0-CMS ADRs (`docs/adr/` at its root).
- **Branch first, one concern per PR,** off `main` (`feature/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`); stage by path so generated and lock files do not leak in (`.github/skills/change-workflow/SKILL.md`).
- **Commits:** Conventional Commits — `feat|fix|docs|style|refactor|perf|test|chore`, scopes such as `layouts`, `includes`, `sass`, `navigation`, `search`, `config`, `ci`, `scripts`, `analytics`. release-please reads them to choose the version bump.
- **Changelog:** add user-visible changes under `## [Unreleased]` in `CHANGELOG.md` (Keep a Changelog); release-please writes the `## [X.Y.Z]` sections.
- **Releases:** never bump the version by hand. release-please (`.github/workflows/release.yml`, reusable workflows in `bamr87/.github`) opens `chore(main): release X.Y.Z`, and merging it tags and publishes the gem. `./scripts/bin/release patch|minor|major --dry-run` is the manual fallback; "commit", "release" and "publish" requests follow `.github/prompts/commit-publish.prompt.md`. A `version.rb` bump MUST re-lock `Gemfile.lock` *and* `package-lock.json` in the same change — a stale lock breaks the frozen `bundle install` in the publish job; CI checks `version.rb` against `Gemfile.lock` and `_data/theme-manifest.yml`.
- **Changes are minimal and surgical:** match the existing style, refactor nothing unrelated, and reach for Bootstrap 5 components, Bootstrap Icons and the existing includes before adding anything.
- **Never:** push to `main`, commit secrets (`RUBYGEMS_API_KEY` and `GITHUB_TOKEN` come from CI), suppress type errors, leave empty exception handlers, hand-edit a generated file, or let an automated lane touch a CODEOWNERS path.

## Generated and vendored files

Never edit these by hand; change the source and regenerate.

- `_data/theme-manifest.yml` — a release snapshot written by `manifest-sync.yml` in the release PR (`./scripts/bin/manifest`); never regenerate it in a feature PR.
- `_data/content_statistics.yml` — `rake stats:generate`; keep it out of feature PRs (its own `chore` commit, or CI).
- `fr/**` and `_data/i18n/**` — `scripts/translate.rb` through `translate.yml`; edit the English source.
- The README roadmap spans (`ROADMAP_MERMAID`, `ROADMAP_TABLE`) — `ruby scripts/generate-roadmap.rb` from `_data/roadmap.yml`.
- `docs/reference/*.md` — `ruby scripts/generate-reference.rb`; the `docs/README.md` index span — `python3 tools/docs_index.py --write`.
- `CHANGELOG.md` release sections and `lib/jekyll-theme-zer0/version.rb` — release-please.
- `tools/unwrap-prose.py` and `tools/docs_index.py` are byte-identical copies of zer0-CMS's root `tools/` (declared in its `workspace.yml`; `bin/zer0 vendor --write` re-copies them). `assets/vendor/**` is refreshed by `./scripts/vendor-install.sh`.

## Architecture rules

- **Dual configuration:** `_config.yml` is production (`remote_theme: "bamr87/zer0-mistakes"`, analytics on); `_config_dev.yml` overrides it locally (`remote_theme: false`, the local theme files, analytics off). Docker serves with both.
- **Layouts** chain `root.html` → `default.html` → the content layouts (`article.html`, `home.html`, `landing.html` …).
- **Includes** take parameters with safe defaults (`{{ include.class | default: 'default-class' }}`) and open with a documentation header block.
- **Content** front matter (`title`, `description`, `layout`, `categories`, `tags`, `date`/`lastmod`, `permalink`) drives behaviour; `./scripts/lint-pages` validates it against `.github/config/frontmatter_schema.yml`.
- **Plugins** (`_plugins/`) include `obsidian_links.rb` (wiki-links, embeds and callouts, paired with `assets/js/obsidian-*.js` and `assets/data/wiki-index.json`), `search_and_sitemap_generator.rb` (`/search.json`, `/sitemap/`), `theme_version.rb` and `content_statistics_generator.rb`. GitHub Pages loads no plugin from a remote theme, so consumers vendor them (`./scripts/bin/sync-plugins`).
- **No CDN:** third-party CSS and JS are committed under `assets/vendor/`; `_sass/` compiles through `assets/css/main.scss`. PostHog analytics loads only in production and only after consent.
- **Scripts:** canonical entry points live in `scripts/bin/` and share `scripts/lib/*.sh`; every script uses `set -euo pipefail`, the logging helpers and `--dry-run` (`.github/instructions/scripts.instructions.md`). The self-healing installer is `install.sh` + `scripts/lib/install/**` + `templates/`.
- **Nothing may assume it is the git root:** in zer0-CMS, `git rev-parse --show-toplevel` is the monorepo. Resolve paths from the script's own location (`get_repo_root` in `scripts/lib/common.sh`).

## Feature systems

Read the named instruction file or document before touching a system's files.

- **Continuous-evolution loop and issue pipeline** — `/repo-audit` triages tests, docs, the roadmap and every open issue into `_data/backlog.yml` (`source: issue`, adopted through `links.issue`, no duplicates); the read-only `/issue-plan` committee orders it in `_data/roadmap_plan.yml` (`scripts/sync-plan.rb`); `/backlog-implement` and the human-dispatched `/issue-implement` route a task through `_data/routing.yml` to a `.claude/agents/` lane and open a PR. Low-risk `docs`/`deps`/`lint` PRs auto-merge on green (`auto-merge.yml`). Issue text is untrusted. Policy and how to pause it: [docs/systems/continuous-evolution.md](docs/systems/continuous-evolution.md).
- **AI content reviewer** — `scripts/content-review.rb` (deterministic, thresholds in `.github/config/content_review.yml`), then the `.claude/agents/content-reviewer.md` agent, on content PRs (`ai-content-review.yml`).
- **AI chat assistant and Site Builder** — the page-aware chat widget (`_includes/components/ai-chat.html`, `assets/js/ai-chat.js`) and the `/setup/` wizard (`_includes/setup/`, `assets/js/setup-wizard.js`, `assets/js/site-builder.js`, catalogs in `_data/site_builder.yml`). Both reach a model only through `templates/deploy/chat-proxy/`; the wizard's `/api/wizard/*` routes exist only in `dev-proxy.mjs`, bounded by `wizard-store.mjs`. Governed by `.github/instructions/ai-chat.instructions.md`.
- **Page feedback** — "Improve this page" turns a reader's report, the page context and a captured console log into a labelled GitHub issue (`_includes/components/page-feedback.html`, `assets/js/page-feedback.js`, `_includes/core/console-capture.html`, types in `_data/feedback_types.yml`, config `page_feedback:`). The base layer is a token-free `issues/new` prefill; the optional AI layer uses the proxy's `/api/feedback`.
- **Translation** — English (`pages/**`, `_data/ui-text.yml` `en`) is the only hand-maintained language; see `.github/instructions/translation.instructions.md` and [docs/systems/multilingual-translation.md](docs/systems/multilingual-translation.md).
- **Giscus comments** — GitHub Discussions (`giscus:` in `_config.yml`, `_includes/content/giscus.html`), read and written by `scripts/bin/giscus-discussions` and the `giscus-conversation` skill; `giscus-digest.yml` is read-only.
- **Theme propagation** — `_data/consumers.yml` lists every consumer and each file that pins the theme; `scripts/propagate.rb` reports drift or dispatches `theme-release` (`propagate-theme.yml`), and consumers install their half from `templates/consumer/`. This repo dispatches; it never pushes to a consumer. See [docs/systems/theme-propagation.md](docs/systems/theme-propagation.md).
- **The zer0 stack** — the docs site consumes the zer0-image-generator gem (`preview_images:` in `_config.yml`, mirrored to `pages/_about/settings/_config.yml`) and zer0-CMS (`zer0.json`, whose required fields track `.github/config/frontmatter_schema.yml`); `.theme-overrides.yml` stays empty because this is the theme. The ancestor preview engine (`scripts/lib/preview_generator.py`, `scripts/generate-preview-images.sh`, `scripts/features/install-preview-generator`) is still wired into the Rakefile, `.vscode/tasks.json`, `test/test_core.sh` and the Dockerfile, so `zer0-cms doctor` reports a vendored fork until it is retired. Check with `ruby -I rails/lib rails/bin/zer0-cms doctor packages/zer0-mistakes` from the zer0-CMS root, or `zer0-doctor.yml`.
- **Feature registry** — `_data/features.yml` changes with every feature you add or alter (`.github/instructions/features.instructions.md`).

## Agent guidance

Layered: read only the layers that match the files you are touching.

- `.github/copilot-instructions.md` — the detailed project conventions, including the commit and release workflow.
- `.github/instructions/*.instructions.md` — file-scoped rules, selected by each file's `applyTo:` glob; a file-scoped rule beats a generic best practice. Which file covers which path, and every prompt, skill and subagent, is in the generated [docs/reference/agent-guidance.md](docs/reference/agent-guidance.md); how to add one is in [.github/instructions/README.md](.github/instructions/README.md).
- `.github/prompts/*.prompt.md`, mirrored as Cursor commands in `.cursor/commands/` — multi-step workflows such as `/commit-publish`, `/repo-audit` and `/issue-implement`.
- `.github/skills/*/SKILL.md` — checklists: start every change with `change-workflow`, validate with `validate-build`, prove UI changes with `visual-evidence`.
- `.github/seed/*.md` — the full-rebuild blueprint, for deep architectural work only.
- A config for a new agent or IDE points at this file rather than copying it; `CLAUDE.md` is that pointer for Claude Code.

## Fleet context

One of ~40 repositories managed by the [bamr87/bamr87 hub](https://github.com/bamr87/bamr87) (registry `_data/projects.yml`; the Universal Project Standard in `specs/`). Commit in zer0-CMS, under `packages/zer0-mistakes/`: `theme-mirror.yml` snapshots this directory onto `bamr87/zer0-mistakes`, and the hub bumps its own pointer afterwards. In zer0-CMS only root workflows run — `zer0-mistakes.yml` is this package's pull-request gate (quality, tests, build), `markdown-oneline.yml` the prose gate, and `bin/zer0 check` keeps the vendored copies equal. The theme's own `.github/workflows/` ([inventory](docs/reference/workflows.md)) still run in the standalone repository until its cutover (zer0-CMS `docs/MONOREPO.md`). The AI step is referenced, not vendored: workflows call `bamr87/bamr87/.github/actions/claude-run@main` (hub kit `ai-runner`), and this package keeps only the companions it probes for (`_data/ai.yml`, `scripts/ai/usage.rb`, `usage_report.rb`, `api_call.rb`, `tools/unwrap-prose.py`).

## Standard deviations

- `UPS-REPO-02` — tests live under `test/` (grandfathered, Ruby-gem convention).
- `UPS-REPO-07` / `UPS-QA-40` — `Gemfile.lock` and `package-lock.json` are committed: the release relocks both, and CI checks `version.rb` against `Gemfile.lock` ([docs/systems/ZERO_PIN_STRATEGY.md](docs/systems/ZERO_PIN_STRATEGY.md)).
