<!-- kit: sdlc v0.1.0 · AGENTS.md is the CANONICAL agent instructions file (decision D4, UPS-AGENT-07/08). -->

# zer0-CMS

> How to work in zer0-CMS, the zer0 stack's agent-native headless CMS and monorepo: commands, layout, conventions, the plane boundary and the invariants the build enforces.

## What this repo is

zer0-CMS is becoming one agent-native, headless CMS: a **content plane** (Django + Wagtail, `content/`), an **experience plane** (Rails, `rails/`), and the VS Code extension (`src/`) and the Jekyll sites as clients and frontends ([ADR 0001](docs/adr/0001-target-architecture.md); one home, DB-first site by site, [ADR 0002](docs/adr/0002-one-home-cutover.md)). The build order is [`docs/plan/PLAN.md`](docs/plan/PLAN.md) (M0–M20), implementing [`docs/plan/agent-native-design.md`](docs/plan/agent-native-design.md) ("the note"); **until a milestone lands, the code as it is wins over the plan.** Where a project under `packages/`, `sites/`, `apps/` or `content/` has its own `AGENTS.md`, it governs that tree — read it first. Rails is never "the content engine" — that is `.cms/` (`src/core/contract/`).

"Done": extension — `npm run compile`, `npm test`; `rails/lib` — `rails/bin/test-stdlib`, no bundler; Rails app — `bin/rails test`, `bin/rails zeitwerk:check`, and after a `rails/Dockerfile` or `docker-compose.yml` change the image builds, boots and answers `/up`; `content/` — `pytest -q`, `makemigrations --check --dry-run`, no GraphQL schema drift.

## Stack & commands

```bash
npm install
npm run compile          # check-types + lint + all five bundles
npm run watch            # rebuild on change, then F5 in VS Code to launch the Extension Host
npm test                 # unit, golden, MCP stdio and integration suites
SITES_DIR=$HOME/github docker compose up --build                                   # fleet CMS → http://localhost:3001/admin
docker compose --profile content up -d --wait db redis content worker beat relay  # content plane → http://localhost:8000/admin/
bin/zer0 run check --affected                                                      # fast checks of every project this branch touched
```

```bash
# ── Extension (src/) — vanilla TypeScript, esbuild; fast loop needs Node >= 22.12 (require(esm)) ──
npm run check-types && npm run lint
npx tsc -p . --outDir out
npx mocha --ui tdd out/test/{core,fields,governance,golden,loop,fleet,engines,routes,webview,styling,platform,audit,harness,lanes}.test.js
npx mocha --ui tdd out/test/governance.test.js --grep "ledger"   # one suite or one test
npx @vscode/vsce package                                         # the .vsix

# ── Fleet CMS (rails/) — rails/lib stays stdlib-only ──
cd rails && bash bin/test-stdlib                                       # rails/lib, no bundler
ruby bin/zer0-cms doctor ../sites/drsai                                # zer0 stack alignment; exit 1 on error
ruby bin/zer0-cms new --theme "IT systems" --out ../sites/drsai        # an ABC book, headless
bundle install && bin/rails db:prepare && SITES_DIR=$HOME/github bin/rails server   # http://localhost:3000/admin
bin/rails test && bin/rails zeitwerk:check                             # image-engine tests need python3 + PyYAML
SITES_DIR=$HOME/github docker compose --profile imagegen up --build    # (repo root) + zer0-image-generator on :3000

# ── Content plane (content/) — Django 5.2 + Wagtail 7.4; see content/AGENTS.md ──
cd content && pip install -r requirements-dev.txt
python manage.py migrate && python manage.py sync_agents --publish     # agent users, definitions, evals → live
python -m pytest -q -m "not slow"                                      # fast tier; drop -m for big-site round trips
python manage.py makemigrations --check --dry-run && ruff check . && ruff format --check .
python manage.py run_evals --all --recorded                            # every agent's evals, no network
DATABASE_URL=postgres://… python -m pytest -q                          # the same suite on Postgres + pgvector
python manage.py import_jekyll --site drsai --path ../sites/drsai      # a site → pages (idempotent)
python manage.py roundtrip_jekyll --path ../sites/drsai                # import → export → byte-compare

# ── Workspace and docs (stdlib Ruby / Python, no installs) ──
bin/zer0 list && bin/zer0 check && bin/zer0 doctor
python3 tools/check-config-docs.py            # generated docs current: CONFIG.md §5 + the docs indexes (--write regenerates)
python3 tools/docs_index.py --lint            # every indexed doc has one H1 and a summary line
python3 tools/unwrap-prose.py --write --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$'
```

The fourteen-suite line omits the three suites that need an extension host or a built bundle ([`src/test/README.md`](src/test/README.md)).

## Layout

| Path | What lives there |
|---|---|
| `src/` | The extension: `core/` (pure Node), `mcp/`, `webview/`, the `vscode` shell, `test/` ([`src/README.md`](src/README.md)). |
| `media/`, `schemas/` | Stylesheets, icons and lane templates; `zer0.schema.json` and the content plane's schemas. |
| `rails/` | The fleet CMS; `rails/lib` is the stdlib-only zer0 library. |
| `content/` | The content plane. |
| `packages/`, `sites/`, `apps/` | Imported projects ([`docs/MONOREPO.md`](docs/MONOREPO.md)). |
| `bin/`, `tools/`, `workspace.yml` | `bin/zer0` and its registry, the docs gates, vendored `unwrap-prose.py`, `tools/history/` (cutover C0). |
| `docs/` | Guides, ADRs and the plan, indexed in [`docs/README.md`](docs/README.md). |
| `features/`, `verify/`, `fleet.manifest.yml` | The feature index, its scenarios, the one AI lane. |

## Conventions

- **Backlog of record:** GitHub Issues (`.github/sdlc.yml`) with the fleet labels — take `agent:ready`, never touch `agent:hold` or `human-review` — and `docs/plan/PLAN.md`'s milestones as the build order.
- **One milestone per PR:** the first unchecked one whose dependencies are done, on `m<N>-<slug>` from an up-to-date `main` (or the session's branch); one commit series per milestone if a branch carries several; unrelated fixes get their own PR. Tick its PLAN boxes in that PR, adding sub-tasks and deviations.
- **Definition of Done:** `.github/PULL_REQUEST_TEMPLATE.md`'s checklist, the "done" commands, the milestone's PLAN test commands, `bin/zer0 check` and `bin/zer0 run test` per affected project, pasted with results into the PR. Never tick a box over red or skipped tests.
- **Decisions:** ADRs in `docs/adr/NNNN-slug.md`, indexed in `docs/adr/README.md`; the extension's D1–D17 and D-A–D-I are in `docs/ARCHITECTURE.md`. **Stop and ask** (PR comment, box unchecked) on an open PLAN §7 decision, destructive data step or credential.
- **Commits:** Conventional Commits (`feat(content): …`), which release-please reads in manifest mode — no nested release-please config, no hand edits to `CHANGELOG.md` or a version. **Branches:** `m<N>-<slug>`, else `feature/`, `fix/`, `docs/`, `refactor/`, `test/` or `chore/` off `main`.
- **Never:** push to `main`, force-push, rewrite shared history, amend pushed commits, `--no-verify`, change repo settings, branch protection, secrets or workflow permissions, suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`), leave an empty exception handler, or hand-edit a generated or vendored file.
- **README-First, README-Last:** read the nearest `README.md` first, update it (and any behaviour doc) in the same PR. Every source file opens with a short block comment saying what it is and why. Markdown is one paragraph per line.

## The planes and their boundary

Non-negotiable; ADR 0001 records where today's code still crosses it and which milestone ends that.

- **`content/` owns** content, revisions, workflow, the graph, embeddings, the agent harness, the tool registry, the MCP server and the agents that write content. **`rails/` owns** users, sessions, personalization, app/commerce data, distribution channels and the agents that act on app state.
- Rails **never** writes content tables: it reads through GraphQL/REST or MCP and changes content only by calling content-plane tools (`content.propose_edit`) with a scoped agent token. *Transitional:* until M16 and decision D1, `PageEditor` and `Zer0Cms::Cms::Writer` still write Jekyll files (D16) — don't add a third Rails writer.
- Django never reads the Rails database; Rails data arrives as aggregated events (`app.user.interaction`) or via Rails MCP tools.
- Cross-plane side effects go through the transactional outbox and `schemas/events/`. Changing a schema means bumping its version and updating the contract tests on both sides.
- Frontends (the Jekyll sites, the theme) and clients (the extension) are headless: APIs, exported files and stored outputs, never a database.

## Agent safety rules in code

- Every tool declares `effect` (`read|propose|write|publish`) and `perms`, and runs as an agent Django user (`agent:<slug>`); no superuser service accounts.
- New agents start at policy `suggest`. One revision per accepted outcome; intermediate work stays in the run.
- Page content and user input are untrusted data; review agents get no publish tools.
- Tests never call live LLMs; use recorded fixtures or fakes.

## Extension rules the build enforces

Why each exists: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (decisions D1–D17) and [`src/README.md`](src/README.md).

- **`src/core/` and `src/mcp/` never import `vscode`** (eslint, and the MCP bundle marks nothing external — `Could not resolve "vscode"` from `npm run compile` *is* the gate). Take the editor as a parameter or an injected callback.
- **`src/webview/` never imports `vscode`, `commands/` or `views/`** (it speaks `postMessage` only) and never uses `innerHTML` — `el()` and `textContent`.
- **Zero shipped runtime dependencies** (D3/D14): `dependencies` stays empty; a build-time library is bundled only when named in that target's `esbuild.js` allow-list (today `@bamr87/fleet-engines` and `yaml`, into `dist/extension.js` alone); the MCP bundle allows no bare import; `@anthropic-ai/claude-agent-sdk` is the one optional dynamic import. YAML, globbing, dates, JSONC and Python-parity JSON stay hand-rolled in `src/core/shared/`.
- **The engines seam is never re-exported:** only `src/core/fleet/engines.ts` imports `@bamr87/fleet-engines`, never through `src/core/index.ts` (names collide); convert in `src/core/fleet/adapters.ts` and keep our tristate (`null` = "the manifest did not say").
- **The webview is UI, never the gate:** a button posts an intent and a target, never a payload or an override; every gate re-runs host-side in the function the command palette calls.
- **Import core through the barrel** (`../core`); declare cross-cutting types once, in `src/core/shared/types.ts`.
- **Goldens are generated** (`src/test/fixtures/golden/generate.py`, `{engines,lanes,platform}/generate.mjs`): regenerate and read the diff, never edit one to pass a test.
- **Five bundles** (`esbuild.js`): `extension`, `mcp-server` (nothing external), `panel`, `dashboard`, `agent`; a missing codicon file is a deliberate build error.

## Extension invariants that are easy to break

- **Configuration is three layers** (settings → `zer0.json` → `package.json` defaults); `src/config.ts` reads `inspect()`, not `get()`, and caches nothing ([`docs/CONFIG.md`](docs/CONFIG.md) §1).
- **Front matter is edited by line surgery** (`updateFrontMatterKeys()`): untouched lines stay byte-identical, and dates stay strings end to end.
- **The ledger is keyed by canonical URL** and written byte-compatible with Python's `json.dump` (`sort_keys`, `ensure_ascii`, indent 2, trailing newline).
- **The fleet plan is data:** every GitHub call is a `FLEET_PLAN` entry, guarded both ways by `fleetSurfaceIsRepoScopedOnly` (whole-segment allow-list) and `fleetPlanHasNoMergeVerbs`. The console never merges, approves, closes, removes a review label or reads a secret.
- **The Fleet console** takes only `{repo, lane}` from the webview; `src/commands/fleet.ts` re-reads the manifest, re-runs `evaluateFleetGates()` and derives a toggle from GitHub's value. `zer0Cms.fleet.dispatchAllow` is settings-layer only; network follows only a user action, through the injected `fetch` (D11).
- **Unknown is not off:** `listVariables`, `listWorkflows`, `recentRuns` and `openPulls` return `null`, not `[]`, on 403/404, and an unread cell says so.
- **A generated lane is files, never an armed loop:** no `*_ENABLED` variable created, no kill switch omitted, no guardrail weakened, no `factory--*.yml` targeted; `bespoke` from `classifyExpressibility` is a refusal with reasons.
- **A command acts on the site it was given:** `Zer0Shell.store` is the *active* site; never resolve `workspaceFolders[0]`; one `WorkspaceStore` per folder.
- **The platform is a profile:** nothing platform-specific outside `src/core/platform/profiles/`; `src/test/fixtures/golden/platform/` pins Jekyll's answers.
- **`.cms/` absence is normal:** the page index supplies `health: -1`, `freshness: 'unknown'`; never invent a score.
- **MCP registration is two-phase:** `provideMcpServerDefinitions` returns an empty `env`; `resolveMcpServerDefinition` reads the publish flag from the **settings** layer and sets a disabled flag to `null`. `ZER0_CMS_MCP_ALLOW_EXEC` (trusted only) gates `zer0_contract`, `ZER0_CMS_MCP_ALLOW_SCAFFOLD` gates `zer0_lane_scaffold`; a hand-started server only reads and drafts, and the server never opens a socket ([`docs/CONFIG.md`](docs/CONFIG.md) §6).
- **`src/core/harness/` is one vocabulary** for the editor agent and CI: `resolveHarnessProfile` alone decides roles, skills and model ([`src/core/harness/README.md`](src/core/harness/README.md)).
- **Eleven context keys, each gating something:** grep `package.json` before adding one; a key is a rendering hint, so every spawn re-asks `workspaceTrusted()`.
- **Adding a command:** `contributes.commands` (+ `menus`), `register(shell, id, …)` in its `src/commands/*.ts`, `ALL_COMMAND_IDS`, and `ALL_COMMANDS` in `src/test/extension.test.ts` with its `54` bumped ([`src/README.md`](src/README.md#adding-a-command)). Anything that writes, publishes or approves re-reads disk and re-runs `evaluateGates()` in the palette's function.

## Fleet CMS invariants (`rails/`)

Explained in [`docs/PLATFORM.md`](docs/PLATFORM.md).

- **Git is the source of truth; SQLite is an index** (D16): `Site#sync!` rebuilds it in one transaction; `PageEditor` and `Zer0Cms::Cms::Writer` are the only writers, each write re-syncs its path, no page row is saved from a form.
- **A stale write is refused twice** (indexed digest, form `base_digest`), re-checked before the atomic rename; an unchanged save writes nothing.
- **`rails/lib` is stdlib-only** (D15; CI: no bundle, Ruby 3.3 and 4.0.5); Rails-only code stays in `app/`.
- **The catalog is Jekyll 4.4's reader**, not a glob; its fixture lists come from Jekyll 4.4.1 (`bin/jekyll-parity`) — never re-baseline by hand.
- **Every disk path is confined** to realpaths inside `SITES_DIR`, through `SitePath`; escaping `source:` or `collections_dir:` is refused.
- **`ImageEngine` alone loads or runs zer0-image-generator**; its write goes through `PageEditor#replace_engine_write!`, its subprocess gets no credentials.
- **Loopback or a password:** `AccessGuard` reads `REMOTE_ADDR` and every `X-Forwarded-For` hop, never `remote_ip`; publish beyond 127.0.0.1 only with `ZER0_CMS_PASSWORD`.
- **No inline script or style:** per-request CSP nonce, no `unsafe-inline`, Administrate's compiled JS/CSS not loaded, flashes escaped.
- **The ABC wizard** exports only into an explicit Jekyll root; re-run it rather than hand-edit a generated book in drsai.

## The monorepo (`workspace.yml`, `bin/zer0`)

Explained in [`docs/MONOREPO.md`](docs/MONOREPO.md) and [`tools/workspace/README.md`](tools/workspace/README.md).

- **`workspace.yml` is the registry**; run a project's commands with `bin/zer0 run <task> <project>`, never restate them elsewhere.
- **A new directory under `packages/`, `sites/` or `apps/`, or a new top-level project, gets its `workspace.yml` entry in the same change**, with a root workflow or `ci: none — <reason>`, or `bin/zer0 check` fails.
- **Only the root `.github/workflows/` runs**, path-filtered per project; nested workflow files are reference copies.
- **Nothing under `packages/`, `sites/` or `apps/` assumes it is the git root**; resolve paths from the file.
- **A file two projects need is `vendored:`** in `workspace.yml` with one source (including `rails/`'s tokens CSS, art styles and front-matter schema): edit the source, `bin/zer0 vendor --write`, read the diff.
- **A Jekyll site lists `AGENTS.md` and `CLAUDE.md` under `exclude:`**, or Jekyll publishes them.
- **This repository is the only home** (ADR 0002): change an imported project here, never in its original; originals publish until cutover C1–C7, so don't archive one `docs/MONOREPO.md` still lists. `bamr87/zer0-mistakes` is a read-only mirror of `packages/zer0-mistakes/`.

## Fleet context

One of ~40 repositories managed by the [bamr87/bamr87 hub](https://github.com/bamr87/bamr87) (registry `_data/projects.yml`, standards in `specs/`), as a submodule: commit and push here first; the hub bumps its pointer afterwards. Prefer the hub's `templates/` kits; `ci.yml` (`standard-ci@v2`) and `markdown-oneline.yml` are hub-seeded callers — don't edit their logic. The other workflows are in [`docs/CICD.md`](docs/CICD.md); `claude.yml` (`@claude`) is the only one that calls a model and the one lane `fleet.manifest.yml` declares. Hub loops reach it by PR or label: the `fleet-pulse` doctor, the `issue-pipeline`, the fan-outs and `token-rotation`.

## Standard deviations

- **Lockfile committed** (2026-09-09), against `lockfiles: never-commit`: `npm ci` and the relock job need it, and the exact-pinned engines are only reproducible with one.
- **`@bamr87/fleet-engines` exact-pinned** (2026-09-09), against always-latest: a bump changes goldens, so it is a deliberate `chore(deps)` PR.
- **`yaml` bundled** (2026-09-09): the hand-rolled subset in `src/core/shared/config.ts` cannot read Actions workflows (anchors, merge keys, multi-line flows); extension host only, never the MCP server.
- **UPS-DOC-08:** four products' commands blocks sit on top of the 2,000-word prose budget.
