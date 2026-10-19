# AGENTS.md — AI Agent Guide for zer0-mistakes

> **Cross-tool entry point** for AI coding agents working in this repository
> (GitHub Copilot, OpenAI Codex, Cursor, Aider, Jules, Continue, Claude Code,
> and any future agent that follows the [agents.md](https://agents.md/)
> convention).

This file is intentionally short. It tells an agent **where to look** for the detailed, file-scoped guidance that already lives under `.github/`. **It does not duplicate that content** — keep changes here minimal and instead update the targeted instruction files when patterns evolve.

---

## 🧭 Project Snapshot

- **What it is**: A Docker-first Jekyll theme (Ruby gem `jekyll-theme-zer0`)
with Bootstrap 5.3.3, GitHub Pages remote-theme support, automated semantic releases to RubyGems, and privacy-compliant analytics.
- **Primary language(s)**: Ruby (gem), Liquid/HTML (theme), SCSS, Bash (tooling).
- **Version source of truth**: `lib/jekyll-theme-zer0/version.rb`.
- **Default dev environment**: Docker Compose (`docker-compose up`). A local
  Ruby/Bundler workflow also works.

**Releases.** Don't bump the version by hand. **release-please** is the canonical flow: it watches Conventional Commits on `main`, opens a "chore(main): release X.Y.Z" PR, and merging that PR tags the release and publishes the gem (`.github/workflows/release.yml` → reusable workflows in `bamr87/.github`). `./scripts/bin/release` remains a manual fallback. Any `version.rb` bump MUST re-lock `Gemfile.lock` *and* `package-lock.json` in the same change — a stale lock breaks the frozen `bundle install` in the publish job (CI guards version.rb ↔ Gemfile.lock).

For the full architectural and product overview, see [`README.md`](./README.md) and [`.github/copilot-instructions.md`](./.github/copilot-instructions.md).

---

## 📚 Where Agent Guidance Lives

This repo follows a layered guidance model. Read the layers that match the files you are about to touch — do **not** load everything up front.

| Layer | Location | When to read |
| --- | --- | --- |
| **Cross-tool entry point** | `AGENTS.md` (this file) | Always — first |
| **Project-wide Copilot instructions** | `.github/copilot-instructions.md` | Always — second; full architecture, commands, conventions |
| **File-scoped instructions** | `.github/instructions/*.instructions.md` | When editing files matching the `applyTo:` glob in each file's front matter |
| **Reusable prompts (chat/agent modes)** | `.github/prompts/*.prompt.md` | When asked to perform a multi-step task that matches a prompt |
| **Project "seed" blueprint** | `.github/seed/*.md` | For deep architectural decisions or rebuilding subsystems from scratch |
| **Tactical backlog** | `_data/backlog.yml` | When picking up or filing granular tasks (synced to GitHub Issues) — see the continuous-evolution loop below |
| **Obsidian vault docs** | `pages/_docs/obsidian/` | When working with `[[wiki-links]]`, `![[embeds]]`, callouts, or the wiki-index/JS resolver |
| **Cursor slash-commands** | `.cursor/commands/*.md` | Auto-loaded by Cursor; mirrors the prompts above |
| **CI / quality config** | `.github/config/`, `.github/workflows/` | When changing lint rules, tests, or release automation |

### File-scoped instruction map

Apply the instruction file whose `applyTo:` glob matches the path you are editing (most editors do this automatically; agents without that capability should load them manually):

| Editing files in… | Read |
| --- | --- |
| `_layouts/**` | `.github/instructions/layouts.instructions.md` |
| `_includes/**` | `.github/instructions/includes.instructions.md` |
| `scripts/**` | `.github/instructions/scripts.instructions.md` |
| `scripts/lib/install/**`, `scripts/bin/install`, `install.sh`, `templates/{profiles,deploy,agents,ai}/**` | `.github/instructions/install.instructions.md` |
| `_plugins/obsidian_links.rb`, `assets/js/obsidian-*.js`, `assets/data/wiki-index.json`, `_includes/content/backlinks.html`, `pages/_docs/obsidian/**`, `test/test_obsidian.sh`, `test/test_ruby_converter.rb`, `test/test_resolver.js` | `.github/instructions/obsidian.instructions.md` |
| `_sass/**`, `assets/css/**` | `.github/instructions/sass.instructions.md` |
| `test/**` | `.github/instructions/testing.instructions.md` |
| `docs/**`, `pages/_docs/**`, `*docs*.md` | `.github/instructions/documentation.instructions.md` |
| `CHANGELOG.md`, `**/version.*`, `*.gemspec`, `package.json` | `.github/instructions/version-control.instructions.md` |
| `_data/backlog.yml`, `scripts/sync-backlog.*`, `.github/workflows/sync.yml` | `.github/instructions/backlog.instructions.md` |
| `pages/**/*.md`, `.github/config/content_review.yml`, `.claude/agents/content-reviewer.md`, `scripts/content-review.rb`, `.github/workflows/ai-content-review.yml` | `.github/instructions/content-review.instructions.md` |
| `_includes/components/ai-chat.html`, `assets/js/ai-chat.js`, `templates/deploy/chat-proxy/**` | `.github/instructions/ai-chat.instructions.md` |
| `_data/features.yml`, `features/**`, `pages/features.md`, `scripts/{validate-features.rb,tag-features}`, `test/test_features.sh` — **and whenever you add/alter a feature** | `.github/instructions/features.instructions.md` |

### Reusable prompts

| Task | Prompt |
| --- | --- |
| Full release pipeline (analyze → validate → version → publish → verify) | `.github/prompts/commit-publish.prompt.md` |
| Add a new Obsidian wiki-link / embed / callout syntax across all rendering paths | `.github/prompts/obsidian-add-syntax.prompt.md` |
| Front matter audit / fix across content | `.github/prompts/frontmatter-maintainer.prompt.md` |
| Review content for SEO / consistency / polish (per-collection) | `.github/prompts/content-review.prompt.md` |
| Rebuild the theme from scratch (deep blueprint) | `.github/prompts/seed.prompt.md` |
| Review the repo **and triage all open issues** into the backlog | `.github/prompts/repo-audit.prompt.md` |
| Implement the next open backlog task and open a PR | `.github/prompts/backlog-implement.prompt.md` |
| Implement ONE issue/task — route → loop-until-green → PR (human-dispatched) | `.github/prompts/issue-implement.prompt.md` |
| Plan/sequence the open backlog (the planning committee) | `.github/prompts/issue-plan.prompt.md` |

### Workflow skills

Operational checklists under `.github/skills/<name>/SKILL.md`. Read the matching skill before the action it covers.

| Doing… | Skill |
| --- | --- |
| **Starting any change** — branch → commit → PR, splitting mixed work, keeping generated/lock files out of feature PRs | `.github/skills/change-workflow/SKILL.md` |
| Validating a change before commit/PR (Jekyll build, doctor, tests) | `.github/skills/validate-build/SKILL.md` |
| **Any UI/behavioural change** — regression test + before/after evidence (required for fixes to auto-merge) | `.github/skills/visual-evidence/SKILL.md` |
| Reviewing content PRs for SEO/consistency/polish | `.github/skills/content-review/SKILL.md` |
| Planning/sequencing the backlog (the `/issue-plan` committee fan-out) | `.github/skills/committee-plan/SKILL.md` |

---

## 🔁 Continuous-Evolution Loop

This repo runs a self-sustaining backlog loop so AI agents can keep improving it between human sessions:

1. **Audit + issue intake** (`/repo-audit`, scheduled weekly) reviews tests, docs,
and roadmap delivery **and triages all open GitHub issues** into [`_data/backlog.yml`](./_data/backlog.yml) (`source: issue`, adopted via `links.issue` — no duplicates). The committee `/issue-plan` then sequences them and `/issue-implement` (human-dispatched) routes each to a specialized agent. See [`docs/systems/continuous-evolution.md`](./docs/systems/continuous-evolution.md).
2. **Sync** (`.github/workflows/sync.yml`) mirrors open tasks to GitHub
   Issues (`agent-ready` label) and closes issues for tasks marked `done`.
3. **Implement** (`/backlog-implement`, scheduled) picks the top open task, builds
it on a branch, validates, and opens a PR. Low-risk classes (`docs`/`deps`/`lint` with `risk: low`) auto-merge once CI is green via `.github/workflows/auto-merge.yml`; everything else waits for human review.

`_data/backlog.yml` is the source of truth — edit the file, not the issues. Full design, autonomy policy, and how to pause the loop: [`docs/systems/continuous-evolution.md`](./docs/systems/continuous-evolution.md).

---

## 🏗 Architecture

**Dual configuration system** — the core pattern to understand first:

- `_config.yml` — production; uses `remote_theme: "bamr87/zer0-mistakes"` for
  GitHub Pages, analytics enabled.
- `_config_dev.yml` — development overrides; `remote_theme: false`, loads the
  local theme files, analytics disabled. Docker runs Jekyll with both configs.

**Layout hierarchy**: `_layouts/root.html` (base) → `default.html` (main) → content layouts (`article.html`, `home.html`, …).

**Modular includes** (`_includes/`): `core/` (head, header, footer), `components/` (cookie consent, theme info), `analytics/` (PostHog — production-only, consent-driven), `navigation/` (navbar, breadcrumbs). Includes take parameters with safe defaults
(`{{ include.class | default: 'default-class' }}`) and carry a documentation
header block.

**Content collections** live under `pages/`: `_posts/` (layout `article`), `_docs/`, `_about/`, `_notebooks/`, `_notes/`, `_quickstart/`. Front matter drives behavior — `title`, `description`, `layout`, `categories`, `tags`, `date`/`lastmod`, `permalink`.

**Custom Jekyll plugins** (`_plugins/`): `obsidian_links.rb` (Obsidian `[[wiki-links]]`/embeds/callouts — paired with `assets/js/obsidian-*.js` and `assets/data/wiki-index.json`; see `.github/instructions/obsidian.instructions.md`), `search_and_sitemap_generator.rb` (`/search.json`, `/sitemap/`), `theme_version.rb`, preview-image and content-statistics generators.

**Vendored assets**: Bootstrap 5.3.3 + Bootstrap Icons + Mermaid are committed under `assets/vendor/` (GitHub Pages–safe, no CDN). Custom styles layer on via `_sass/` → `assets/css/main.css`.

**Automation scripts**: canonical entry points in `scripts/bin/` (`build`, `release`, `test`, `validate`, `install`) share modules from `scripts/lib/*.sh`. Scripts use `set -euo pipefail`, logging helpers, and support `--dry-run`. The self-healing installer is `install.sh` + `scripts/lib/install/**` + `templates/`.

---

## 🛰 Feature Systems

The theme carries several self-contained systems. Read the matching entry (and the instruction file it names) before touching its files.

- **Autonomous issue pipeline** — extends the continuous-evolution loop to ingest
GitHub issues. `/repo-audit` triages all open issues into `_data/backlog.yml` (`source: issue`, adopted via `links.issue` by `scripts/sync-backlog.rb`, no duplicates); `/issue-plan` plans them (order-only `_data/roadmap_plan.yml` + `scripts/sync-plan.rb`); `/issue-implement` routes via `_data/routing.yml` to a specialized `.claude/agents/*` lane. Issue text is **untrusted** (injection fence); agents never touch CODEOWNERS paths. See [`docs/systems/continuous-evolution.md`](./docs/systems/continuous-evolution.md).
- **AI content reviewer** — reviews content PRs (Markdown under `pages/**`) for
SEO, consistency, polish, accessibility, and accuracy. Two tiers: `scripts/content-review.rb` (deterministic, per-collection thresholds from `.github/config/content_review.yml`) and the `.claude/agents/content-reviewer.md` Claude Code agent, run on PRs by `.github/workflows/ai-content-review.yml`. Skill: `.github/skills/content-review/`.
- **AI chat assistant** — opt-in Claude-powered chat widget grounded in the
current page, with GitHub issue/PR tools and a dev-only local page-edit mode. Widget: `_includes/components/ai-chat.html` + `assets/js/ai-chat.js`; proxy: `templates/deploy/chat-proxy/` (Cloudflare Worker + Node dev proxy), deployed by `.github/workflows/deploy-chat-proxy.yml`. Governed by [`ai-chat.instructions.md`](./.github/instructions/ai-chat.instructions.md).
- **Site Builder** — the Claude-guided setup wizard at `/setup/` (and on the
`welcome` layout): nine steps from prerequisites to a written, running site. Form + generators: `_includes/setup/wizard.html` + `assets/js/setup-wizard.js` (pure client-side, GitHub Pages-safe); Claude session: `_includes/setup/claude-session.html` + `assets/js/site-builder.js`, proxy-only via the dev proxy's `/api/wizard/*` routes, which exist only in `templates/deploy/chat-proxy/dev-proxy.mjs` and are bounded by `wizard-store.mjs` (fixed check table, read-only theme source, scaffold into a new folder under `WIZARD_TARGET_ROOT`, fixed `docker compose` actions). Catalogs and the framework brief live in `_data/site_builder.yml`; config under `site_builder:`. Governed by [`ai-chat.instructions.md`](./.github/instructions/ai-chat.instructions.md) §9; docs at `pages/_docs/features/site-builder.md`.
- **Page-feedback widget** — the "Improve this page" capture flow: a runtime
modal + global FAB turn a reader's report (request type + description + live page context + a captured console/error log buffer) into a well-formed, correctly-**labeled** GitHub issue. Base layer is a token-free `issues/new` prefill (GitHub Pages-safe); an optional AI layer sends the capture to Claude via the chat proxy's `/api/feedback` route (Claude Code OAuth) to clarify, vet, prioritize, and recommend before filing. Widget: `_includes/components/page-feedback.html` + `assets/js/page-feedback.js` + `_includes/core/console-capture.html`; request types in `_data/feedback_types.yml`; config under `page_feedback:` in `_config.yml`. Replaces the old build-time Copilot dropdown (which could not capture logs).
- **Multilingual translation pipeline** — English (`pages/**`,
`_data/ui-text.yml` `en`) is the only human-maintained language; alternates (`fr/**`, `_data/i18n/**`) are GENERATED by `scripts/translate.rb` (Claude Code OAuth) via `.github/workflows/translate.yml` (dispatch `mode=full` bulk job + incremental on content pushes; output lands as a `chore/i18n-translations` PR). Never hand-edit generated translations. Frontend: `_includes/components/language-toggle.html`, `_includes/core/{i18n,hreflang}.html`. Governed by [`translation.instructions.md`](./.github/instructions/translation.instructions.md); see [`docs/systems/multilingual-translation.md`](./docs/systems/multilingual-translation.md).
- **Giscus comment conversations** — comments are GitHub Discussions (config:
`_config.yml` `giscus:` block; include: `_includes/content/giscus.html`). `scripts/bin/giscus-discussions` (gh GraphQL) can list/read/draft/seed/post, driven by the `giscus-conversation` skill (`.github/skills/giscus-conversation/`). Read-only digest workflow: `.github/workflows/giscus-digest.yml`.
- **Theme propagation** — how a release reaches the ~5 downstream sites built on
this theme. `_data/consumers.yml` is the registry (consumer, consumption mode, every file holding a pin); `scripts/propagate.rb` reports pin drift or dispatches `theme-release`; `.github/workflows/propagate-theme.yml` fires it on release + weekly. Consumers copy their half from `templates/consumer/` (`bump-theme-pins.sh`, `theme-bump.yml`, `.theme-overrides.yml`, and the zer0 stack files `zer0-doctor.yml` + `zer0.json.template`). This repo **never** pushes to a consumer — it dispatches, and each consumer opens a PR gated by its own CI. `_data/theme-manifest.yml` is the contract underneath it all: a **release snapshot** (regenerated by `manifest-sync.yml` in the release PR, gated in CI on `version.rb` ↔ manifest version), not a working-tree mirror — don't regenerate it in feature PRs. See [`docs/systems/theme-propagation.md`](./docs/systems/theme-propagation.md).
- **The zer0 stack — this repo is also a consumer.** Its docs site (zer0-mistakes.com) uses the same three pillars it asks of every consumer: this theme, the [zer0-image-generator](https://github.com/bamr87/zer0-image-generator) gem (in the `Gemfile`, `group: :jekyll_plugins`; configured by the single `preview_images:` block in `_config.yml`, mirrored to `pages/_about/settings/_config.yml`), and [zer0-CMS](https://github.com/bamr87/zer0-CMS) (the committed `zer0.json` at the root, whose required fields must track `.github/config/frontmatter_schema.yml`). `.theme-overrides.yml` is deliberately empty — nothing here shadows the theme, because it is the theme. The in-repo ancestor engine (`scripts/lib/preview_generator.py`, `scripts/generate-preview-images.sh`, `scripts/features/install-preview-generator`) is still referenced by the Rakefile, `.vscode/tasks.json`, `test/test_core.sh`, the Dockerfile and the docs, so `zer0-cms doctor` keeps reporting it as a vendored fork until it is retired. Run the check with `ruby -I rails/lib rails/bin/zer0-cms doctor /path/to/zer0-mistakes` from a zer0-CMS checkout, or dispatch `.github/workflows/zer0-doctor.yml` (report-only, weekly). Consumer-side instructions: `templates/consumer/README.md` § The zer0 stack.
- `_data/backlog.yml` — tactical task backlog (source of truth; synced to
GitHub Issues by `.github/workflows/sync.yml`). See [`docs/systems/continuous-evolution.md`](./docs/systems/continuous-evolution.md).

---

## ⚡ Essential Commands

```bash
# Development (recommended; serves http://localhost:4000)
docker-compose up                          # Jekyll dev server with live reload
docker-compose exec jekyll bash            # Shell into the container
docker-compose down -v                     # Clean up
bundle exec jekyll serve                   # Local (non-Docker) alternative

# Validate a Jekyll build (required before declaring theme changes done)
docker-compose exec -T jekyll bundle exec jekyll build \
  --config '_config.yml,_config_dev.yml'

# Tests
./scripts/bin/test                         # All suites: lib + theme + integration
./scripts/bin/test lib                     # One tier: lib | theme | integration | install
./test/test_runner.sh                      # Theme test orchestrator (core suites)
./test/test_runner.sh --suites core        # Single suite: core, deployment, quality,
                                           #   installer, site_generation, i18n, obsidian,
                                           #   features, playwright, playwright_snapshots,
                                           #   audit  (the authoritative list is
                                           #   TEST_SUITE_KEYS in test/test_runner.sh;
                                           #   `installation` was retired — its scenarios
                                           #   live in test_install_legacy_flags.sh)
./test/test_runner.sh --suites full        # Everything incl. Playwright tiers
./test/test_core.sh                        # Run one test script directly
npm run test:smoke                         # Playwright smoke tier
npm run test:snapshots                     # Playwright pixel snapshots
npm run test:update-snapshots              # Refresh snapshot baselines

# Quality / preflight
./scripts/validate                         # Canonical preflight validation
./scripts/validate --quick                 # Host-only checks
markdownlint "**/*.md" --ignore node_modules
yamllint -c .github/config/.yamllint.yml .

# Build / release (semantic-version aware; full pipeline:
# changelog → version bump → test → build → tag → publish)
./scripts/bin/build                        # Build the gem only
./scripts/bin/release patch|minor|major    # Release (use --dry-run to preview)
./scripts/analyze-commits.sh HEAD~5..HEAD  # Preview version-bump analysis

# Assets
./scripts/vendor-install.sh                # Refresh committed Bootstrap/icon vendor files
```

Make targets (`make test`, `make release-patch`, …) and Rake tasks (`rake test:all`, `rake dev:serve`, `rake preview:generate`) wrap the same scripts. Wrappers at `scripts/{build,release,test}` forward to the canonical `scripts/bin/` implementations.

---

## ✅ Operating Rules for Agents

1. **Branch first; one concern per PR.** Create a branch off `main` *before*
editing — never commit to `main` directly (it's protected). Each branch/PR holds one logical change; stage by path so generated/lock files don't leak in. See the `change-workflow` skill and `version-control.instructions.md`.
2. **Make minimal, surgical changes.** Match existing style; don't refactor
   unrelated code.
3. **Validate before declaring done.** Run the relevant test suite; for any
   layout/include/sass change, run the Docker Jekyll build above.
4. **Update `CHANGELOG.md`** for user-visible changes (Keep a Changelog
   format, newest entry at the top).
5. **Version bumps happen via release automation** — release-please's release PR
(canonical) or `./scripts/bin/release` (manual fallback), never in unrelated PRs. A `version.rb` bump MUST re-lock `Gemfile.lock` *and* `package-lock.json` in the same change — a stale lock breaks the frozen `bundle install` in the publish workflow. Keep the generated `_data/content_statistics.yml` out of feature PRs (its own `chore` commit or CI).
6. **Conventional commits**: types `feat|fix|docs|style|refactor|perf|test|chore`;
scopes include `search`, `navigation`, `layouts`, `includes`, `sass`, `config`, `ci`, `scripts`, `analytics`. Commit analysis drives the automatic version-bump type.
7. **Prefer existing patterns**: Bootstrap 5 components, Bootstrap Icons, and
   the modular `_includes/` system cover most UI needs.
8. **Backlog**: edit `_data/backlog.yml`, not the mirrored GitHub Issues.
9. When asked to "commit", "release", or "publish", follow the structured
workflow in `.github/copilot-instructions.md` (§ Commit and Release Workflow) or the `/commit-publish` prompt.
10. **Respect the layered guidance.** When a file-scoped instruction conflicts with a generic best practice, the file-scoped instruction wins.
11. **Do not commit secrets.** Use environment variables; `RUBYGEMS_API_KEY` and `GITHUB_TOKEN` are provided in CI.
12. **Document non-obvious decisions** in the relevant instruction file so the next agent benefits from the context.

---

## 🧩 Extending Agent Capabilities

This repository is designed to be **extendable** by both humans and agents. To add new agent capabilities, follow these patterns:

### Add a new file-scoped instruction set

1. Create `.github/instructions/<area>.instructions.md` with front matter:

   ```yaml
   ---
   applyTo: "<glob pattern>"
   description: "One-line summary of what these instructions cover"
   ---
   ```

2. Cover: overview, structure, standards, patterns, best practices, testing,
   documentation (mirror existing files such as `layouts.instructions.md`).
3. List it in [`.github/instructions/README.md`](./.github/instructions/README.md)
   and add a row to the **File-scoped instruction map** above.

### Add a reusable prompt / agent mode

1. Create `.github/prompts/<task>.prompt.md` with front matter:

   ```yaml
   ---
   agent: agent
   mode: agent
   description: "Short description of the multi-step task"
   tools: [optional, list, of, tool, names]
   ---
   ```

2. Write the prompt as a numbered, checkable workflow (see
   `commit-publish.prompt.md` for the canonical pattern).
3. If you want it available as a Cursor slash-command, mirror the file into
   `.cursor/commands/<task>.md`.

### Add a new tool-specific config

When onboarding a new agent or IDE that uses its own config file, add it **without** duplicating instruction content — point the new file at this `AGENTS.md` and the layered guidance under `.github/`. Examples:

- Claude Code: `CLAUDE.md` → a pointer whose `@AGENTS.md` line imports this file.
- Aider: `.aider.conf.yml` with `read: [AGENTS.md, .github/copilot-instructions.md]`.
- Continue: `.continuerc.json` referencing the same files.

This keeps a single source of truth and prevents drift.

### Add a new automation script

1. Place the implementation under `scripts/bin/<name>` (executable, `set -euo pipefail`).
2. Share logic via `scripts/lib/*.sh` modules.
3. Optionally add a thin wrapper at `scripts/<name>` for backward compatibility.
4. Follow the conventions in `.github/instructions/scripts.instructions.md`
   (logging helpers, parameter validation, `--dry-run` support, help text).

---

## 🛸 Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents. The AI step is not vendored at all: workflows call `bamr87/bamr87/.github/actions/claude-run@main` by reference (hub kit `ai-runner`), and this repo keeps only the consumer companions it probes for (`_data/ai.yml`, `scripts/ai/usage.rb` + `usage_report.rb` + `api_call.rb`, `tools/unwrap-prose.py`).

## Standard deviations

- `UPS-REPO-02` — tests live under `test/` (grandfathered, Ruby-gem convention).

---

## 🔗 Quick Links

- Project README: [`README.md`](./README.md)
- Contributing: [`CONTRIBUTING.md`](./CONTRIBUTING.md)
- Security policy: [`SECURITY.md`](./SECURITY.md)
- Code of conduct: [`CODE_OF_CONDUCT.md`](./CODE_OF_CONDUCT.md)
- Changelog: [`CHANGELOG.md`](./CHANGELOG.md)
- Main Copilot instructions: [`.github/copilot-instructions.md`](./.github/copilot-instructions.md)
- Instruction index: [`.github/instructions/README.md`](./.github/instructions/README.md)

---

_Last reviewed: 2026-10-19, when `CLAUDE.md` was folded in and became a pointer. Keep this file short — push detail into `.github/instructions/` and `.github/prompts/`._
