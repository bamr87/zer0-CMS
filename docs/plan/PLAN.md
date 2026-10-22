# PLAN: zer0-CMS → one Python platform with a React frontend (ADR 0006)

**The target is [ADR 0006](../adr/0006-one-python-platform.md), described in [`TARGET.md`](TARGET.md); what each merged repository can do, and where it goes, is [`capabilities.yml`](capabilities.yml); the order of work is § 3's list.** This plan grew in layers (the agent-native content plane, then one home, one platform, the theme going home, and now one Python platform), and its older sections are kept as the record of what was built and why; where an older line says Ruby, Jekyll or the Wagtail admin "stays", ADR 0006 has superseded it. Source of truth for the target: `docs/plan/agent-native-design.md` (called "the note"; section numbers refer to it). Working rules: [`AGENTS.md`](../../AGENTS.md). The decision record is [ADR 0001](../adr/0001-target-architecture.md), which also makes the interim calls on §7's open decisions. One milestone = one Claude Code session = one PR. Tick boxes in the same PR that does the work.

## 0. What is in this repo today (review findings)

> Historical (the 2026-10-17 review). The current target is [`TARGET.md`](TARGET.md); a row here that keeps Ruby, Rails, Jekyll or the Wagtail admin is superseded by ADR 0006.

**Repos merged in** (from `ATTRIBUTION.md`, `workspace.yml` `upstream:` keys, `git log --merges`):

| Project (workspace.yml) | Path | Upstream | Notes |
|---|---|---|---|
| cms-extension | `src/ media/ schemas/` (root) | bamr87/zer0-CMS (fork of estruyf/vscode-front-matter v10.10.1, rewritten) | Merge history still carries estruyf PRs (#9xx–#1026) before the rewrite; zer0 PRs #13–#27 after |
| — governance layer inside the extension | `src/core/governance/` | bamr87/bash-cms (ported, not subtree) | draft queue, brand guard, approval, idempotency ledger |
| cms-rails | `rails/` | bamr87/zer0-CMS (PR #24 feat/rails-fleet-platform) | Rails 8.1 fleet CMS + stdlib `zer0` lib |
| zer0-mistakes | *(returned to its repository, ADR 0005)* | bamr87/zer0-mistakes | Jekyll theme gem `jekyll-theme-zer0`; developed there with its Rails studio; consumed here as a gem / `remote_theme` |
| zer0-image-generator | `packages/zer0-image-generator` | bamr87/zer0-image-generator | Python engine + byte-identical Ruby port + web panel; own release-please + compose |
| books | `packages/books` | bamr87/books | Python bookshelf app + Claude studio |
| parodynews | `apps/parodynews` | bamr87/barodybroject | Django 5.2 + React, Azure Container Apps |
| drsai | `sites/drsai` | bamr87/drsai | Jekyll picture-book site + Python story engine |
| zer0-pages | `sites/zer0-pages` | bamr87/zer0-pages | Obsidian vault + Jekyll bridge |
| zer0-pages-remote, zer0-demo-cookbook, zer0-demo-garden | `sites/*` | same-name repos | remote_theme / installer demos |
| aieo | `apps/aieo` | bamr87/aieo | FastAPI + React AI Engine Optimization app (imported 2026-10-20) |
| irony-works | `sites/irony-works` | bamr87/irony-works | AI-tended Obsidian vault + Jekyll site, Germinate loop (imported 2026-10-20) |
| wargames | `sites/wargames` | bamr87/wargames | OverTheWire study site, remote_theme consumer (imported 2026-10-20) |

**Per part: stack, features, models, APIs, tests, CI**

| Part | Stack | Features | Models / data | APIs | Tests | CI |
|---|---|---|---|---|---|---|
| Extension | TS, esbuild, no runtime deps | front-matter panel, dashboard, SEO insights, governance (drafts/guard/approval/ledger), harness lanes (`src/core/harness`), catering/distribution, analytics, portfolio, Claude agent panel (`src/agent`), MCP server (`src/mcp`, tools.ts ≈2.3k lines) | files + `zer0.json`, `.cms/` contract, `schemas/zer0.schema.json` | VS Code commands `zer0Cms.*`, MCP tools | `src/test` via vscode-test | extension.yml, release.yml (release-please, node) |
| Rails | Rails 8.1, Ruby | indexes every registered site, writes edits back to files, ABC book wizard, LinkedIn distribution, image engine | `Site, Page, Term, Asset, Channel` (schema.rb) | HTML admin, `files`, `abc_books`, `linkedin_callbacks` | minitest (integration, services, zer0_cms) + `bin/test-stdlib` | rails-app.yml, zer0-doctor.yml, zer0-linkedin.yml |
| rails/lib/zer0_cms | stdlib Ruby | catalog, doctor, ABC generator with `ContentProvider` (Deterministic, Anthropic) | — | CLI | stdlib tests | rails-app.yml |
| parodynews | Django 5.2, DRF, React/Vite, Postgres, Azure | AI parody news generation, assistants, threads, posts with front matter + versions | `JSONSchema, AIModel, Assistant, AssistantGroup(+Membership), AIProviderConfig, AppConfig, FieldDefaults, ContentItem, ContentDetail, Post, PostFrontMatter, PostVersion, Thread, Message, PoweredBy` | DRF `parodynews/api/urls.py` | pytest + Vitest (frontend) | parodynews.yml |
| books | Python | validate/compile/edit book projects, Claude studio | `library/<slug>/` files | CLI/local app | pytest | books.yml |
| image-generator | Python + Ruby gem + web | AI preview/social images | files | CLI, Jekyll plugin | py + ruby tests | zer0-image-generator.yml |
| Sites | Jekyll / Obsidian | content | Markdown + front matter | — | build | sites.yml, zer0-pages.yml, drsai.yml, abc-engine.yml |
| Workspace tooling | Ruby `bin/zer0`, `tools/workspace` | registry check, affected, vendor drift | `workspace.yml`, `fleet.manifest.yml` | CLI | — | zer0-workspace.yml, ci.yml, markdown-oneline.yml, codeql, claude.yml |

**Duplication and dead code**

1. **Five LLM clients**: extension `src/agent`, `rails/lib/zer0_cms` Anthropic provider, parodynews provider layer (`AIProviderConfig`/`AIModel`), books studio, drsai story engine (plus image-generator). Target: one Django tool registry + LiteLLM, and `ruby_llm` only for Rails app agents.
2. **Two ledgers**: `src/core/governance/ledger.ts` and `src/core/harness/ledger.ts`, both idempotency/run records. They become `AgentRun/AgentStep` in Django.
3. **Two content models**: Rails `Page/Term/Asset` vs parodynews `Post/PostFrontMatter/PostVersion/ContentItem`, both shadowing Markdown files. Both are replaced by Wagtail pages, revisions and snippets.
4. **Two MCP surfaces in waiting**: extension `src/mcp` (TS) vs the note's Django MCP server.
5. **Image engine twice**: Python engine + "byte-identical Ruby port" + `rails/app/services/image_engine.rb` + vendored copies tracked by `bin/zer0 vendor`.
6. **Per-package infra leftovers from the subtree imports**: 2 nested `release-please-config.json` (root, image-generator), 10+ `docker-compose.yml` (incl. `apps/parodynews/src/posthog/`), 9 `CLAUDE.md` (the theme's went home with it, ADR 0005).
7. **CI is not on hub conventions**: 18 workflows, none call `standard-ci@v2`; release-please covers only the root node package.
8. **Dead/obsolete**: pre-rewrite estruyf history (keep it in git, but nothing in-tree depends on it); commented-out reusable-workflow calls (`zer0-doctor.yml`, `zer0-linkedin.yml` refs); parodynews Azure `infra/` and `azure.yaml` if Azure is dropped; `sites/drsai` planning docs (`PRD*.md`, `IMPLEMENTATION_PLAN.md`, `newsletter_seuss.md`, `reena_poem.md`, `Family newsletter.md`) at the site root; `src/test/fixtures/sites/wikijs/docker-compose.yml` is a fixture, so keep it.

## 1. Inventory → target mapping

> Historical (the 2026-10-17 review). The current target is [`TARGET.md`](TARGET.md); a row here that keeps Ruby, Rails, Jekyll or the Wagtail admin is superseded by ADR 0006.

| Source | Features | Lands in | Action |
|---|---|---|---|
| parodynews Django project | Django settings, DRF, Postgres, auth | `content/` (Django + Wagtail project base) | **Evolve**: becomes the content plane skeleton |
| parodynews `Post/PostFrontMatter/PostVersion/ContentItem/ContentDetail` | posts, versions | Wagtail `ArticlePage` + `Revision` | Migrate data, then drop the models |
| parodynews `Assistant/AssistantGroup/AIModel/AIProviderConfig` | agent config | `content/agents`: `AgentDefinition` (snippet + RevisionMixin), LiteLLM config | Migrate, then drop |
| parodynews `Thread/Message` | chat history | `AgentRun/AgentStep` (kind=llm) | Migrate if needed, otherwise archive |
| parodynews `JSONSchema/FieldDefaults` | content schemas | `wagtail_ai_schema` export (note §2.1) | Replace |
| parodynews React frontend | admin UI | — | **Drop** (Wagtail admin replaces it); keep it only as a reference in git history |
| parodynews Azure infra | deploy | — | **Drop** (open decision D4) |
| Rails `Site/Page/Term/Asset` + `site_sync`, `page_editor`, `files_controller` | file index + write-back | Content → Wagtail (importer + Jekyll exporter); Rails keeps `Site` only as an app-side registry | Rails **stops writing content** (boundary) |
| Rails `Channel`, `linkedin_gateway`, LinkedIn callbacks | distribution | Rails `app/` (app-domain: OAuth, channels); triggered by the `content.page.published` event | Keep in Rails |
| Rails ABC wizard + `rails/lib/zer0_cms` ABC generator | book generation | Django `drafter` agent profile "abc"; export target becomes a Jekyll exporter | Port the logic to Django tools, then drop the Ruby provider |
| Rails `doctor`, `catalog` (stdlib lib) | fleet checks | `tools/zer0` CLI (stays Ruby, stdlib) | Keep |
| Rails users/sessions (new) | personalization | Rails `app/` + `agent_runs/agent_steps` mirror, MCP client, outbox | New |
| Extension `src/core/governance` | drafts, brand guard, approval, ledger | Django: `Suggestion`, `AgentReviewTask(brand)`, brand rules snippet, `AgentRun` | Port the semantics; the extension becomes a client |
| Extension `src/core/harness` | lanes, skills, metering, preflight | Django `agents` harness (tool registry, budgets, evals) | Port, then delete the TS duplicates |
| Extension `src/mcp` | MCP tools | Django MCP server (`content.*`, `graph.*`, `media.*`) | Replace; the extension calls Django MCP/GraphQL |
| Extension panel/dashboard/SEO UI | editor UX | `clients/vscode` headless client (reads/writes via the GraphQL API + suggestions) | Keep as a frontend |
| `schemas/zer0.schema.json` | project file schema | `schemas/` (shared) + `schemas/events/*.json` (CloudEvents) | Keep + extend |
| zer0-image-generator | image AI | Django media pipeline (`ai_alt`, `ai_tags`, embedding, previews) via a Python import; the gem stays for Jekyll users | Keep the package; **drop the Ruby port** from Rails (`image_engine.rb`) |
| books | book projects + studio | Content import as `BookPage` tree; studio → Django agents | Migrate content; drop the studio LLM client |
| drsai story engine | story generation | Django agent profile; site → frontend | Migrate |
| zer0-mistakes theme | Jekyll theme | its own repository, `bamr87/zer0-mistakes`, with its Rails studio (ADR 0005); the exporter's sites build with the gem / `remote_theme` each declares | Consume |
| sites/* | content | Imported into Wagtail (one `Site` per Jekyll site); Jekyll stays as a static frontend | Migrate |
| `bin/zer0`, `tools/workspace`, `workspace.yml` | registry | Keep, re-registered with the new projects | Update |
| 18 workflows | CI | `standard-ci@v2` caller + per-project matrix via `bin/zer0 affected` | Consolidate |

## 2. Target layout

> Historical (the 2026-10-17 review). The current target is [`TARGET.md`](TARGET.md); a row here that keeps Ruby, Rails, Jekyll or the Wagtail admin is superseded by ADR 0006.

```text
content/                 # Django 5.2 + Wagtail 6 — system of record, agent runtime
  config/                # settings, celery, urls (GraphQL, /api/v2, MCP mount)
  cms/                   # page models (ArticlePage, BookPage, SitePage...), AgentManagedMixin, StreamField blocks, custom Image
  agents/                # AgentDefinition, AgentRun, AgentStep, Memory, EvalCase, EvalResult, tool registry, runner
  suggestions/           # Suggestion model, accept flow, editor sidebar (wagtail hooks)
  graph/                 # Entity, Edge, pgvector, structural edges from ReferenceIndex, GraphRAG
  workflow/              # AgentReviewTask
  api/                   # Grapple/Strawberry schema, REST viewsets, SSE
  mcp/                   # FastMCP server backed by agents.registry
  outbox/                # transactional outbox + relay to Redis Streams
  importers/             # jekyll, parodynews, books, drsai
  exporters/             # jekyll exporter (static frontends)
  tests/
app/                     # Rails 8 (moved from rails/) — experience plane
  app/models             # User, Site(registry), Channel, AgentRun, AgentStep, Affinity, OutboxEvent
  app/services           # ContentClient (graphql-client), McpClient, HomepageAgent, LinkedinGateway
  lib/zer0_cms           # stdlib doctor/catalog (ABC generator removed)
clients/vscode/          # the extension (src/, media/, package.json) as a headless client
frontends/sites/         # sites/*
packages/zer0-image-generator/
schemas/                 # zer0.schema.json, events/*.json, graphql/schema.graphql (generated)
tools/                   # bin/zer0, workspace lib
docs/  AGENTS.md  CLAUDE.md -> AGENTS.md (one line pointer)
docker-compose.yml  workspace.yml  release-please-config.json  .release-please-manifest.json
```

Moving `rails/` → `app/` and `src/` → `clients/vscode/` was milestone M2; [ADR 0004](../adr/0004-one-platform.md) closes it. The tree keeps its layout — `content/` is the platform, `src/` the extension, `rails/` and the apps retire in place (Phase G) — and only the names in the docs change.

## 3. Milestones

Each milestone: one branch `m<N>-<slug>`, one PR, green CI. Commands assume `docker compose up -d db redis` where noted.

**Status, 2026-10-21 (later).** [ADR 0006](../adr/0006-one-python-platform.md) sets the destination: one Python platform, one React frontend (the studio and the site renderer), the extension at parity with the studio, an AI content layer rebuilt from barodybroject's model, the manage → monitor → improve loop for sites with AIEO in it, every merged repository absorbed with its content and capabilities, and no Ruby. That is Phase P below, with Phase G re-pointed at it: G2 is superseded by P2, G7 is AIEO in full, G8 is the AI content layer, G10 is extension parity, G12 (monitor) and G13 (improve) are new, T3 and Phase F's D1 milestones are superseded by P5, and M16 and C2's Ruby component are struck.

**Order of work.** Pick the first milestone in this list that is not done and whose predecessors have merged; never pick by "the first unchecked box" — the older phases keep unchecked boxes that later decisions overtook, and each of those says so. Within a milestone, keep one commit series per concern.

1. **P0** — ADR 0006, the target, the ledger, the gate.
2. **P1** — record every site's Jekyll build (it needs Jekyll, so it comes before any site loses its Ruby).
3. **P2** — the studio foundation (`web/`). From here on, every milestone ships its studio views and their extension counterparts (or records the gap).
4. **G3** — accounts (the studio's sign-in, and parodynews's account capabilities).
5. **G8** — the AI content layer (parodynews in full).
6. **G4** — sites and jobs (the Rails catalog, writer and doctor in Python).
7. **P3** — the workspace tool in Python.
8. **G5** — distribution (LinkedIn, WordPress, GitHub pull requests).
9. **G7** — AIEO.
10. **G12**, then **G13** (with M17's remaining entity extraction) — monitor, then improve.
11. **G6** — media.
12. **G9** — books and the ABC wizard.
13. **P4**, then **P5-<site>** per site — the site renderer, then each site switches.
14. **G10** — close the remaining extension gaps.
15. **G11** and **P6** — retire the sources; no Ruby.
16. **H1**, **H2** — enterprise.

**Status, 2026-10-21.** [ADR 0004](../adr/0004-one-platform.md) makes `content/` the one platform: Rails is retired function by function, the apps are absorbed, the Wagtail admin is the CMS, the extension stays as its client, and the platform is built enterprise-ready. That is Phase G and Phase H below; M2 is closed, M16's Rails half is superseded, and M18–M20 are re-scoped there (each says so). G0 (this record) and G1 (`content/ops/`) landed in one PR.

**Status, 2026-10-19.** M0, M3–M15 landed together (one branch, one commit series per area, so the PR can still be split), as the content plane `content/` — additive, because no site has cut over yet (ADR 0002: the Jekyll files stay canonical for each site until it does). M1 and M2 are held on decisions, M16–M20 on §4.8's two-release rule, applied per site now that D1 is decided (ADR 0002, Phases E and F); each says what is done and what blocks the rest. Test paths are `content/tests/<area>/…` rather than `content/tests/<area>` run from the repository root; `cd content && python -m pytest -q` runs them all, on SQLite and (with `DATABASE_URL`) on Postgres + pgvector.

### Phase A: Foundation

- [x] **M0: AGENTS.md + hub conventions**
  - Tasks: promote `AGENTS.draft.md` → `AGENTS.md`; make the root `CLAUDE.md` a pointer to it; make sub-package `CLAUDE.md` files pointers or AGENTS.md sections; add `docs/adr/0001-target-architecture.md` linking to the note.
  - Files: `AGENTS.md`, `CLAUDE.md`, `*/CLAUDE.md`, `docs/adr/`.
  - Accept: `bin/zer0 check` passes; there is one canonical agent file.
  - Test: `bin/zer0 check && npx markdownlint-cli2 AGENTS.md`
  - Done: the draft was already at `AGENTS.md`, so "promote" became "merge": the root `CLAUDE.md`'s invariants moved into it and every `CLAUDE.md` is now a pointer whose `@AGENTS.md` line imports it (so Claude Code reads the same text other agents do); project `CLAUDE.md` files became their own `AGENTS.md` (the theme's was folded into its existing one), and Jekyll sites exclude `AGENTS.md` from their builds. A root `.markdownlint-cli2.jsonc` relaxes the two rules that contradict the one-paragraph-per-line gate, so the test passes.
- [ ] **M1: CI on standard-ci@v2 + monorepo release-please** — *amended by ADR 0006: the release components are the extension, the platform image and `web/`; there is no Ruby component.*
  - Tasks: add `.github/workflows/ci.yml` calling `bamr87/<hub>/.github/workflows/standard-ci.yml@v2` (the exact hub path is open decision D5) with a matrix from `bin/zer0 affected`; convert the root `release-please-config.json` to multi-package (`.`, `rails`, `apps/parodynews`, `packages/*`) with a `.release-please-manifest.json`; delete the nested release-please configs; fold the per-project workflows into the matrix (keep codeql and claude.yml).
  - Accept: one PR run executes check/test for affected projects only; release-please dry-run lists every package.
  - Test: `bin/zer0 affected --base origin/main && npx release-please release-pr --dry-run --repo-url=bamr87/zer0-CMS --token=$GITHUB_TOKEN` (dry-run, read-only); `actionlint`
  - Partly done, rest held: the root `ci.yml` already calls `bamr87/bamr87/.github/workflows/standard-ci.yml@v2` (D5's hub path), and every project — `content/` included, via the new `content.yml` — has one path-filtered root workflow, so a PR already runs only what it touches. Not done: multi-package release-please. The original repositories still release `jekyll-theme-zer0` and `zer0-image-generator` (docs/MONOREPO.md), so a second release line here would double-version them; how tags are prefixed once packages share this repository is the decision MONOREPO.md lists. Folding the per-project workflows into one matrix is left until then too: each carries setup (services, xvfb, Ruby/Python matrices) a generic matrix would lose.
- [x] **M2: Layout moves** — *closed, won't do ([ADR 0004](../adr/0004-one-platform.md) decision 9).*
  - Was: `git mv rails app`, `git mv src media package.json … clients/vscode/`, `git mv packages/zer0-mistakes frontends/jekyll-theme`, `git mv sites frontends/sites`.
  - Why closed: D5 is decided (the extension stays, as the platform's client), the Rails plane is retired rather than moved, and moving `package.json` off the root changes what the hub's `detect-stack` sees (docs/RELEASING.md: the root manifest's `private: true` steers it). `content/` already sits where the target layout put it.
- [x] **M3: Root docker compose**
  - Tasks: services `db` (pgvector/pgvector:pg16), `redis`, `content` (Django), `worker` (Celery), `app` (Rails), `app-jobs` (Solid Queue), `relay` (outbox relay), `imagegen`; delete the per-project compose files that duplicate these (keep the site-preview ones behind profile `sites`).
  - Accept: `docker compose up` gives healthy services; `/healthz` returns 200 on content and app.
  - Test: `docker compose up -d --wait && curl -fsS localhost:8000/healthz && curl -fsS localhost:3000/up`
  - Done, with three deviations: the content plane's services (`db` on pgvector/pgvector:pg16, `redis`, `content`, `worker`, `beat`, `relay`) are behind `--profile content`, because the Rails CMS needs none of them while no site has cut over to DB-first yet; the Rails service keeps its name `cms` on :3001 and runs Solid Queue in-process (no `app-jobs` until M16 gives it jobs); and the per-project compose files stay, since they are each project's own dev server. Verified: `docker compose --profile content up -d --wait db redis content worker beat relay` → all healthy, `/healthz` 200, a REST-started run executed by the worker, the relay delivering to the `zer0:content` stream.

### Phase B: Content plane

- [x] **M4: Wagtail skeleton from config**
  - Tasks: create `content/` from `apps/parodynews/src` settings; add Wagtail 6, Postgres + pgvector extension, `cms` app with `BasePage`, `ArticlePage`, `BookPage`, the `AgentManagedMixin` (note §2.2), custom `AbstractImage` with `ai_alt`, `ai_tags`, `embedding`, `embedding_model`; keep the parodynews app mounted read-only for now.
  - Accept: migrations apply; Wagtail admin loads; existing parodynews tests still pass.
  - Test: `cd content && pytest -q && python manage.py makemigrations --check --dry-run`
  - Deviations: Wagtail 7.4, not 6 (Wagtail 6 does not support the Django 5.2 LTS parodynews runs); parodynews's settings *shape* is kept (base/development/production/testing, all from the environment) but `parodynews` is not mounted — its data comes in through `import_parodynews` from a `dumpdata`, so the content plane carries none of parodynews's dependencies and parodynews's own suite is untouched; `ai_keywords` is JSON (SQLite and Postgres share one schema); vectors live in `graph.Embedding`, not on the page or image row (a revision would copy them); `front_matter` is an order-preserving JSON text field (Postgres `jsonb` sorts keys).
- [x] **M5: Headless APIs**
  - Tasks: Grapple (or Strawberry, D2) schema for the page types; Wagtail API v2 `/api/v2/pages/`; export `schemas/graphql/schema.graphql`; CI check for drift.
  - Accept: a GraphQL query for an `ArticlePage` returns StreamField JSON; the schema file is committed and checked.
  - Test: `pytest content/tests/api -q && python manage.py graphql_schema --out /tmp/s.graphql && diff /tmp/s.graphql schemas/graphql/schema.graphql`
  - D2 decided as Grapple (ADR 0001). StreamField JSON is `bodyJson` (Grapple's `rawValue` cannot represent a struct block); mutations sit behind a GraphQL view that authenticates agent tokens and enforces CSRF for browser sessions.
- [x] **M6: Importers (see §4)**: Jekyll → Wagtail, parodynews posts → ArticlePage.
  - Done: `import_jekyll` (idempotent; refuses to overwrite a page edited in Wagtail; links indexed in a second pass; front-matter `preview` images into a collection per site; ABC `alphabet:` → `letter` blocks) and `import_parodynews` (posts, `PostVersion` history as dated revisions by `legacy:import`, assistants as legacy definitions that cannot run). drsai's books import through `import_jekyll`.
  - [ ] `packages/books` `library/<slug>/` → `BookPage` + chapters (§4.5) — not started.
  - Found: `apps/parodynews/src/pages/_config.yml` refers to an undefined YAML alias (`*site_domain`), which Jekyll's YAML loader refuses as well; the importer reports it instead of guessing.
- [x] **M7: Jekyll exporter** so the static sites keep building from Wagtail (§4).
  - Done: `export_jekyll` and `roundtrip_jekyll`. An unchanged page exports its source byte for byte; an edited one renders typed fields over its original front matter, in its original key order. Every Jekyll site in the repository round-trips byte for byte — zer0-pages (210 files), drsai, the two demos and zer0-pages-remote — and so does the theme's docs site (376 files) from a pinned checkout (`ZER0_THEME_CHECKOUT`, fetched by `content.yml`; ADR 0005), on SQLite and on Postgres (`test_the_real_sites_round_trip_byte_for_byte`). The build-time switch to exporter output (§4.8) waits on D1.
- [x] **M8: Outbox + event schemas**
  - Tasks: `outbox` app (`OutboxEvent` written in the same transaction as publish/revision); relay to Redis Streams; `schemas/events/` CloudEvents JSON Schemas for `content.page.published`, `content.suggestion.created`, `agent.run.completed`, `app.user.interaction`; contract tests on both sides.
  - Accept: publishing a page writes exactly one outbox row; the relay delivers it at least once; consumers dedupe by event id.
  - Test: `pytest content/tests/outbox -q`
  - The Rails side of the contract is `rails/lib/zer0_cms/events.rb` + `rails/test/zer0_cms/test_event_contracts.rb` (stdlib, in `abc-engine.yml`). `content.suggestion.created` carries a `target` (`page:`/`image:`) so image suggestions fit; D6 decided as Redis Streams.

### Phase C: Agents, harness, graph (note §10 build order)

- [x] **M9 (build step 1a): Agent users, AgentRun/AgentStep, tool registry**
  - Tasks: `agents` app with the models from note §4; data migration creating the `Agents` group and `agent:seo`, `agent:editor`, `agent:drafter`, `agent:review` users with page and collection permissions; `@tool(effect, perms, rate)` decorator, registry, permission resolution to the agent user; LiteLLM wrapper; runner as a Celery task with a hand-rolled state machine (D3); OTel spans with `trace_id`.
  - Accept: a run of a fake tool records an `AgentRun` + steps; a tool with effect `publish` is refused unless the policy allows it; there is no superuser path.
  - Test: `pytest content/tests/agents -q`
  - Deviations: agent users and groups are provisioned at `post_migrate` (and by `sync_agents`), not in a data migration — Wagtail's page-permission rows do not exist until after migrations run. LiteLLM is an optional backend loaded lazily, not a pinned dependency; tests use `recorded` and `fake`. OpenTelemetry spans open when `opentelemetry` is installed; the trace id is recorded either way and crosses planes as `traceparent`.
- [x] **M10 (build step 1b): Suggestion model + editor sidebar**
  - Tasks: `Suggestion` (note §2.3), accept → new Revision by the agent user with `BlockProvenance`; Wagtail admin panel hook; port the extension's governance semantics (draft queue → Suggestion `pending`, approval → accept, brand guard → validator).
  - Accept: accepting creates one revision; rejecting records the status; the accept rate is queryable.
  - Test: `pytest content/tests/suggestions -q`
  - The editor side is a panel in every page's edit view plus an accept/reject view ("accept all of this run" = one revision). The brand guard is a rule-for-rule port of `src/core/governance/guard.ts`.
- [x] **M11 (build step 2a): Schema export + validated block tools**
  - Tasks: `manage.py wagtail_ai_schema` emits JSON Schema per block, versioned and stored on `AgentRun`; tools `content.get_schema`, `content.get_page`, `content.search`, `content.propose_edit` validated with `StreamBlock.to_python` + `clean()`.
  - Accept: invalid block JSON is rejected with the error; snapshot test of the schema output.
  - Test: `pytest content/tests/schema -q`
- [x] **M12 (build step 2b): Drafter + SEO agents**
  - Tasks: `AgentDefinition` fixtures for `drafter` (incl. "abc" and "story" profiles ported from `rails/lib/zer0_cms` and drsai) and `seo`; GraphQL `requestAgentRun`, `acceptSuggestion`; REST `/api/v2/agent-runs/` with SSE; both agents start at policy `suggest`.
  - Accept: "Draft with agent" yields a draft revision with provenance; SEO produces meta suggestions; the LLM is mocked in tests (recorded fixtures).
  - Test: `pytest content/tests/agents/test_drafter.py content/tests/agents/test_seo.py -q`
  - Definitions are YAML (`content/agents/definitions/`), synced by `sync_agents`; besides drafter (profiles `abc` — the Rails generator's offline lexicon path, ported — and `story`) and seo there are editor, review, brand, a11y and enrich. "Draft with agent" at policy `suggest` is suggestions that accept as one draft revision; at `draft` the drafter writes that revision itself.
- [x] **M13 (build step 3): pgvector + structural edges + related/semanticSearch**
  - Tasks: `graph` app with `Entity`, `Edge` (note §5); embeddings keyed by `content_hash` + `embedding_model`; structural edges from `ReferenceIndex`, page tree, tags, locale on publish; GraphQL `related`, `semanticSearch`, `entities`; REST `/api/v2/graph/` neighbors/path.
  - Accept: publishing builds `child_of` and reference edges; `related` returns kNN + 1-hop results; re-embedding is skipped when the hash is unchanged.
  - Test: `pytest content/tests/graph -q`
  - Embeddings default to a deterministic hashing model (`hashing-256`), so the graph works offline; `EMBEDDING_BACKEND=litellm` swaps in a real one. Internal Markdown links and wikilinks become `links_to` edges, since imported bodies keep their links as Markdown rather than `PageChooserBlock`s.
- [x] **M14 (build step 4): AgentReviewTask + evals in CI**
  - Tasks: `AgentReviewTask` (brand, a11y, factcheck) writing Wagtail comments; `EvalCase/EvalResult`; `manage.py run_evals --agent <slug>`; CI job runs the evals on mocked or recorded models; publishing an AgentDefinition revision requires a passing suite.
  - Accept: a failing review blocks the workflow; an eval regression fails CI.
  - Test: `pytest content/tests/workflow -q && python manage.py run_evals --all --recorded`
  - Added: an agent review cannot be a workflow's last task (approving the last task publishes as the approver, and an agent never publishes), and a definition with no eval cases can never go live.
- [x] **M15 (build step 5a): MCP server**
  - Tasks: FastMCP mounted at `/mcp` backed by the same registry (one definition, three surfaces); scoped tokens mapped to agent users; retire `clients/vscode/src/mcp` in favour of a thin proxy or registration that points at Django.
  - Accept: the MCP `tools/list` matches the registry; a token for `agent:seo` cannot call `content.propose_edit` on pages outside its permissions.
  - Test: `pytest content/tests/mcp -q && npm --prefix clients/vscode test`
  - Deviation: a Django view speaking MCP's Streamable HTTP (JSON responses) plus `manage.py mcp_stdio`, not a mounted FastMCP app (ADR 0001); the app is `mcp_server/` so it never shadows the `mcp` package.
  - [ ] Retire `src/mcp` in favour of the content plane's server — moved to M18: the extension's server works without a content plane, which is still optional while no site has cut over to DB-first yet.
- [x] **M16 (build step 5b): Rails app plane: content client, MCP client, outbox, personalization** — *struck: superseded by ADR 0004 and ADR 0006 (no Rails plane, no Ruby).*
  - Tasks: Rails stops writing content: remove `PageEditor`, file write-back and `SiteSync` writes; `ContentClient` (graphql-client, persisted queries); `agent_runs/agent_steps` mirror; `McpClient`; `HomepageAgent` (ranker, returns block IDs or variant keys); Rails outbox → Redis Streams; consume `content.page.published` for cache purge and LinkedIn distribution; emit `app.user.interaction`.
  - Accept: no Rails code writes content tables or files (a test greps for it); the homepage returns variant keys; the trace_id propagates.
  - Test: `cd app && bin/rails test && bin/rails zeitwerk:check`
  - Started: the Rails half of the event contract (`Zer0Cms::Events`, M8). Gated per site (Phase F): removing `PageEditor` and the file write-back for a site waits until that site has cut over — while its files are canonical, Rails writing them is the design (D16), and the content plane's `import_jekyll` picks those edits up.
  - *Superseded by [ADR 0004](../adr/0004-one-platform.md):* there is no Rails app plane to build. The "Rails stops writing content" half becomes G4's parity gate (the platform's `sites` app syncs and writes the same files); the content client, MCP client, personalization agent and Rails outbox are dropped. The event contract stays (the outbox still publishes `content.page.published`; `distribution` consumes it in G5).
- [ ] **M17 (build step 6): Entity extraction + GraphRAG + behavioral edges**
  - Tasks: enrichment agent on publish (entities, `mentions/about/similar_to` with a confidence threshold → Edge or Suggestion); GraphRAG retrieval (search → 1–2 hops → rerank); nightly Celery job aggregating Rails interaction events into `viewed_together` / affinity edges (aggregates only).
  - Accept: below-threshold edges become Suggestions; no raw user ids are stored in Django.
  - Test: `pytest content/tests/graph/test_enrichment.py content/tests/graph/test_behavioral.py -q`
  - Mostly done (tests in `content/tests/graph/test_graph.py`): GraphRAG retrieval (`graph_rag`, `graph.search`, GraphQL `graphSearch`); the `enrich` agent proposing `about`/`similar_to` edges, below-threshold ones as Suggestions; `app.user.interaction` aggregated into daily and co-view counts with no reader id stored, and a nightly `viewed_together` build.
  - [ ] Entity extraction proper: a tool that creates `Entity` rows (people, organisations, topics) from page text, and the publish-time trigger that runs `enrich`.

### Phase D: Clients and cleanup

- [ ] **M18: VS Code extension as a headless client** — *re-scoped as G10 ([ADR 0004](../adr/0004-one-platform.md)).* Gated by Phase F: deleting the extension's governance queue, ledger and harness only makes sense once the sites it edits are DB-first; until then they are what works without a server.: panel/dashboard read via GraphQL, edits go out as `propose_edit`, suggestions shown inline; delete `src/core/harness` and `governance/ledger.ts` duplicates. Test: `npm test`
- [ ] **M19: Media pipeline** — *re-scoped as G6.* The fields exist (`ContentImage.ai_alt/ai_caption/ai_tags`, `media.describe`, `media.propose_alt`); the image-save trigger and the image-generator integration are not started, and `image_engine.rb` stays until they replace it.: image save → event → alt/tags/focal/embedding using `zer0-image-generator`; delete `rails/app/services/image_engine.rb` and the vendored Ruby port. Test: `pytest content/tests/media -q`
- [ ] **M20: Remove superseded code** — *re-scoped as G11.* Gated per site by §4.8 (ADR 0002): nothing a site still depends on is removed before that site has cut over.: the news app's `parodynews` models (after the M6 import verifies), its React frontend, its Azure infra (D4 is decided: drop once a deployment target exists), Rails `Page/Term/Asset` tables (after the M7 exporter is live), books studio LLM client, dead drsai planning docs → `docs/archive/`. Test: `bin/zer0 run test --all`

### Phase E: Cutover — one home ([ADR 0002](../adr/0002-one-home-cutover.md))

Ordered: each step needs the one before it. A step that needs a credential, a repository setting, a DNS change or an archive stops and asks (AGENTS.md § Workflow 5); those are the owner's.

- [ ] **C0: Restore the imported history** — found 2026-10-19: #29 and #36 were *squash*-merged, so `main` holds each imported tree as one commit (`packages/zer0-mistakes`: 3 commits here, 770 in the original) and the rewritten histories survive only in `refs/pull/29/head`, `refs/pull/36/head` and the originals. Nothing is archived before this lands.
  - Tasks: a branch from `main` that removes the imported paths, merges each rewritten history back (`git merge --allow-unrelated-histories`, the tips taken from the PR refs so the hashes match what was reviewed), then replays every later `main` commit that touched those paths as its own commit, so the branch's tree ends equal to `main`'s.
  - Accept: `git diff main <branch>` is empty; `git log -- sites/drsai/_config.yml` and `git blame` reach the original commits. (The theme's graft stays as history; the theme itself has gone home, ADR 0005.)
  - Needs the owner: it must land as a **fast-forward** (`git push origin <branch>:main`). A GitHub merge commit keeps the history reachable, but `git log` and `git blame` still stop at the squash, because `main`'s side already carries the same lines. A fast-forward adds commits and rewrites none.
  - The same applies to law-ai#174 (`lawmode/`), gitorio#136 (`packages/gitnexus`, `packages/git-with-the-program`) and rewind-arcade#36 (`retro-pi/`), all squash-merged the same day — tracked in the hub's `docs/CONSOLIDATION.md`.
- [ ] **C1: Freeze and final delta**
  - Tasks: land or close every open pull request on the originals (zer0-image-generator, …; the theme is not one of them, ADR 0005), re-open drafts here under the package path; re-import what landed since #29/#36 with the MONOREPO.md recipe (the rewrite is deterministic, so the new commits merge onto the earlier import without duplicating it); turn off the originals' scheduled workflows (`*_ENABLED=false`) and disable issues and pull requests on them.
  - Accept: every original's `main` equals what is under its path here (minus the nested workflows removed at import); no original has an open pull request.
  - Test: `bin/zer0 check`, plus a tree comparison per original (`git diff --stat <original>/main HEAD:<path>` after `git fetch`).
- [ ] **C2: Releases from here** (the rest of M1) — *amended by ADR 0006: no `packages/zer0-image-generator` (ruby) component and no RubyGems publish; the gem's fate is P-D2.*
  - Tasks: release-please manifest mode with components `.` (extension, unchanged), `packages/zer0-image-generator` (ruby), `sites/drsai` (the story engine, python); prefixed tags; the manifest seeded from each original's last release (image generator `v0.9.0`, …); publish jobs for RubyGems and PyPI; delete the nested release-please configs. The theme releases from its own repository (ADR 0005).
  - Accept: a release-please dry run lists every component at its continued version; `bin/zer0 check` fails for a `publishes:` project without a component.
  - Needs the owner: `RUBYGEMS_API_KEY` (or RubyGems trusted publishing) and PyPI trusted publishing pointed at this repository.
- [x] **C3: The theme mirror** — *struck by [ADR 0005](../adr/0005-theme-goes-home.md): there is no mirror; `bamr87/zer0-mistakes` is the theme's home and `theme-mirror.yml` is deleted.*
  - Tasks: `mirror-theme.yml` — on a push to `main` that touches `packages/zer0-mistakes/**`, and on a theme release, commit the subtree onto `bamr87/zer0-mistakes` `main` as one fast-forward snapshot commit (`sync: zer0-CMS@<sha>`) and, on a release, tag it `v<version>`; the mirror's `.github/workflows/` is reduced to nothing that deploys, releases or opens pull requests.
  - Accept: the mirror's tree equals `packages/zer0-mistakes/` (less the workflows); the job refuses when the mirror's `main` is not the commit it last pushed; a consumer pinned to `@v<version>` builds.
  - Needs the owner: a `FLEET_TOKEN` with `contents:write` on the mirror; disabling its issues and pull requests.
  - Built: `.github/workflows/theme-mirror.yml` (kill switch `THEME_MIRROR_ENABLED`, default off). Armed only after C1: a local dry run of the first snapshot against today's mirror changes 99 files outside `.github/workflows/` (−5,981 lines) — the theme's own commits since the import, which this repository does not have yet, so a sync before C1 would revert them on the mirror.
- [ ] **C4: One Pages deploy** — *amended by ADR 0006: each site builds with Jekyll until its P5 switch, then with the renderer.*
  - Tasks: `pages.yml` builds every site under `sites/` and parodynews's sidecar into one artifact with each site's sub-path `baseurl` (ADR 0002 §4, amended by ADR 0005: the theme's docs stay on zer0-mistakes.com from the theme's repository, and this deploy targets this repository's project site); `year-of-ai.github.io` builds `sites/2005` into `/2005/` from this repository.
  - Accept: every route answers 200 in a link-checked preview; `bin/zer0 check` fails for a site with no route.
  - Needs the owner: enabling Pages for this repository (the domain stays with the theme).
  - Built: `.github/workflows/pages.yml`, `route:` + the `pages` task in `workspace.yml`, `bin/zer0 routes [--json]` and the `routes` rule in `bin/zer0 check`. Routed today: `/zer0-pages/`, `/drsai/`, `/zer0-pages-remote/`, `/demos/cookbook/`, `/demos/garden/`, `/wargames/`. Not routed, each with its reason in `workspace.yml`: parodynews (its sidecar's `_config.yml` uses an undefined YAML alias — C5), `sites/1987` (no Jekyll config since its repository was deleted), `sites/2005` (year-of-ai.github.io builds it), `sites/irony-works` (no Gemfile: it builds with GitHub Pages' own Jekyll after a node transplant step). Deploys only while `PAGES_DEPLOY_ENABLED` is `true`.
- [ ] **C5: Port what is left** — done so far: the news app's Jekyll sidecar is routed at `/parodynews/` (ADR 0003). *Amended by ADR 0006: parodynews's Playwright E2E becomes studio scenarios in G8; its Azure deploy is not ported (H1 is the deploy).*
  - Tasks: parodynews's Playwright E2E, container validation and Trivy jobs (the theme's workflows stay in the theme's repository, ADR 0005). parodynews's Azure deploy waits on D4.
  - Accept: every nested `.github/workflows/` file is ported or deleted with a reason; MONOREPO.md § What still depends on the original repositories is empty.
- [ ] **C6: Redirect and archive**
  - Tasks: one last commit per original (the theme excepted — it is not archived, ADR 0005) that replaces its Pages site with redirects to the new URL and its README with a pointer here; then archive it.
  - Accept: each old URL answers with a redirect to the new one.
  - Needs the owner: the archive itself.
- [ ] **C7: The fleet hub follows**
  - Tasks (in `bamr87/bamr87`): point the registry entries at this repository's sub-paths (registry-only rows), remove the seven absorbed submodules, and take the originals out of every loop (evolution, issue pipeline, fan-outs); `zer0-mistakes` is registered as a submodule again (T4) and a normal fan-out target.
  - Accept: the hub's drift gate is green; no hub loop opens a pull request on an archived repository.

### Phase F: DB-first, site by site (PLAN-D1, [ADR 0002](../adr/0002-one-home-cutover.md) §5)

One milestone per site, smallest first. A site is eligible once `roundtrip_jekyll` has been green for it for two consecutive releases.

- [ ] **D1-0: The switch** — `workspace.yml` gains `content_source: files | wagtail` per site (default `files`); `pages.yml` builds a `wagtail` site from `export_jekyll` output; a CI check fails when a `wagtail` site's committed Markdown differs from the export. Test: `bin/zer0 check && cd content && python -m pytest -q tests/exporters` — *re-scoped as P5 (ADR 0006): a site becomes platform-first when the renderer takes it over.*
- [ ] **D1-1: `sites/zer0-pages-remote`** · [ ] **D1-2: `sites/zer0-demo-garden`** · [ ] **D1-3: `sites/zer0-demo-cookbook`** · [ ] **D1-4: `sites/drsai`** · [ ] **D1-5: `sites/zer0-pages`** · [ ] **D1-6: `sites/1987`, `sites/2005`** (the theme's docs site is not a CMS site: it lives and publishes from `bamr87/zer0-mistakes`, ADR 0005) — *re-scoped as P5-<site>.*
  - Each: flip `content_source`, publish from the export, unblock that site's share of G4 (the platform stops importing its files and starts exporting them), G10 and G11.

### Phase G: One platform ([ADR 0004](../adr/0004-one-platform.md))

One branch `g<N>-<slug>`, one PR per milestone. **ADR 0006 applies to every milestone below:** an "admin view", "menu" or "admin form" means a studio view in `web/` and its extension counterpart (the Wagtail admin gets no new screens); a merged app's models are redesigned to TARGET.md's rules, not ported one to one; the milestone's first commit completes its source's rows in `capabilities.yml` from the code, and its last sets their status. Every absorption ends in a parity gate the ADR names; the old code goes in its own commit, citing the gate, and never before it is green. "Done" for a platform change is `content/AGENTS.md`'s definition.

- [x] **G0: ADR 0004 + this plan.** The record, Phase G/H, D5 decided, M2 closed, M16/M18/M19/M20 re-scoped; `AGENTS.md`, `README.md`, `docs/MONOREPO.md`, `docs/CICD.md`, `workspace.yml` say "the platform". Test: `bin/zer0 check && python3 tools/unwrap-prose.py --check --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$'`
- [x] **G1: The ops baseline** (`content/ops/`, the fleet's `BE`/`OPS` rows): `/healthz` (liveness, touches nothing), `/readyz` (database, cache, Redis), `/version`; `X-Request-Id` + `X-App-Version` on every response; one error envelope for REST (DRF handler + Django's own 400/403/404/500/CSRF on API paths), GraphQL (`extensions.code`/`request_id`) and MCP (`data.request_id`, `-32603` on a crash); JSON logging (`LOG_FORMAT=json`) with secret redaction and one access line per request; throttles per address, person and agent token; CORS allowlist; security headers with a report-only CSP; `drf-spectacular` → committed `schemas/openapi/openapi.json` with a CI drift step; Sentry when `SENTRY_DSN`; compose labels and log rotation; root `SECURITY.md`, `.env.example`, `.pre-commit-config.yaml`; the verify kit pointed at the platform and a real feature index.
  - Accept: every row has a test in `content/tests/ops/`; `tests/test_healthz.py` is superseded (its traceparent assertions moved); every existing test stays green.
  - Test: `cd content && python -m pytest -q && python manage.py spectacular --format openapi-json --urlconf ops.openapi --fail-on-warn --file /tmp/o.json && diff ../schemas/openapi/openapi.json /tmp/o.json`
  - Deviations: the DRF throttles also cover Wagtail's public `pages/images/documents` endpoints (per address; `NUM_PROXIES` keys the bucket behind a proxy); the OpenAPI document covers the platform's own endpoints only, because Wagtail's viewsets build their serializer per request; `handler500` is JSON only with `DEBUG=False`; the graph views' query-parameter errors moved from 400 to 422 (no consumer outside `content/`).
- [x] **G2: The admin shell and the editor's UX** — the Wagtail admin becomes the CMS: the zer0 design tokens mapped onto `--w-color-*` with light/dark/system, branding and login; dashboard panels (sites, suggestions inbox, agent activity, operations); menu groups (Suggestions, Agents, Sites, Reports); the suggestions **side panel** with a diff, a reject reason and accept-all-of-run, plus a cross-site inbox; "Draft with agent" and "Improve with agent" header buttons; agent runs as a viewset with filters, a steps timeline and cancel (the runner honours `cancelled`), evals and tokens (issue once, revoke); definitions inspect-only (decision 8); SEO/Social promote fields (`og_*`, `canonical_url`, `noindex`) and a read-only front-matter group; blocks `embed`, `document`, `table`, `typed_table`, `raw_html`, `liquid`, `callout` with richer rich text, each with a preview template **and** a `block_to_markdown` case; a theme-like preview via headless preview; `SiteSettings` (SEO defaults, analytics, feedback, brand voice, navigation, `content_source`); `BrandRules` per site; `Author`/`Series`/`Category`/`Entity` snippet viewsets; `FormPage`; i18n on; `publish_scheduled` on beat; search promotions; a seeded "Editorial" workflow (brand review → moderators); `.localhost` in `ALLOWED_HOSTS`; log actions for suggestion/run/token events; `seed_demo`. — *struck: superseded by P2 (ADR 0006 decision 2). The editor UX is the studio's; the backend items (blocks, `SiteSettings`, `publish_scheduled`, the Editorial workflow, log actions, `.localhost`, `seed_demo`) moved to P2.*
  - Accept: `content/tests/admin/` covers each; the byte-for-byte round trip still holds for every in-repo site; `verify/scenarios/admin-*.yml` pass with evidence.
  - Test: `cd content && python -m pytest -q && node verify/runner.mjs`
- [ ] **G3: `accounts`** — django-allauth `openid_connect` (one app per IdP from the environment), `allauth.mfa` TOTP + recovery codes, the Wagtail login routed to allauth with local accounts as the fallback, OIDC groups → Wagtail groups (`OIDC_GROUP_MAP`), `UserToken` (hashed, expiring, scoped; issued and revoked in the account menu) accepted by REST and GraphQL, password and session policy. Test: `pytest content/tests/accounts -q` (a fake IdP, recorded). *ADR 0006 adds parodynews's account capabilities: email sign-up with verification, login by code, password reset, GitHub login, passkeys (WebAuthn) beside TOTP, the session list, per-user ownership and sharing; `allauth.headless` serves the studio and the extension.*
- [ ] **G4: `jobs` + `sites`** — `Job` (kind, status, params, log, artifacts, cancel) on Celery with a live-log admin view; `ManagedSite` (Wagtail `Site` ⇄ checkout path, `content_source files|wagtail` — D1-0's switch — digests, last sync, doctor findings), discovery under `SITES_DIR`, sync as `import_jekyll` jobs, write-back as `export_jekyll` for `files` sites with the digest stale-write guard ported from `page_editor.rb`; `zer0 doctor` ported (`sites/doctor.py`, six checks, the same JSONL), `manage.py doctor`, `zer0-doctor.yml` switched. Gate: the Rails fixture sites sync and export byte for byte. Retires Rails `Site/Page/Asset/Term`, `SiteSync`, `PageEditor`, `Writer`, `Catalog`, the Ruby doctor. Test: `pytest content/tests/sites content/tests/jobs -q`
- [ ] **G5: `distribution`** — `Channel` (LinkedIn OAuth with an encrypted token; WordPress; GitHub-PR), the queue (pending → approved → published) and the ledger keyed by canonical URL, byte-compatible with the extension's; the brand guard is the `brand` agent; the LinkedIn client ported (`restli`, `oauth`, `posts`, `statistics`); tools `distribution.compose` (propose) and `distribution.publish` (publish, armed by `ZER0_LINKEDIN_PUBLISH`); consumes `content.page.published`; statistics ingest; admin queue, draft and published views and a report. Gate: the ported event contract tests plus a recorded transport fixture suite. Retires `rails/lib/zer0_cms/{distribution,linkedin}` and `zer0-linkedin.yml`. Test: `pytest content/tests/distribution -q`
- [ ] **G6: `media`** (M19) — the Python engine imported from `packages/zer0-image-generator` as a library; `ImageRun` jobs (dry-run, list-missing, generate, enhance; provider, parallelism, cost), `Composition`/`CompositionImage` (forge: direct → render → review → enhance), `StudioRender` and sweeps, `LibraryEntry` with FreeSVG sourcing, `ProviderCredential` (encrypted, environment fallback), the image-save trigger → `media.describe`/`propose_alt`, the `preview_images:` site-config editor; the Media studio menu. Gate: the same artifacts on the fixture site; credentials migrate. Retires `packages/zer0-image-generator/web/` and `rails/app/services/image_engine.rb`; the Ruby port and the gem leave this repository (ADR 0006 decision 11; P-D2). Test: `pytest content/tests/media -q` *The panel's features are studio views.*
- [ ] **G7: `aieo`** (all of `apps/aieo/`, ADR 0006) — the analyzers and scoring engine as modules; `ScoringPattern` snippets seeded from `prompts/patterns/*.md`; `AuditRun` (page or URL, five dimensions, evidence); tools `scoring.audit_page|audit_url|score_text|list_patterns|apply_pattern`; the ten prompt agents as `AgentDefinition` profiles at `suggest`; `Citation` and its check task; GA4/GSC/DataForSEO connectors as site settings with cached services; WordPress as a distribution channel; the Scoring menu (audit with the radar, patterns, citations, performance); the `aieo_*` MCP names kept as aliases. Gate: the ported backend tests and the same scores on the fixture pages. Retires `apps/aieo/`. Test: `pytest content/tests/scoring -q` *ADR 0006: every `aieo.*` row of the ledger — the content lifecycle, the CLI and root scripts as `manage.py` commands, reports as job artifacts, Qdrant replaced by pgvector — and the scores feed G12 and G13.*
- [ ] **G8: The AI content layer** (`content/ai/`; parodynews in full, ADR 0006 decision 7) — TARGET.md § The AI content layer: provider adapters behind one registry (`claude_code`, `anthropic`, `openai`, `litellm`, `recorded`, `fake`) with `agents/llm.py` as a front over it and a test that nothing else imports a provider SDK; `ProviderConfig` (encrypted, write-only credential; one default), `ModelEntry` and its sync job, the health test; `OutputSchema` with barodybroject's bundled schemas seeded; `Assistant` (propose-only), `Pipeline`/`PipelineStep`; `Brief` (generate → validated structured result → draft page through a suggestion, with metadata extraction); `Conversation`/`Message` (history replay, run, run-pipeline, assign, re-run, promote to a brief or a draft); every generation an `AgentRun` on Celery, `202` + `/api/v2/runs/<id>/events`, idempotency keys, budgets; YAML import/export; the studio's AI and Create areas and their extension counterparts; `import_parodynews` extended (assistants → `Assistant`, groups → `Pipeline`, schemas, content details → `Brief`, threads → `Conversation`); `ensure_admin` and the install wizard's bootstrap; the GitHub-issue error reporter as an optional logging handler. Gate: every `parodynews.*` ledger row `done` (or `dropped` by the owner), the import round trip, `content/tests/ai/`. Retires `apps/parodynews/` once P5-parodynews has moved its site. Test: `pytest content/tests/ai -q`
  - Was (ADR 0004): **G8: `conversations`** (parodynews) — chat over an `AgentRun` (messages as steps, replayed to any backend), `Playbook` (ordered agents), `OutputSchema` snippets, message → page draft, the provider settings page over `agents/llm.py` (sync, test, default), publish-as-PR through `distribution` (`export_jekyll` → branch → PR with `FLEET_TOKEN`). Gate: the `import_parodynews` round trip and the conversations tests. Retires `apps/parodynews/`. Test: `pytest content/tests/conversations -q`
- [ ] **G9: `books` + the ABC wizard view** — `import_books` (`library/<slug>/` → `BookPage`/`ChapterPage`, the continuity ledger → `Memory`), the `books.validate` tool and a `continuity` review profile, `export_manuscript`, the ABC wizard as an admin form over the `drafter` `abc` profile and `export_jekyll`. Gate: parity on `library/impairment` and the Rails wizard's fixtures. Retires `packages/books/src/` and the Rails ABC code. Test: `pytest content/tests/books -q`
- [ ] **G10: The extension at parity with the studio** (M18; ADR 0006 decision 9) — settings `zer0Cms.platform.url` and a token in secret storage; `src/core/platform/client.ts` (GraphQL over an injected `fetch`, never at activation — D11); panel and dashboard read pages, suggestions and runs from the platform when configured, edits go out as `content.propose_edit`, "Draft with agent" requests a run, suggestions inline; the MCP server proxies `content.*` when configured; file mode unchanged; governance/ledger/harness duplicates deleted only for `wagtail`-source sites. Test: `npm test` *ADR 0006: the same generated client as the studio; every studio capability in the content, review, create, AI and AIEO areas has its extension counterpart; P-D3 decides how webviews share UI. Gate: the ledger's report lists no `extension` gap in those areas.*
- [ ] **G11: Retire** (M20) — `rails/` (P3 replaced `bin/zer0`), `packages/zer0-image-generator/`, `apps/aieo/`, `apps/parodynews/`, `packages/books/src/`; the workflows `rails-app.yml`, `abc-engine.yml`, `zer0-linkedin.yml`, `aieo.yml`, `parodynews.yml`, `books.yml`; `workspace.yml`, `docs/MONOREPO.md`, `ATTRIBUTION.md` updated; one commit per removal, each citing its gate. Test: `bin/zer0 check && bin/zer0 run test --all` *ADR 0006: a source goes only when `tools/check_absorption.py` shows its rows `done` or `dropped`.*

- [ ] **G12: `monitor`** (ADR 0006 decision 8) — per-site checks on Celery beat: uptime, broken links, performance and Core Web Vitals (PageSpeed Insights/CrUX), accessibility (axe-core under Playwright in a browser worker), SEO, the doctor (G4), analytics ingest (GA4, Search Console, DataForSEO — G7's connectors), AIEO audits; `Check`, `CheckRun`, `Finding` (rule, severity, page, evidence, first/last seen, resolved) with history and trends; alerts (email, webhook, GitHub issue); the studio's Sites → Monitor views and the extension's findings for the open page. Test: `pytest content/tests/monitor -q`
- [ ] **G13: `evolve`** (ADR 0006 decision 8) — the editorial plan per site (narrative, pillars with target shares, directives); improvement agents (GitOps definitions at `suggest`) that read findings, analytics, AIEO scores and the plan and propose refreshes, fixes, internal links, new topics and citability rewrites as suggestions and briefs within the site's budget; outcome measurement on accepted proposals; M17's entity extraction. Test: `pytest content/tests/evolve -q && python manage.py run_evals --all --recorded`

### Phase H: Enterprise

- [ ] **H1: Deploy** — `deploy/compose.prod.yml` (web, worker, beat, relay, Postgres, Redis; secrets from the environment), `deploy/helm/zer0-cms/` (a Deployment per role, HPA on web, a PVC for media, external or subchart Postgres/Redis, `/readyz` probes), `.github/workflows/publish.yml` (build and push `ghcr.io/bamr87/zer0-cms` on a release tag, verify `/readyz` on the image), `docs/OPERATIONS.md` (backups with `pg_dump`, a restore drill, retention, rotation), `manage.py seed_demo` if G2 has not added it. Needs the owner: GHCR publish permission.
- [ ] **H2: Observability and tenancy hardening** — OpenTelemetry instrumentation for Django and Celery behind `OTEL_EXPORTER_OTLP_ENDPOINT` (extending `agents/tracing.py`), optional Prometheus `/metrics`, per-site budgets (`budget_usd` per `SiteSettings`, enforced by the runner), per-site token scopes, an agent-provenance audit report, the CSP enforced after a report-only soak, `WORK-10` (fleet workflow refs pinned) and the remaining `AGENT` rows of the hub's conformance report.

### Phase T: The theme goes home ([ADR 0005](../adr/0005-theme-goes-home.md))

The zer0-mistakes theme returns to `bamr87/zer0-mistakes`, gains a Rails theme studio there, and this repository consumes it as each site declares it. T1 and T2 are pull requests on two repositories; T3 lands inside G2; T4 is a pull request on the fleet hub.

- [x] **T1: The theme leaves this repository.** The monorepo's theme changes ported to `bamr87/zer0-mistakes` as a draft PR (`port/zer0-cms-2026-10`: ship-no-person, the setup-wizard fix, the settings byte copy — each with a `Ported-From:` trailer); `packages/zer0-mistakes/` removed; the `zer0-mistakes` project, its `/` route, eight `depends_on` edges and two `vendored:` entries gone from `workspace.yml`; `zer0-mistakes.yml` and `theme-mirror.yml` deleted; `pages.yml` without the theme's route and targeting this repository's project site; `drsai.yml` building against the theme's `main` checked out beside the site (weekly too); `content.yml` fetching the theme at a pinned tag into `.cache/zer0-mistakes` for the round-trip fixture (`ZER0_THEME_CHECKOUT`); ADR 0005; the docs. Test: `bin/zer0 check && cd content && ZER0_THEME_CHECKOUT=<checkout> python -m pytest -q`
- [ ] **T2: zer0 studio** (in `bamr87/zer0-mistakes`, `studio/`) — a Rails 8.1 app, Ruby 3.3, SQLite + Solid Queue + Solid Cable, that customizes, updates and designs the theme: tokens and skins edited at the source through a small SCSS declaration tokenizer with a diff, a digest-guarded atomic write and the design-system parity check; a registry of consumer sites (from `_data/consumers.yml` and `SITES_DIR`) with each site's theme keys edited in place; the theme's own scripts (`validate`, `audit-consumer`, `propagate.rb`, `release --dry-run`, `design-system-check.rb`, Jekyll builds) run as jobs with a live log and cancel; docs-site previews in a sandboxed cross-origin iframe; a WCAG contrast check; a theme doctor (token parity, 7-vs-9 skins, the default skin, the gem's missing backgrounds, the config byte copy, `studio/` excluded); version lockstep and the consumer pin matrix. Loopback-only unless a password is set, nonce CSP, confined paths, no network at boot, never in the gem. Then S2 (live CSS re-render, 9-skin before/after compare, new skins, the axe sweep, a companion theme PR for what the doctor flags), S3 (overrides, `audit-consumer --fix`, consumer previews against gem/remote/checkout, installer profiles), S4 (dispatch, bump PRs through the consumer kit, the hub roster). Test: `cd studio && bin/rails test && bin/rails zeitwerk:check`; the gem build unchanged; the docs site builds with `studio/` excluded.
- [x] **T3: The platform's theme record per site** (inside G2) — `SiteSettings.theme_source` (`gem|remote_theme|path`), `theme_version`, `theme_skin`, filled by `import_jekyll` from the site's `Gemfile`/`_config.yml`; a dashboard row comparing the pin with the newest `bamr87/zer0-mistakes` release (read on demand); a test that `export_jekyll` leaves the pin's bytes untouched. The CMS never edits, vendors or publishes the theme; a bump reaches a site through its own repository and the consumer kit. — *struck by ADR 0006 decision 4: the renderer ports the design at a recorded theme tag; the per-site design and skin live in the site settings (P2, G4).*
- [ ] **T4: The fleet hub follows** (in `bamr87/bamr87`) — `projects/zer0-mistakes` back as a submodule, the registry entry's mirror note and `scout: false` dropped, the `zer0-CMS` description without "plus the theme", `docs/CONSOLIDATION.md`'s rows; the drift gate green. Needs the owner: merging.

### Phase P: One Python platform, a React frontend, no Ruby ([ADR 0006](../adr/0006-one-python-platform.md))

One branch `p<N>-<slug>`, one PR per milestone, based on `main`. The target is [`TARGET.md`](TARGET.md); the gate is `tools/check_absorption.py`.

- [x] **P0: ADR 0006, the target, the ledger and the gate.** ADR 0006; `TARGET.md`; `capabilities.yml` (the platform's capability catalog with its surfaces, and every merged repository's capabilities with their targets); `tools/check_absorption.py` and its tests, run by `zer0-workspace.yml`; AGENTS.md's target section and this order of work; the overtaken milestones marked. Test: `python3 tools/check_absorption.py --report && python3 -m unittest discover tools/tests && bin/zer0 check`
- [ ] **P1: Record every site's Jekyll build** — for each routed site and the parodynews sidecar, build with Jekyll as today and write `web/site/fixtures/<site>/manifest.json`: every output path, its content type, a normalized text digest of each HTML page's main content, the feed and sitemap entries and the redirects; `tools/site_manifest.py` (stdlib Python) writes and compares manifests, with tests; a dispatch-only workflow that builds and commits them. Accept: a manifest per site; a second run is byte-identical. Test: `python3 -m unittest tools/tests/test_site_manifest.py && python3 tools/site_manifest.py --check`
- [ ] **P2: The studio foundation** (`web/`) — the workspace (`web/studio`, `web/packages/{api,ui,tokens}`); the client generated from `schemas/openapi/openapi.json` with a drift check; sign-in (session + CSRF, then `allauth.headless` with G3); the shell (site switcher, TARGET.md's areas, light/dark from the zer0 tokens); **Content**: page tree and filtered lists, the TipTap editor for the existing blocks with the Markdown round trip, fields and SEO, save as a draft revision, preview; **Review**: the suggestions inbox and the per-page panel with diffs, accept / reject with a reason / accept all of a run, revisions with diff and revert, publish, unpublish, schedule; **Create**: a page from a type, "Draft with agent"; **AI**: agent runs with step timelines. Platform side: the endpoints these need, with tests, and G2's backend items. Served by Django at `/studio/`, by Vite in development. Accept: Vitest suites; `verify/scenarios/studio-*.yml` (create a page, accept a suggestion, publish) pass with evidence; `content/` green; schemas regenerated and committed; the ledger's `studio` surfaces updated. Test: `cd web && npm test && npm run build && cd ../content && python -m pytest -q && cd .. && node verify/runner.mjs`
- [ ] **P3: The workspace tool in Python** — `bin/zer0` in Python with the same commands and output; `tools/workspace/` tests ported; `zer0-workspace.yml`, `pages.yml` and `sites.yml` with no `setup-ruby` and no `ruby -e`; `bin/zer0 doctor` runs the platform's doctor (G4). Accept: the Ruby and Python tools print the same `list`, `affected --json`, `matrix`, `routes --json` and `check` on this tree (recorded before the Ruby goes); the ratchet's `bin/zer0` and `tools/workspace/` at 0. Test: `python3 -m unittest discover tools/workspace && bin/zer0 check`
- [ ] **P4: The site renderer** (`web/site/`) — reads an exported source tree (config, data, collections, posts, pages, the includes content uses), evaluates Liquid in content with `liquidjs`, renders Markdown with kramdown-compatible unified plugins, lays out pages with the zer0 design ported to React at a recorded theme tag (layouts, navigation, skins, SEO tags, feeds, sitemap, robots, Pagefind search, redirects), writes static HTML; `npm run site -- --site <name> [--compare]` against P1's manifests. Accept: both demo sites match their manifests. Test: `cd web && npm test && npm run site -- --site zer0-demo-garden --compare`
- [ ] **P5-<site>: Each site switches to the renderer**, smallest first — `zer0-demo-garden`, `zer0-demo-cookbook`, `zer0-pages-remote`, `2005`, `wargames`, `irony-works`, `1987`, `drsai`, `parodynews` (the sidecar's posts), and `zer0-pages` last (its Obsidian bridge — wikilinks, embeds, callouts, Dataview, the graph index — ported as renderer plugins first). Each: the renderer matches the site's manifest; `pages.yml` builds the site with it; the site's `Gemfile`, `Gemfile.lock`, `_plugins/` and Jekyll-only config leave in the same commit; its content imports into the platform and round-trips. Replaces Phase F's D1 milestones.
- [ ] **P6: No Ruby** — every ratchet ceiling at 0 and `ruby_ratchet:` empty, so the gate refuses any Ruby file; `codeql-analysis.yml` without its `ruby` leg; `.vscode/tasks.json` without the Ruby task; no workflow installs Ruby. (`src/core/harness/render.ts` still *generates* `setup-ruby` for other repositories' lanes; that is data about those repositories, not Ruby here.) Test: `python3 tools/check_absorption.py && ! git ls-files | grep -E '\.(rb|rake|ru|erb|gemspec)$'`

## 4. Content and data migration

1. **Freeze**: tag `pre-migration` (via the PR merge, not a manual push); record counts of files per site and rows per parodynews table.
2. **Jekyll/Obsidian → Wagtail (M6)**: `manage.py import_jekyll --site <name> --path frontends/sites/<name>`: one Wagtail `Site` + root per Jekyll site; collections/`_posts` → `ArticlePage`; front matter → typed fields per `schemas/zer0.schema.json` (title, date, tags → taggit, categories → snippet, `seo_title`, `search_description`); body Markdown → StreamField `markdown`/`rich_text` blocks (paragraph split); images → Wagtail Images in a collection per site; internal links → `PageChooserBlock` after a second pass; the original path is kept in `legacy_path` for redirects. Obsidian wikilinks resolve the same way.
3. **Governance state**: extension `.cms/` drafts, approvals and ledger → `Suggestion` (pending/accepted) and `AgentRun` rows with `legacy_ref`.
4. **parodynews DB**: `Post`+`PostFrontMatter` → `ArticlePage`; `PostVersion` → Revisions (ordered, authored by a `legacy:import` user); `Assistant`/`AIModel` → `AgentDefinition`; `Thread`/`Message` → archived JSON or `AgentRun` (D-open); dumped with `dumpdata` first. *ADR 0006 (G8): `Assistant` → `ai.Assistant` (not `AgentDefinition`), `AssistantGroup` → `Pipeline`, `JSONSchema` → `OutputSchema`, `ContentDetail`/`ContentItem` → `Brief`, `Thread`/`Message` → `Conversation`/`Message`, `AIProviderConfig` → `ProviderConfig` (credentials re-entered, never exported), `AIModel` → `ModelEntry`.*
5. **books / drsai**: `library/<slug>/` → `BookPage` with chapter children; drsai stories → `BookPage` (profile `story`).
6. **Rails DB**: `Site` rows stay in Rails as the registry (with a `wagtail_site_id`); `Page/Term/Asset` are derived caches, so drop them rather than migrate after verifying they match the files; `Channel` and LinkedIn tokens stay. *ADR 0006: the registry is the platform's `ManagedSite` (G4); Rails keeps nothing.*
7. **Verification**: an idempotent importer (re-run = no changes); a round-trip test `import → export → diff` against the original Jekyll tree (allow whitespace/front-matter key order); count parity report; redirect map from `legacy_path`.
8. **Cutover per site**: the Jekyll build switches from repo Markdown to exporter output (M7); the repo Markdown stays until the round trip is green for two releases.

## 5. Agent, harness and graph phases

They follow the note's §10 order exactly: M9–M10 (step 1), M11–M12 (step 2), M13 (step 3), M14 (step 4), M15–M16 (step 5), M17 (step 6). Invariants checked in every phase:

- Every tool resolves to an agent Django user; no superuser service account.
- Agents start at `suggest`; promotion to `draft`/`auto` needs the accept rate + evals above a threshold (recorded in the ADR).
- One revision per accepted outcome; intermediate work stays in the run/checkpointer.
- The exported schema version and `embedding_model` are stored with runs and vectors.
- Content is data: review agents get no `publish` tools; `write`/`publish` effects need policy + an eval gate.
- Rails reads content only via GraphQL/MCP; cross-plane writes go through the owning plane's API/tools.

## 6. CI/CD and docker compose

> ADR 0006: the target CI is `content.yml` (the platform), a `web.yml` (the studio and the renderer), `extension.yml`, `pages.yml` (the renderer per site) and `zer0-workspace.yml` (Python) — no Ruby. The bullets below describe the path there.

- **CI**: a single `ci.yml` calls `standard-ci@v2` with `bin/zer0 affected` producing the matrix (content: `pytest` + `makemigrations --check` + schema drift + recorded evals; app: `bin/rails test` + `zeitwerk:check`; clients/vscode: `npm test`; image-generator, books: existing tasks; the theme is gated in its own repository). Services: `pgvector/pgvector:pg16`, `redis:7`. Keep `codeql-analysis.yml` and `claude.yml`; remove the per-project workflows once they are covered.
- **Release**: release-please manifest mode, components `content`, `app`, `clients/vscode` (node, vsix), `packages/zer0-image-generator` (ruby). The theme releases from `bamr87/zer0-mistakes`. Conventional commits are required (squash merge titles).
- **Images**: `content/Dockerfile` carries `GIT_SHA`/`BUILT_AT` into `/version` and OCI labels; the deploy target is decided (ADR 0004: GHCR images, a production compose file and a Helm chart — H1).
- **Compose (root)**: `db`, `redis`, `content` (gunicorn), `worker` (celery), `beat`, `relay` (outbox → Redis Streams) behind `--profile content`, each with the fleet's labels and log rotation; `cms` (Rails) and `imagegen` until Phase G retires them. The root `.env.example` lists the compose keys; `content/.env.example` the platform's own.

## 7. Risks and open decisions

**Risks**

- Markdown → StreamField is lossy (Liquid tags, includes, raw HTML). Mitigation: a raw `markdown` block + round-trip tests.
- Files-as-truth to DB-as-truth is a philosophy change for the extension and the Jekyll users (git history no longer holds content). Mitigation: the exporter keeps git snapshots.
- parodynews's Django version and settings may not fit Wagtail 6 plus the monorepo layout; upgrading is possible churn.
- The scope (20 PRs) and two runtimes add ops load for a single maintainer.
- Prompt injection via imported content; LLM cost in CI (use recorded fixtures only).
- Vendored-copy drift checks break during the moves (M2).

**Open decisions**

- **D1** — *decided 2026-10-19 ([ADR 0002](../adr/0002-one-home-cutover.md)): DB-first, one site at a time (Phase F).* Does content become DB-first in Wagtail, with Jekyll repos as exported artifacts, or do Markdown files stay canonical with Wagtail as an index/editor?
- **D2**: Grapple vs Strawberry-Django for GraphQL.
- **D3**: LangGraph + Postgres checkpointer vs a hand-rolled state machine for the harness.
- **D4**: **Decided by [ADR 0003](../adr/0003-framework-rebuild.md).** barodybroject does not survive as a product or a brand: the app continues as `apps/parodynews/` until M20 absorbs its models; its Azure files stay de-branded (`parodynews` defaults) and deploy nothing from here until a deployment target is chosen.
- **D5** — *decided 2026-10-21 ([ADR 0004](../adr/0004-one-platform.md)): the extension stays, as the platform's editor client (G10); the hub path is `bamr87/bamr87/.github/workflows/standard-ci.yml@v2`.* The exact hub repo/path for `standard-ci@v2`, and whether the VS Code extension stays in this monorepo or splits out.
- **D6**: Event bus: Redis Streams (default) vs NATS.
- **P-D1** (ADR 0006): when the Wagtail admin closes to editors — proposed: when the studio covers every editor task the admin offers (P2 plus G3–G9's views), checked against a list in the PR that closes it.
- **P-D2** (ADR 0006 decision 11): the image-generator gem's fate once its engine is absorbed — retire it, or send it home to `bamr87/zer0-image-generator` for outside Jekyll users, as the theme went home.
- **P-D3** (ADR 0006 decision 9): how the extension's webviews share UI with the studio — proposed: they render `web/packages/ui` React components, bundled at build time under the D14 allow-list (one UI, parity by construction); the alternative keeps the vanilla webviews and shares only the generated client.
- **P-D4**: the studio's home — proposed: served by Django at `/studio/` (same origin, session auth, one deploy); the alternative is a separate static host with token auth.
