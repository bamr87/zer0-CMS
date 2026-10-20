# PLAN: zer0-CMS → agent-native headless CMS (Django/Wagtail + Rails)

Source of truth for the target: `docs/plan/agent-native-design.md` (called "the note"; section numbers refer to it). Working rules: [`AGENTS.md`](../../AGENTS.md). The decision record is [ADR 0001](../adr/0001-target-architecture.md), which also makes the interim calls on §7's open decisions. One milestone = one Claude Code session = one PR. Tick boxes in the same PR that does the work.

## 0. What is in this repo today (review findings)

**Repos merged in** (from `ATTRIBUTION.md`, `workspace.yml` `upstream:` keys, `git log --merges`):

| Project (workspace.yml) | Path | Upstream | Notes |
|---|---|---|---|
| cms-extension | `src/ media/ schemas/` (root) | bamr87/zer0-CMS (fork of estruyf/vscode-front-matter v10.10.1, rewritten) | Merge history still carries estruyf PRs (#9xx–#1026) before the rewrite; zer0 PRs #13–#27 after |
| — governance layer inside the extension | `src/core/governance/` | bamr87/bash-cms (ported, not subtree) | draft queue, brand guard, approval, idempotency ledger |
| cms-rails | `rails/` | bamr87/zer0-CMS (PR #24 feat/rails-fleet-platform) | Rails 8.1 fleet CMS + stdlib `zer0` lib |
| zer0-mistakes | `packages/zer0-mistakes` | bamr87/zer0-mistakes | Jekyll theme gem `jekyll-theme-zer0`, own AGENTS.md + release-please |
| zer0-image-generator | `packages/zer0-image-generator` | bamr87/zer0-image-generator | Python engine + byte-identical Ruby port + web panel; own release-please + compose |
| books | `packages/books` | bamr87/books | Python bookshelf app + Claude studio |
| barodybroject | `apps/barodybroject` | bamr87/barodybroject | Django 5.2 + React, Azure Container Apps |
| drsai | `sites/drsai` | bamr87/drsai | Jekyll picture-book site + Python story engine |
| zer0-pages | `sites/zer0-pages` | bamr87/zer0-pages | Obsidian vault + Jekyll bridge |
| zer0-pages-remote, zer0-demo-cookbook, zer0-demo-garden | `sites/*` | same-name repos | remote_theme / installer demos |

**Per part: stack, features, models, APIs, tests, CI**

| Part | Stack | Features | Models / data | APIs | Tests | CI |
|---|---|---|---|---|---|---|
| Extension | TS, esbuild, no runtime deps | front-matter panel, dashboard, SEO insights, governance (drafts/guard/approval/ledger), harness lanes (`src/core/harness`), catering/distribution, analytics, portfolio, Claude agent panel (`src/agent`), MCP server (`src/mcp`, tools.ts ≈2.3k lines) | files + `zer0.json`, `.cms/` contract, `schemas/zer0.schema.json` | VS Code commands `zer0Cms.*`, MCP tools | `src/test` via vscode-test | extension.yml, release.yml (release-please, node) |
| Rails | Rails 8.1, Ruby | indexes every registered site, writes edits back to files, ABC book wizard, LinkedIn distribution, image engine | `Site, Page, Term, Asset, Channel` (schema.rb) | HTML admin, `files`, `abc_books`, `linkedin_callbacks` | minitest (integration, services, zer0_cms) + `bin/test-stdlib` | rails-app.yml, zer0-doctor.yml, zer0-linkedin.yml |
| rails/lib/zer0_cms | stdlib Ruby | catalog, doctor, ABC generator with `ContentProvider` (Deterministic, Anthropic) | — | CLI | stdlib tests | rails-app.yml |
| barodybroject | Django 5.2, DRF, React/Vite, Postgres, Azure | AI parody news generation, assistants, threads, posts with front matter + versions | `JSONSchema, AIModel, Assistant, AssistantGroup(+Membership), AIProviderConfig, AppConfig, FieldDefaults, ContentItem, ContentDetail, Post, PostFrontMatter, PostVersion, Thread, Message, PoweredBy` | DRF `parodynews/api/urls.py` | pytest + Vitest (frontend) | barodybroject.yml |
| books | Python | validate/compile/edit book projects, Claude studio | `library/<slug>/` files | CLI/local app | pytest | books.yml |
| image-generator | Python + Ruby gem + web | AI preview/social images | files | CLI, Jekyll plugin | py + ruby tests | zer0-image-generator.yml |
| zer0-mistakes | Jekyll, Ruby, Node, Docker | theme, installer, propagation | — | — | `scripts/bin/test` | zer0-mistakes.yml |
| Sites | Jekyll / Obsidian | content | Markdown + front matter | — | build | sites.yml, zer0-pages.yml, drsai.yml, abc-engine.yml |
| Workspace tooling | Ruby `bin/zer0`, `tools/workspace` | registry check, affected, vendor drift | `workspace.yml`, `fleet.manifest.yml` | CLI | — | zer0-workspace.yml, ci.yml, markdown-oneline.yml, codeql, claude.yml |

**Duplication and dead code**

1. **Five LLM clients**: extension `src/agent`, `rails/lib/zer0_cms` Anthropic provider, barodybroject provider layer (`AIProviderConfig`/`AIModel`), books studio, drsai story engine (plus image-generator). Target: one Django tool registry + LiteLLM, and `ruby_llm` only for Rails app agents.
2. **Two ledgers**: `src/core/governance/ledger.ts` and `src/core/harness/ledger.ts`, both idempotency/run records. They become `AgentRun/AgentStep` in Django.
3. **Two content models**: Rails `Page/Term/Asset` vs barodybroject `Post/PostFrontMatter/PostVersion/ContentItem`, both shadowing Markdown files. Both are replaced by Wagtail pages, revisions and snippets.
4. **Two MCP surfaces in waiting**: extension `src/mcp` (TS) vs the note's Django MCP server.
5. **Image engine twice**: Python engine + "byte-identical Ruby port" + `rails/app/services/image_engine.rb` + vendored copies tracked by `bin/zer0 vendor`.
6. **Per-package infra leftovers from the subtree imports**: 3 nested `release-please-config.json` (root, zer0-mistakes, image-generator), 10+ `docker-compose.yml` (incl. `apps/barodybroject/src/posthog/`), 9 `CLAUDE.md`, but only one `AGENTS.md` (zer0-mistakes).
7. **CI is not on hub conventions**: 18 workflows, none call `standard-ci@v2`; release-please covers only the root node package.
8. **Dead/obsolete**: pre-rewrite estruyf history (keep it in git, but nothing in-tree depends on it); commented-out reusable-workflow calls (`zer0-doctor.yml`, `zer0-linkedin.yml` refs); barodybroject Azure `infra/` and `azure.yaml` if Azure is dropped; `sites/drsai` planning docs (`PRD*.md`, `IMPLEMENTATION_PLAN.md`, `newsletter_seuss.md`, `reena_poem.md`, `Family newsletter.md`) at the site root; `src/test/fixtures/sites/wikijs/docker-compose.yml` is a fixture, so keep it.

## 1. Inventory → target mapping

| Source | Features | Lands in | Action |
|---|---|---|---|
| barodybroject Django project | Django settings, DRF, Postgres, auth | `content/` (Django + Wagtail project base) | **Evolve**: becomes the content plane skeleton |
| barodybroject `Post/PostFrontMatter/PostVersion/ContentItem/ContentDetail` | posts, versions | Wagtail `ArticlePage` + `Revision` | Migrate data, then drop the models |
| barodybroject `Assistant/AssistantGroup/AIModel/AIProviderConfig` | agent config | `content/agents`: `AgentDefinition` (snippet + RevisionMixin), LiteLLM config | Migrate, then drop |
| barodybroject `Thread/Message` | chat history | `AgentRun/AgentStep` (kind=llm) | Migrate if needed, otherwise archive |
| barodybroject `JSONSchema/FieldDefaults` | content schemas | `wagtail_ai_schema` export (note §2.1) | Replace |
| barodybroject React frontend | admin UI | — | **Drop** (Wagtail admin replaces it); keep it only as a reference in git history |
| barodybroject Azure infra | deploy | — | **Drop** (open decision D4) |
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
| zer0-mistakes theme | Jekyll theme | `frontends/jekyll` theme, fed by the exporter / headless API | Keep |
| sites/* | content | Imported into Wagtail (one `Site` per Jekyll site); Jekyll stays as a static frontend | Migrate |
| `bin/zer0`, `tools/workspace`, `workspace.yml` | registry | Keep, re-registered with the new projects | Update |
| 18 workflows | CI | `standard-ci@v2` caller + per-project matrix via `bin/zer0 affected` | Consolidate |

## 2. Target layout

```
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
  importers/             # jekyll, barodybroject, books, drsai
  exporters/             # jekyll exporter (static frontends)
  tests/
app/                     # Rails 8 (moved from rails/) — experience plane
  app/models             # User, Site(registry), Channel, AgentRun, AgentStep, Affinity, OutboxEvent
  app/services           # ContentClient (graphql-client), McpClient, HomepageAgent, LinkedinGateway
  lib/zer0_cms           # stdlib doctor/catalog (ABC generator removed)
clients/vscode/          # the extension (src/, media/, package.json) as a headless client
frontends/jekyll-theme/  # packages/zer0-mistakes
frontends/sites/         # sites/*
packages/zer0-image-generator/
schemas/                 # zer0.schema.json, events/*.json, graphql/schema.graphql (generated)
tools/                   # bin/zer0, workspace lib
docs/  AGENTS.md  CLAUDE.md -> AGENTS.md (one line pointer)
docker-compose.yml  workspace.yml  release-please-config.json  .release-please-manifest.json
```
Moving `rails/` → `app/` and `src/` → `clients/vscode/` is milestone M2 (pure moves, no logic).

## 3. Milestones

Each milestone: one branch `m<N>-<slug>`, one PR, green CI. Commands assume `docker compose up -d db redis` where noted.

**Status, 2026-10-19.** M0, M3–M15 landed together (one branch, one commit series per area, so the PR can still be split), as the content plane `content/` — additive, because no site has cut over yet (ADR 0002: the Jekyll files stay canonical for each site until it does). M1 and M2 are held on decisions, M16–M20 on §4.8's two-release rule, applied per site now that D1 is decided (ADR 0002, Phases E and F); each says what is done and what blocks the rest. Test paths are `content/tests/<area>/…` rather than `content/tests/<area>` run from the repository root; `cd content && python -m pytest -q` runs them all, on SQLite and (with `DATABASE_URL`) on Postgres + pgvector.

### Phase A: Foundation

- [x] **M0: AGENTS.md + hub conventions**
  - Tasks: promote `AGENTS.draft.md` → `AGENTS.md`; make the root `CLAUDE.md` a pointer to it; make sub-package `CLAUDE.md` files pointers or AGENTS.md sections; add `docs/adr/0001-target-architecture.md` linking to the note.
  - Files: `AGENTS.md`, `CLAUDE.md`, `*/CLAUDE.md`, `docs/adr/`.
  - Accept: `bin/zer0 check` passes; there is one canonical agent file.
  - Test: `bin/zer0 check && npx markdownlint-cli2 AGENTS.md`
  - Done: the draft was already at `AGENTS.md`, so "promote" became "merge": the root `CLAUDE.md`'s invariants moved into it and every `CLAUDE.md` is now a pointer whose `@AGENTS.md` line imports it (so Claude Code reads the same text other agents do); project `CLAUDE.md` files became their own `AGENTS.md` (the theme's was folded into its existing one), and Jekyll sites exclude `AGENTS.md` from their builds. A root `.markdownlint-cli2.jsonc` relaxes the two rules that contradict the one-paragraph-per-line gate, so the test passes.
- [ ] **M1: CI on standard-ci@v2 + monorepo release-please**
  - Tasks: add `.github/workflows/ci.yml` calling `bamr87/<hub>/.github/workflows/standard-ci.yml@v2` (the exact hub path is open decision D5) with a matrix from `bin/zer0 affected`; convert the root `release-please-config.json` to multi-package (`.`, `rails`, `apps/barodybroject`, `packages/*`) with a `.release-please-manifest.json`; delete the nested release-please configs; fold the per-project workflows into the matrix (keep codeql and claude.yml).
  - Accept: one PR run executes check/test for affected projects only; release-please dry-run lists every package.
  - Test: `bin/zer0 affected --base origin/main && npx release-please release-pr --dry-run --repo-url=bamr87/zer0-CMS --token=$GITHUB_TOKEN` (dry-run, read-only); `actionlint`
  - Partly done, rest held: the root `ci.yml` already calls `bamr87/bamr87/.github/workflows/standard-ci.yml@v2` (D5's hub path), and every project — `content/` included, via the new `content.yml` — has one path-filtered root workflow, so a PR already runs only what it touches. Not done: multi-package release-please. The original repositories still release `jekyll-theme-zer0` and `zer0-image-generator` (docs/MONOREPO.md), so a second release line here would double-version them; how tags are prefixed once packages share this repository is the decision MONOREPO.md lists. Folding the per-project workflows into one matrix is left until then too: each carries setup (services, xvfb, Ruby/Python matrices) a generic matrix would lose.
- [ ] **M2: Layout moves**
  - Tasks: `git mv rails app`, `git mv src media package.json … clients/vscode/`, `git mv packages/zer0-mistakes frontends/jekyll-theme`, `git mv sites frontends/sites`; update `workspace.yml`, workflow paths, compose, and vendored paths.
  - Accept: every project's `check` and `test` tasks are green; `bin/zer0 check` passes.
  - Test: `bin/zer0 run check --all && bin/zer0 run test --all`
  - Held: D5 (does the extension stay here or split out?) is open, and moving `package.json` off the root changes what the hub's `detect-stack` sees (docs/RELEASING.md: the root manifest's `private: true` steers it). The new project was placed where the target layout puts it (`content/`), so M2 no longer has to move it.
- [x] **M3: Root docker compose**
  - Tasks: services `db` (pgvector/pgvector:pg16), `redis`, `content` (Django), `worker` (Celery), `app` (Rails), `app-jobs` (Solid Queue), `relay` (outbox relay), `imagegen`; delete the per-project compose files that duplicate these (keep the site-preview ones behind profile `sites`).
  - Accept: `docker compose up` gives healthy services; `/healthz` returns 200 on content and app.
  - Test: `docker compose up -d --wait && curl -fsS localhost:8000/healthz && curl -fsS localhost:3000/up`
  - Done, with three deviations: the content plane's services (`db` on pgvector/pgvector:pg16, `redis`, `content`, `worker`, `beat`, `relay`) are behind `--profile content`, because the Rails CMS needs none of them while no site has cut over to DB-first yet; the Rails service keeps its name `cms` on :3001 and runs Solid Queue in-process (no `app-jobs` until M16 gives it jobs); and the per-project compose files stay, since they are each project's own dev server. Verified: `docker compose --profile content up -d --wait db redis content worker beat relay` → all healthy, `/healthz` 200, a REST-started run executed by the worker, the relay delivering to the `zer0:content` stream.

### Phase B: Content plane

- [x] **M4: Wagtail skeleton from barodybroject**
  - Tasks: create `content/` from `apps/barodybroject/src` settings; add Wagtail 6, Postgres + pgvector extension, `cms` app with `BasePage`, `ArticlePage`, `BookPage`, the `AgentManagedMixin` (note §2.2), custom `AbstractImage` with `ai_alt`, `ai_tags`, `embedding`, `embedding_model`; keep the parodynews app mounted read-only for now.
  - Accept: migrations apply; Wagtail admin loads; existing barodybroject tests still pass.
  - Test: `cd content && pytest -q && python manage.py makemigrations --check --dry-run`
  - Deviations: Wagtail 7.4, not 6 (Wagtail 6 does not support the Django 5.2 LTS barodybroject runs); barodybroject's settings *shape* is kept (base/development/production/testing, all from the environment) but `parodynews` is not mounted — its data comes in through `import_barodybroject` from a `dumpdata`, so the content plane carries none of barodybroject's dependencies and barodybroject's own suite is untouched; `ai_keywords` is JSON (SQLite and Postgres share one schema); vectors live in `graph.Embedding`, not on the page or image row (a revision would copy them); `front_matter` is an order-preserving JSON text field (Postgres `jsonb` sorts keys).
- [x] **M5: Headless APIs**
  - Tasks: Grapple (or Strawberry, D2) schema for the page types; Wagtail API v2 `/api/v2/pages/`; export `schemas/graphql/schema.graphql`; CI check for drift.
  - Accept: a GraphQL query for an `ArticlePage` returns StreamField JSON; the schema file is committed and checked.
  - Test: `pytest content/tests/api -q && python manage.py graphql_schema --out /tmp/s.graphql && diff /tmp/s.graphql schemas/graphql/schema.graphql`
  - D2 decided as Grapple (ADR 0001). StreamField JSON is `bodyJson` (Grapple's `rawValue` cannot represent a struct block); mutations sit behind a GraphQL view that authenticates agent tokens and enforces CSRF for browser sessions.
- [x] **M6: Importers (see §4)**: Jekyll → Wagtail, barodybroject posts → ArticlePage.
  - Done: `import_jekyll` (idempotent; refuses to overwrite a page edited in Wagtail; links indexed in a second pass; front-matter `preview` images into a collection per site; ABC `alphabet:` → `letter` blocks) and `import_barodybroject` (posts, `PostVersion` history as dated revisions by `legacy:import`, assistants as legacy definitions that cannot run). drsai's books import through `import_jekyll`.
  - [ ] `packages/books` `library/<slug>/` → `BookPage` + chapters (§4.5) — not started.
  - Found: `apps/barodybroject/src/pages/_config.yml` refers to an undefined YAML alias (`*site_domain`), which Jekyll's YAML loader refuses as well; the importer reports it instead of guessing.
- [x] **M7: Jekyll exporter** so the static sites keep building from Wagtail (§4).
  - Done: `export_jekyll` and `roundtrip_jekyll`. An unchanged page exports its source byte for byte; an edited one renders typed fields over its original front matter, in its original key order. Every Jekyll site in the repository round-trips byte for byte — the theme (376 files), zer0-pages (210), drsai, the two demos and zer0-pages-remote — on SQLite and on Postgres (`test_the_real_sites_round_trip_byte_for_byte`). The build-time switch to exporter output (§4.8) waits on D1.
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
- [ ] **M16 (build step 5b): Rails app plane: content client, MCP client, outbox, personalization**
  - Tasks: Rails stops writing content: remove `PageEditor`, file write-back and `SiteSync` writes; `ContentClient` (graphql-client, persisted queries); `agent_runs/agent_steps` mirror; `McpClient`; `HomepageAgent` (ranker, returns block IDs or variant keys); Rails outbox → Redis Streams; consume `content.page.published` for cache purge and LinkedIn distribution; emit `app.user.interaction`.
  - Accept: no Rails code writes content tables or files (a test greps for it); the homepage returns variant keys; the trace_id propagates.
  - Test: `cd app && bin/rails test && bin/rails zeitwerk:check`
  - Started: the Rails half of the event contract (`Zer0Cms::Events`, M8). Gated per site (Phase F): removing `PageEditor` and the file write-back for a site waits until that site has cut over — while its files are canonical, Rails writing them is the design (D16), and the content plane's `import_jekyll` picks those edits up.
- [ ] **M17 (build step 6): Entity extraction + GraphRAG + behavioral edges**
  - Tasks: enrichment agent on publish (entities, `mentions/about/similar_to` with a confidence threshold → Edge or Suggestion); GraphRAG retrieval (search → 1–2 hops → rerank); nightly Celery job aggregating Rails interaction events into `viewed_together` / affinity edges (aggregates only).
  - Accept: below-threshold edges become Suggestions; no raw user ids are stored in Django.
  - Test: `pytest content/tests/graph/test_enrichment.py content/tests/graph/test_behavioral.py -q`
  - Mostly done (tests in `content/tests/graph/test_graph.py`): GraphRAG retrieval (`graph_rag`, `graph.search`, GraphQL `graphSearch`); the `enrich` agent proposing `about`/`similar_to` edges, below-threshold ones as Suggestions; `app.user.interaction` aggregated into daily and co-view counts with no reader id stored, and a nightly `viewed_together` build.
  - [ ] Entity extraction proper: a tool that creates `Entity` rows (people, organisations, topics) from page text, and the publish-time trigger that runs `enrich`.

### Phase D: Clients and cleanup

- [ ] **M18: VS Code extension as a headless client** — gated by Phase F: deleting the extension's governance queue, ledger and harness only makes sense once the sites it edits are DB-first; until then they are what works without a server.: panel/dashboard read via GraphQL, edits go out as `propose_edit`, suggestions shown inline; delete `src/core/harness` and `governance/ledger.ts` duplicates. Test: `npm --prefix clients/vscode test`
- [ ] **M19: Media pipeline** — the fields exist (`ContentImage.ai_alt/ai_caption/ai_tags`, `media.describe`, `media.propose_alt`); the image-save trigger and the image-generator integration are not started, and `image_engine.rb` stays until they replace it.: image save → event → alt/tags/focal/embedding using `zer0-image-generator`; delete `app/app/services/image_engine.rb` and the vendored Ruby port in the Rails plane. Test: `pytest content/tests/media -q`
- [ ] **M20: Remove superseded code** — gated per site by §4.8 (ADR 0002): nothing a site still depends on is removed before that site has cut over.: barodybroject `parodynews` models (after the M6 import verifies), React frontend, Azure infra (per D4), Rails `Page/Term/Asset` tables (after the M7 exporter is live), books studio LLM client, dead drsai planning docs → `docs/archive/`. Test: `bin/zer0 run test --all`

### Phase E: Cutover — one home ([ADR 0002](../adr/0002-one-home-cutover.md))

Ordered: each step needs the one before it. A step that needs a credential, a repository setting, a DNS change or an archive stops and asks (AGENTS.md § Workflow 5); those are the owner's.

- [ ] **C0: Restore the imported history** — found 2026-10-19: #29 and #36 were *squash*-merged, so `main` holds each imported tree as one commit (`packages/zer0-mistakes`: 3 commits here, 770 in the original) and the rewritten histories survive only in `refs/pull/29/head`, `refs/pull/36/head` and the originals. Nothing is archived before this lands.
  - Tasks: a branch from `main` that removes the imported paths, merges each rewritten history back (`git merge --allow-unrelated-histories`, the tips taken from the PR refs so the hashes match what was reviewed), then replays every later `main` commit that touched those paths as its own commit, so the branch's tree ends equal to `main`'s.
  - Accept: `git diff main <branch>` is empty; `git log -- packages/zer0-mistakes/_layouts/default.html` and `git blame` reach the original commits.
  - Needs the owner: it must land as a **fast-forward** (`git push origin <branch>:main`). A GitHub merge commit keeps the history reachable, but `git log` and `git blame` still stop at the squash, because `main`'s side already carries the same lines. A fast-forward adds commits and rewrites none.
  - The same applies to law-ai#174 (`lawmode/`), gitorio#136 (`packages/gitnexus`, `packages/git-with-the-program`) and rewind-arcade#36 (`retro-pi/`), all squash-merged the same day — tracked in the hub's `docs/CONSOLIDATION.md`.
- [ ] **C1: Freeze and final delta**
  - Tasks: land or close every open pull request on the originals (zer0-mistakes, zer0-image-generator, …), re-open drafts here under the package path; re-import what landed since #29/#36 with the MONOREPO.md recipe (the rewrite is deterministic, so the new commits merge onto the earlier import without duplicating it); turn off the originals' scheduled workflows (`*_ENABLED=false`) and disable issues and pull requests on them.
  - Accept: every original's `main` equals what is under its path here (minus the nested workflows removed at import); no original has an open pull request.
  - Test: `bin/zer0 check`, plus a tree comparison per original (`git diff --stat <original>/main HEAD:<path>` after `git fetch`).
- [ ] **C2: Releases from here** (the rest of M1)
  - Tasks: release-please manifest mode with components `.` (extension, unchanged), `packages/zer0-mistakes` (`jekyll-theme-zer0`, ruby), `packages/zer0-image-generator` (ruby), `sites/drsai` (the story engine, python); prefixed tags; the manifest seeded from each original's last release (theme `v1.31.2`, image generator `v0.9.0`, …); publish jobs for RubyGems and PyPI; delete the nested release-please configs.
  - Accept: a release-please dry run lists every component at its continued version; `bin/zer0 check` fails for a `publishes:` project without a component.
  - Needs the owner: `RUBYGEMS_API_KEY` (or RubyGems trusted publishing) and PyPI trusted publishing pointed at this repository.
- [ ] **C3: The theme mirror**
  - Tasks: `mirror-theme.yml` — on a push to `main` that touches `packages/zer0-mistakes/**`, and on a theme release, commit the subtree onto `bamr87/zer0-mistakes` `main` as one fast-forward snapshot commit (`sync: zer0-CMS@<sha>`) and, on a release, tag it `v<version>`; the mirror's `.github/workflows/` is reduced to nothing that deploys, releases or opens pull requests.
  - Accept: the mirror's tree equals `packages/zer0-mistakes/` (less the workflows); the job refuses when the mirror's `main` is not the commit it last pushed; a consumer pinned to `@v<version>` builds.
  - Needs the owner: a `FLEET_TOKEN` with `contents:write` on the mirror; disabling its issues and pull requests.
- [ ] **C4: One Pages deploy**
  - Tasks: `pages.yml` builds every site under `sites/`, the theme's docs and barodybroject's sidecar into one artifact with each site's sub-path `baseurl` (ADR 0002 §4); `year-of-ai.github.io` builds `sites/2005` into `/2005/` from this repository.
  - Accept: every route answers 200 in a link-checked preview; `bin/zer0 check` fails for a site with no route.
  - Needs the owner: moving the `zer0-mistakes.com` custom domain from the theme repository's Pages to this one.
  - Built: `.github/workflows/pages.yml`, `route:` + the `pages` task in `workspace.yml`, `bin/zer0 routes [--json]` and the `routes` rule in `bin/zer0 check`. Routed today: `/` (theme docs + examples), `/zer0-pages/`, `/drsai/`, `/zer0-pages-remote/`, `/demos/cookbook/`, `/demos/garden/`. Not routed, each with its reason in `workspace.yml`: barodybroject (its sidecar's `_config.yml` uses an undefined YAML alias — C5), `sites/1987` (no Jekyll config since its repository was deleted), `sites/2005` (year-of-ai.github.io builds it). Deploys only while `PAGES_DEPLOY_ENABLED` is `true`.
- [ ] **C5: Port what is left**
  - Tasks: the theme's remaining reference workflows (Docker integration, the 9-skin visual snapshots, nightly, translation) as root workflows filtered to `packages/zer0-mistakes/**`, the issue autopilot and theme propagation only if still wanted; barodybroject's Playwright E2E, container validation and Trivy jobs. barodybroject's Azure deploy waits on D4.
  - Accept: every nested `.github/workflows/` file is ported or deleted with a reason; MONOREPO.md § What still depends on the original repositories is empty.
- [ ] **C6: Redirect and archive**
  - Tasks: one last commit per original (the mirror excepted) that replaces its Pages site with redirects to the new URL and its README with a pointer here; then archive it.
  - Accept: each old URL answers with a redirect to the new one.
  - Needs the owner: the archive itself.
- [ ] **C7: The fleet hub follows**
  - Tasks (in `bamr87/bamr87`): point the registry entries at this repository's sub-paths (registry-only rows), remove the eight submodules, and take the originals out of every loop (evolution, issue pipeline, fan-outs); `zer0-mistakes` stays registered as a mirror that is never a fan-out target.
  - Accept: the hub's drift gate is green; no hub loop opens a pull request on an archived repository or on the mirror.

### Phase F: DB-first, site by site (PLAN-D1, [ADR 0002](../adr/0002-one-home-cutover.md) §5)

One milestone per site, smallest first. A site is eligible once `roundtrip_jekyll` has been green for it for two consecutive releases.

- [ ] **D1-0: The switch** — `workspace.yml` gains `content_source: files | wagtail` per site (default `files`); `pages.yml` builds a `wagtail` site from `export_jekyll` output; a CI check fails when a `wagtail` site's committed Markdown differs from the export. Test: `bin/zer0 check && cd content && python -m pytest -q tests/exporters`
- [ ] **D1-1: `sites/zer0-pages-remote`** · [ ] **D1-2: `sites/zer0-demo-garden`** · [ ] **D1-3: `sites/zer0-demo-cookbook`** · [ ] **D1-4: `sites/drsai`** · [ ] **D1-5: `sites/zer0-pages`** · [ ] **D1-6: `sites/1987`, `sites/2005`** · [ ] **D1-7: the theme's docs site**
  - Each: flip `content_source`, publish from the export, unblock that site's share of M16 (Rails stops writing its files), M18 and M20.

## 4. Content and data migration

1. **Freeze**: tag `pre-migration` (via the PR merge, not a manual push); record counts of files per site and rows per barodybroject table.
2. **Jekyll/Obsidian → Wagtail (M6)**: `manage.py import_jekyll --site <name> --path frontends/sites/<name>`: one Wagtail `Site` + root per Jekyll site; collections/`_posts` → `ArticlePage`; front matter → typed fields per `schemas/zer0.schema.json` (title, date, tags → taggit, categories → snippet, `seo_title`, `search_description`); body Markdown → StreamField `markdown`/`rich_text` blocks (paragraph split); images → Wagtail Images in a collection per site; internal links → `PageChooserBlock` after a second pass; the original path is kept in `legacy_path` for redirects. Obsidian wikilinks resolve the same way.
3. **Governance state**: extension `.cms/` drafts, approvals and ledger → `Suggestion` (pending/accepted) and `AgentRun` rows with `legacy_ref`.
4. **barodybroject DB**: `Post`+`PostFrontMatter` → `ArticlePage`; `PostVersion` → Revisions (ordered, authored by a `legacy:import` user); `Assistant`/`AIModel` → `AgentDefinition`; `Thread`/`Message` → archived JSON or `AgentRun` (D-open); dumped with `dumpdata` first.
5. **books / drsai**: `library/<slug>/` → `BookPage` with chapter children; drsai stories → `BookPage` (profile `story`).
6. **Rails DB**: `Site` rows stay in Rails as the registry (with a `wagtail_site_id`); `Page/Term/Asset` are derived caches, so drop them rather than migrate after verifying they match the files; `Channel` and LinkedIn tokens stay.
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

- **CI**: a single `ci.yml` calls `standard-ci@v2` with `bin/zer0 affected` producing the matrix (content: `pytest` + `makemigrations --check` + schema drift + recorded evals; app: `bin/rails test` + `zeitwerk:check`; clients/vscode: `npm test`; image-generator, theme, books: existing tasks). Services: `pgvector/pgvector:pg16`, `redis:7`. Keep `codeql-analysis.yml` and `claude.yml`; remove the per-project workflows once they are covered.
- **Release**: release-please manifest mode, components `content`, `app`, `clients/vscode` (node, vsix), `packages/zer0-image-generator` (ruby), `frontends/jekyll-theme` (ruby). Conventional commits are required (squash merge titles).
- **Images**: Dockerfiles `content/Dockerfile`, `app/Dockerfile` (existing), built in CI on release tags; the deploy target is open (D4).
- **Compose (root)**: `db`, `redis`, `content` (gunicorn/runserver), `worker` (celery), `beat`, `relay` (outbox → Redis Streams, both planes), `app` (Rails), `app-jobs` (Solid Queue), `imagegen`; profile `sites` for Jekyll previews; profile `observability` for Langfuse/OTel collector. `.env.example` lists `LITELLM_*`, `DATABASE_URL`, `REDIS_URL`, `MCP_TOKEN_*`.

## 7. Risks and open decisions

**Risks**
- Markdown → StreamField is lossy (Liquid tags, includes, raw HTML). Mitigation: a raw `markdown` block + round-trip tests.
- Files-as-truth to DB-as-truth is a philosophy change for the extension and the Jekyll users (git history no longer holds content). Mitigation: the exporter keeps git snapshots.
- barodybroject's Django version and settings may not fit Wagtail 6 plus the monorepo layout; upgrading is possible churn.
- The scope (20 PRs) and two runtimes add ops load for a single maintainer.
- Prompt injection via imported content; LLM cost in CI (use recorded fixtures only).
- Vendored-copy drift checks break during the moves (M2).

**Open decisions**
- **D1** — *decided 2026-10-19 ([ADR 0002](../adr/0002-one-home-cutover.md)): DB-first, one site at a time (Phase F).* Does content become DB-first in Wagtail, with Jekyll repos as exported artifacts, or do Markdown files stay canonical with Wagtail as an index/editor?
- **D2**: Grapple vs Strawberry-Django for GraphQL.
- **D3**: LangGraph + Postgres checkpointer vs a hand-rolled state machine for the harness.
- **D4**: Deployment target: keep Azure Container Apps (barodybroject) or move elsewhere; and whether barodybroject survives as a product (a parody-news site on top of the new CMS) or is absorbed.
- **D5**: The exact hub repo/path for `standard-ci@v2`, and whether the VS Code extension stays in this monorepo or splits out.
- **D6**: Event bus: Redis Streams (default) vs NATS.
