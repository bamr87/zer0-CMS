<!-- kit: sdlc v0.1.0 · AGENTS.md is the CANONICAL agent instructions file (decision D4, UPS-AGENT-07/08). -->

# zer0-CMS

> How to work in zer0-CMS while it becomes one Python platform with a React frontend (ADR 0006): the target and what an agent must not do, the commands, the layout, the conventions, the platform boundary and the invariants today's build enforces.

## What this repo is

**zer0-CMS is becoming a comprehensive application for content work — writing articles, creating content, brainstorming ideas, gathering information, operating a news site and writing books — with AI integrations and pipelines and workflows throughout, and every AI result something a person reviews.** Everything below serves that. It is being rebuilt — rewritten where a port would not scale — into **one Python platform with a React frontend**: a complete, modern CMS on established libraries, with an AI content layer that helps create and develop content, that manages, monitors and improves the sites it serves (AIEO included), and into which every repository that was merged here is **absorbed with its content, features and capabilities intact**. The decision is [ADR 0006](docs/adr/0006-one-python-platform.md); the target is described in [`docs/plan/TARGET.md`](docs/plan/TARGET.md); the order of work is [`docs/plan/PLAN.md`](docs/plan/PLAN.md) § 3; every capability — what the platform must do, on which surfaces, and what each merged repository brings — is the ledger [`docs/plan/capabilities.yml`](docs/plan/capabilities.yml).

- **Backend:** `content/`, Django + Wagtail **used as a headless library** (page tree, revisions, workflow, StreamField, images). It is the system of record, the agent runtime and the only server. Its agent-native rules ([ADR 0001](docs/adr/0001-target-architecture.md), [ADR 0004](docs/adr/0004-one-platform.md)) carry over unchanged.
- **Frontend:** `web/`, one React + TypeScript + Vite codebase with two halves: the **studio**, where people *manage*, *review* and *create* content and operate everything the absorbed apps did; and the **site renderer**, which turns each site's content into its static public site. It reaches the platform only through its APIs.
- **Client:** `src/`, the VS Code extension, is **built from the studio's code** — same TypeScript, React, libraries and generated client; its webviews render the studio's workspaces from `web/packages/`, and its own code is a thin VS Code host plus file mode. A studio capability without its extension counterpart is a gap the ledger reports.
- **AI content layer:** provider adapters behind one registry, assistants, pipelines, output schemas, briefs and conversations — barodybroject's model rebuilt onto the platform's agent runtime, every generation an async, costed, reviewable run (TARGET.md § The AI content layer).
- **Workspaces:** the studio is organised around what people do — Write, Create, Ideas, Research, Newsroom, Books, Sites — on one runtime of AI pipelines, editorial workflows and automations (TARGET.md § What it is for).
- **Content in the database, files generated:** every site and book lives in the platform and also exists as a generated, committed, re-importable file tree (a site's source, a book's `library/<slug>/`).
- **Sites:** manage (registry, settings, render, deploy), monitor (uptime, links, performance, accessibility, SEO, analytics, AIEO scores) and improve (agents propose changes from those signals; a person accepts them). Sites render with React by default; zer0-mistakes survives only as an option — render a site with that theme and deploy it with a Jekyll server.
- **No Ruby.** The workspace tool (`bin/zer0`) is Python already (PLAN P5); the Rails fleet CMS is gone ([ADR 0008](docs/adr/0008-retire-the-rails-cms.md)); the image generator's gem and the sites' Jekyll builds are being ported away, and until they are, a ratchet in CI stops Ruby from growing or spreading.
- **Every merged repository is absorbed, not discarded:** parodynews (formerly barodybroject — every one of its capabilities), aieo, books, the image generator, the Rails CMS, the workspace tool and the nine sites' content. A source directory is deleted only when the ledger shows every capability `done` (with a test), `dropped` by the owner, or — by the owner's decision, as for the Rails CMS — `specified`: what it did kept in a written spec the platform still owes ([`docs/plan/rails-cms-spec.md`](docs/plan/rails-cms-spec.md)).

**What an agent must not do** — each of these has happened, or is the next obvious mistake:

- Add Ruby anywhere, or build a feature on Rails, Jekyll or the image-generator gem that a later milestone would have to port. `tools/check_absorption.py` fails CI on new Ruby.
- Add screens to the Wagtail admin. New UI is React in `web/`, with its extension counterpart or a recorded gap.
- Call a model provider's SDK outside the adapter registry, or add a second LLM client, ledger or registry.
- Port a merged app's models and views one to one. Map its capabilities onto the platform's model (TARGET.md § Rules that keep models and views manageable) and import its data.
- Hand-roll what an established library already does (an editor, a diff, auth, a job queue, a schema validator, a query cache, a YAML or glob parser) without a reason in the pull request. **Less code is better**: configure a library, reuse a shared package, delete what the platform or a library now covers.
- Build an extension UI separately from the studio's. Extension webviews render `web/packages/` workspaces; the extension's own code is the VS Code host.
- Build a capability that only an API can reach. A capability is done when a person can use it from its studio workspace (and, where it belongs next to a file, from the extension).
- Add a dependency on zer0-mistakes — a vendored file, a fixture checkout, a CI job against it, a design port, an overlay. Only the Jekyll-theme option names it (`theme_allowed:` in the ledger); its home is `bamr87/zer0-mistakes` ([ADR 0005](docs/adr/0005-theme-goes-home.md)).
- Hand-edit a generated file tree (a site's exported source, a book's `library/<slug>/`) as if it were the source. Edit in the platform; the files are regenerated. Likewise a recorded site build (`web/site/fixtures/`): re-record it with `tools/site_manifest.py`, never edit it to make a check pass.
- Delete a source directory, a site or a capability because it looks obsolete, or mark a capability `dropped`. Deletion follows the ledger; dropping a capability, or deleting its source before it moved (`specified`), is the owner's decision.
- Run a fleet-wide kit (docs framework, governance, standards) over an imported project as if it were a live product. Imported projects under `apps/`, `packages/` and `sites/` are **sources being absorbed**; fleet kits apply to the platform, `web/` and the extension.
- Pick work by "the first unchecked box" in the plan. The order of work is PLAN § 3's list; older phases keep boxes later decisions overtook.
- Stack a pull request on another unmerged branch. Base every pull request on `main` (#52 merged into a dead branch and left `main` contradicting the owner for a day).

**Today's code vs. the target.** Until a milestone lands, the code as it is wins over the plan: the rules below that describe today's Jekyll sites are enforced by today's build and still hold — keep them working, but do not extend them. When a rule below and ADR 0006 seem to disagree about *new* work, ADR 0006 wins.

Where a project under `packages/`, `sites/`, `apps/` or `content/` has its own `AGENTS.md`, it governs that tree — read it first.

"Done": extension — `npm run compile`, `npm test`; after a `content/Dockerfile` or `docker-compose.yml` change the image builds, boots and answers `/readyz`; `content/` — `pytest -q`, `makemigrations --check`, ruff, the recorded evals and its three committed schemas unchanged ([`content/AGENTS.md`](content/AGENTS.md)).

## Stack & commands

```bash
npm ci                   # the root postinstall installs web/ from its lockfile too (dist/studio.js is built from it)
npm run compile          # check-types + lint + all six bundles
npm run watch            # rebuild on change, then F5 in VS Code to launch the Extension Host
npm test                 # unit, golden, MCP stdio and integration suites
docker compose --profile content up -d --wait db redis content worker research-worker beat relay belt-publisher events  # the platform → http://localhost:8000/studio/
bin/zer0 run check --affected                                                      # fast checks of every project this branch touched
```

```bash
# ── Extension (src/) — vanilla TypeScript, esbuild; fast loop needs Node >= 22.12 (require(esm)) ──
npm run check-types && npm run lint
npx tsc -p . --outDir out
npx mocha --ui tdd out/test/{core,fields,governance,golden,loop,fleet,engines,routes,webview,styling,platform,audit,harness,lanes}.test.js
npx mocha --ui tdd out/test/governance.test.js --grep "ledger"   # one suite or one test
npx @vscode/vsce package                                         # the .vsix

# ── The image generator's panel (packages/zer0-image-generator/), until PLAN G6 absorbs it ──
SITES_DIR=$HOME/github docker compose --profile imagegen up --build    # (repo root) zer0-image-generator on :3000

# ── The platform (content/) — Django 5.2 + Wagtail 7.4; see content/AGENTS.md ──
cd content && pip install -r requirements-dev.txt
python manage.py migrate && python manage.py sync_agents --publish     # agent users, definitions, evals → live
python -m pytest -q -m "not slow"                                      # fast tier; drop -m for big-site round trips
python manage.py makemigrations --check --dry-run && ruff check . && ruff format --check .
python manage.py run_evals --all --recorded                            # every agent's evals, no network
python manage.py spectacular --format openapi-json --urlconf ops.openapi --fail-on-warn --file ../schemas/openapi/openapi.json   # the committed OpenAPI document
DATABASE_URL=postgres://… python -m pytest -q                          # the same suite on Postgres + pgvector
python manage.py import_jekyll --site drsai --path ../sites/drsai      # a site → pages (idempotent)
python manage.py roundtrip_jekyll --path ../sites/drsai                # import → export → byte-compare
python manage.py seed_demo                                             # a demo site, the person `editor` (password zer0-demo under DEBUG), pending suggestions
# Docker, from the repository root: http://localhost:8000 (/studio/, /admin/, /graphql/, /api/v2/, /mcp/, /healthz, /readyz, /version)

# ── The studio (web/) — React 19, Vite, Mantine, TanStack Query, TipTap; see web/README.md ──
cd web && npm ci                                   # the committed lockfile (§ Standard deviations)
npm run dev                                        # http://localhost:5173/studio/, proxied to the platform on :8000
npm run lint && npm run typecheck && npm test      # ESLint (with the @zer0/ui host gate), tsc, Vitest
npm run build                                      # studio/dist/, which the platform serves at /studio/
npm run gen && npm run check:api                   # after the OpenAPI document changed: regenerate @zer0/api's types, then check them
node verify/runner.mjs --only studio-create-page,studio-accept-suggestion,studio-publish   # (repo root) the browser scenarios; see the runner's header

# ── Workspace and docs (Python 3.9+ and PyYAML, nothing else) ──
python3 -m venv .venv && .venv/bin/pip install pyyaml   # once, where python3 lacks PyYAML; bin/zer0 then runs on .venv
bin/zer0 list && bin/zer0 check && bin/zer0 tags       # projects; registry, paths, workflows and vendored copies agree; release tags
bin/zer0 doctor                                        # zer0 doctor over every in-repo site (content/sites/doctor.py; needs PyYAML and jsonschema)
.venv/bin/python -m unittest discover tools/workspace  # the tool's tests, with the golden replay of its Ruby predecessor
python3 tools/check-config-docs.py            # generated docs current: CONFIG.md §5 + the docs indexes (--write regenerates)
python3 tools/docs_index.py --lint            # every indexed doc has one H1 and a summary line
python3 tools/unwrap-prose.py --write --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$'

# ── The sites' recorded Jekyll builds (web/site/fixtures/, PLAN P1) — Ruby 3.3, bundler, network ──
python3 tools/site_manifest.py --check --site drsai    # rebuild a routed site as pages.yml does (UTC, none of your JEKYLL_/ZER0_ variables), compare
python3 tools/site_manifest.py compare --pages <recorded> <candidate>   # what a renderer must match: pages, titles, text, feeds, sitemaps, redirects
```

The fourteen-suite line omits the three suites that need an extension host or a built bundle ([`src/test/README.md`](src/test/README.md)).

## Layout

| Path | What lives there |
|---|---|
| `src/` | The extension, a client of the platform with the studio's capabilities from PLAN G10 (ADR 0006 decision 9), keeping its file mode: in file mode it edits a site's files; with a platform configured (`zer0Cms.platform.url`) its webviews render the studio's workspaces and its own code is the host around them. `core/` (pure Node; `core/studio/` is the bridge that gates every webview request), `mcp/`, `webview/` (file mode's), `studio/`, the `vscode` shell, `test/` ([`src/README.md`](src/README.md)). |
| `media/`, `schemas/` | Stylesheets, icons and lane templates; `zer0.schema.json` and the platform's schemas. |
| `content/` | The platform, including the studio's APIs (`api/session.py`, `api/pages.py`, `api/review.py`) and the built studio at `/studio/`; `content/ops/` is its operational baseline (probes, request ids, errors, logs, throttling, OpenAPI). |
| `web/` | The React frontend (PLAN P4): the studio (`web/studio/`) and the packages it is built from (`web/packages/`: `@zer0/api`, the client generated from the OpenAPI document; `@zer0/tokens`; `@zer0/ui`, the workspaces and their registry `WORKSPACES`, which take client, streams and navigation from their host so the extension's webviews render them; `@zer0/webview`, the extension's webview entry) ([`web/README.md`](web/README.md)). |
| `packages/`, `sites/`, `apps/` | Imported sources being absorbed, each capability a row in [`docs/plan/capabilities.yml`](docs/plan/capabilities.yml) ([`docs/MONOREPO.md`](docs/MONOREPO.md)). |
| `bin/`, `tools/`, `workspace.yml` | `bin/zer0` and its registry, the absorption gate (`check_absorption.py`), the docs gates, vendored `unwrap-prose.py`, `tools/history/` (cutover C0). |
| `docs/` | Guides, ADRs, the target (`plan/TARGET.md`) and the plan, indexed in [`docs/README.md`](docs/README.md). |
| `features/`, `verify/`, `fleet.manifest.yml` | The feature index, its scenarios, the one AI lane. |

## Conventions

- **During the overhaul, work lands directly on `main`** (the owner's direction of 2026-10-21: "these are breaking changes and a complete overhaul. no need for PRs until there's a working system"). Until the owner says the system works: no pull requests and no long-lived branches; parallel work happens in short-lived worktrees merged into `main` and deleted the same day. Afterwards changes return to branches (`m<N>-<slug>`, else `feature/`, `fix/`, `docs/`, `refactor/`, `test/` or `chore/`) and pull requests.
- **Backlog of record:** GitHub Issues (`.github/sdlc.yml`) with the fleet labels — take `agent:ready`, never touch `agent:hold` or `human-review` — and the order of work in `docs/plan/PLAN.md` § 3.
- **One milestone at a time:** the first milestone in PLAN § 3's order that is not done and whose predecessors have landed — not the first unchecked box in the file. One commit series per milestone; unrelated fixes get their own commits. Tick its PLAN boxes and set the status (and proof) of every `capabilities.yml` row it moved, in the same commits, adding sub-tasks and deviations.
- **Definition of Done:** the "done" commands, the milestone's PLAN test commands, `bin/zer0 check`, `python3 tools/check_absorption.py` and `bin/zer0 run test` per affected project, green before every push, with the commands and results in the commit message body (in the PR, under `.github/PULL_REQUEST_TEMPLATE.md`'s checklist, once pull requests return). Never tick a box over red or skipped tests.
- **Decisions:** ADRs in `docs/adr/NNNN-slug.md`, indexed in `docs/adr/README.md`; the extension's D1–D17 and D-A–D-I are in `docs/ARCHITECTURE.md`. **Stop and ask** (tell the owner, box unchecked) on an open PLAN §7 decision, destructive data step or credential.
- **Commits:** Conventional Commits (`feat(content): …`), which release-please reads in manifest mode — no nested release-please config, no hand edits to `CHANGELOG.md` or a version.
- **Never:** force-push, rewrite shared history, amend pushed commits, `--no-verify`, change repo settings, branch protection, secrets or workflow permissions, suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`), leave an empty exception handler, or hand-edit a generated or vendored file.
- **README-First, README-Last:** read the nearest `README.md` first, update it (and any behaviour doc) in the same PR. Every source file opens with a short block comment saying what it is and why. Markdown is one paragraph per line.

## The platform and its boundary

Non-negotiable; ADRs 0001 and 0004 record where today's code still crosses it and which milestone ends that.

- **The platform (`content/`) owns** content, revisions, workflow, the graph, embeddings, the agent harness, the tool registry, MCP, users and sign-in and every API (its screens are React, in `web/` — ADR 0006), and, as Phase G lands, the site registry, distribution, media, scoring, conversations and books.
- A new capability is a platform app on the one registry, agent users, Suggestions and outbox, with its UI in `web/`; a second LLM client, ledger or registry is federation, not absorption.
- Side effects leaving the platform go through the transactional outbox and `schemas/events/`. Changing a schema means bumping its version and updating the contract tests on both sides.
- Frontends (`web/`'s studio and site renderer; the Jekyll sites until each switches) and clients (the extension) are headless: APIs, exported files and stored outputs, never a database.

## Agent safety rules in code

- Every tool declares `effect` (`read|propose|write|publish`) and `perms`, and runs as an agent Django user (`agent:<slug>`); no superuser service accounts.
- New agents start at policy `suggest`. One revision per accepted outcome; intermediate work stays in the run.
- Page content and user input are untrusted data; review agents get no publish tools.
- Tests never call live LLMs; use recorded fixtures or fakes.

## Extension rules the build enforces

Why each exists: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (decisions D1–D17) and [`src/README.md`](src/README.md).

- **`src/core/` and `src/mcp/` never import `vscode`** (eslint, and the MCP bundle marks nothing external — `Could not resolve "vscode"` from `npm run compile` *is* the gate). Take the editor as a parameter or an injected callback.
- **`src/webview/` never imports `vscode`, `commands/` or `views/`** (it speaks `postMessage` only) and never uses `innerHTML` — `el()` and `textContent`.
- **Zero shipped runtime dependencies, and libraries over hand-rolled code** (D3/D14, amended by ADR 0006 decision 9): `dependencies` stays empty; a build-time library is bundled only when named in that bundle's `esbuild.js` allow-list, which reads what this repository's own code (`src/`, `web/packages/`) imports — `dist/extension.js` the engines package, `eventsource` and `CORE_LIBRARIES` (`yaml`, `jsonc-parser`, `picomatch`, `date-fns`, `@date-fns/tz`); **`dist/mcp-server.js` `CORE_LIBRARIES` and nothing else** (never `vscode`, never the engines package); `dist/panel.js` the two date libraries; `dist/studio.js` the studio's libraries. `@anthropic-ai/claude-agent-sdk` is the one optional dynamic import. Python-parity JSON stays hand-rolled (no library writes `json.dumps` byte for byte); a new helper a maintained library already provides needs a reason in the pull request.
- **The engines seam is never re-exported:** only `src/core/fleet/engines.ts` imports `@bamr87/fleet-engines`, never through `src/core/index.ts` (names collide); convert in `src/core/fleet/adapters.ts` and keep our tristate (`null` = "the manifest did not say").
- **The webview is UI, never the gate:** a button posts an intent and a target, never a payload or an override; every gate re-runs host-side in the function the command palette calls.
- **The studio webviews are the studio's code, and the host is their gate** (PLAN G10): `dist/studio.js` is `web/packages/webview` over `@zer0/ui` — never write a workspace, a component or an API call into `src/`; add it to `@zer0/ui` and its registry (`WORKSPACES`) and the extension renders it. Every request goes through `sendToPlatform` in `src/core/studio/bridge.ts`, whose gates read the URL that is sent, never the text the webview posted: a path under `/api/v2/` exactly as the platform routes it (no `%`, no `.`, `..` or empty segment — `%70ublish` and `./publish/` are refused, not normalised past the modal), never the session endpoints, a modal before publish, unpublish or schedule (a page id is any one segment), JSON bodies only, and only the headers the platform reads (`Idempotency-Key`, `If-Match`). The platform URL is settings-layer only (`settingsPlatformUrl`, trusted workspaces) and https or http on this machine; the person's token lives in SecretStorage per platform origin, never posted, logged or put in an error. The page is `default-src 'none'`, scripts and styles by nonce, images from the extension, the platform, `data:` and `blob:` only (`src/core/studio/page.ts`). No request at activation (D11).
- **Platform mode is decided per file, never per window:** the Metadata view shows the studio's page editor only for a file the platform has a page for (`Studio.modeFor`: `?source=` with the folder's name first); any other file keeps file mode in the same window. `zer0Cms.dashboard` opens the studio; `zer0Cms.dashboard.files` always opens the file-mode dashboard, and every file-mode caller (fleet console, monitor, audit, harness, drafts, the file-mode panel) opens it through that command.
- **Import core through the barrel** (`../core`); declare cross-cutting types once, in `src/core/shared/types.ts`.
- **Goldens are generated** (`src/test/fixtures/golden/generate.py`, `{engines,lanes,platform}/generate.mjs`): regenerate and read the diff, never edit one to pass a test.
- **Six bundles** (`esbuild.js`): `extension`, `mcp-server` (no `vscode`, no engines — the layering gate), `panel`, `dashboard`, `agent` (file mode), and `studio` (`dist/studio.js` + `dist/studio.css`, the studio's workspaces from `web/packages/webview`; a missing `web/node_modules` is one clear build error); a missing codicon file is a deliberate build error.

## Extension invariants that are easy to break

- **Configuration is three layers** (settings → `zer0.json` → `package.json` defaults); `src/config.ts` reads `inspect()`, not `get()`, and caches nothing ([`docs/CONFIG.md`](docs/CONFIG.md) §1).
- **Front matter is edited by line surgery** (`updateFrontMatterKeys()`): untouched lines stay byte-identical, and dates stay strings end to end.
- **The ledger is keyed by canonical URL** and written byte-compatible with Python's `json.dump` (`sort_keys`, `ensure_ascii`, indent 2, trailing newline).
- **The fleet plan is data:** every GitHub call is a `FLEET_PLAN` entry, guarded both ways by `fleetSurfaceIsRepoScopedOnly` (whole-segment allow-list) and `fleetPlanHasNoMergeVerbs`. The console never merges, approves, closes, removes a review label or reads a secret.
- **The Fleet console** takes only `{repo, lane}` from the webview; `src/commands/fleet.ts` re-reads the manifest, re-runs `evaluateFleetGates()` and derives toggles from GitHub's value. `zer0Cms.fleet.dispatchAllow` is settings-only; network follows a user action, through the injected `fetch` (D11).
- **Unknown is not off:** `listVariables`, `listWorkflows`, `recentRuns` and `openPulls` return `null`, not `[]`, on 403/404, and an unread cell says so.
- **A generated lane is files, never an armed loop:** it creates no `*_ENABLED` variable, omits no kill switch, weakens no guardrail and targets no `factory--*.yml`; `bespoke` from `classifyExpressibility` is a refusal with reasons.
- **A command acts on the site it was given:** `Zer0Shell.store` is the *active* site; never resolve `workspaceFolders[0]`; one `WorkspaceStore` per folder.
- **The platform is a profile:** nothing platform-specific outside `src/core/platform/profiles/`; `src/test/fixtures/golden/platform/` pins Jekyll's answers.
- **`.cms/` absence is normal:** the page index supplies `health: -1`, `freshness: 'unknown'`; never invent a score.
- **MCP registration is two-phase:** `provideMcpServerDefinitions` returns an empty `env`; `resolveMcpServerDefinition` reads the publish flag from the **settings** layer (disabled → `null`). `ZER0_CMS_MCP_ALLOW_EXEC` (trusted only) and `ZER0_CMS_MCP_ALLOW_SCAFFOLD` gate `zer0_contract` and `zer0_lane_scaffold`; otherwise the server only reads and drafts, and never opens a socket ([`docs/CONFIG.md`](docs/CONFIG.md) §6).
- **`src/core/harness/` is one vocabulary** for the editor agent and CI: `resolveHarnessProfile` alone decides roles, skills and model ([`src/core/harness/README.md`](src/core/harness/README.md)).
- **Eleven context keys, each gating something:** grep `package.json` before adding one; a key is a rendering hint, so every spawn re-asks `workspaceTrusted()`.
- **Adding a command:** `contributes.commands` (+ `menus`), `register(shell, id, …)` in its `src/commands/*.ts`, `ALL_COMMAND_IDS`, and `ALL_COMMANDS` in `src/test/extension.test.ts` with its `57` bumped ([`src/README.md`](src/README.md#adding-a-command)). Anything that writes, publishes or approves re-reads disk and re-runs `evaluateGates()` in the palette's function.

## A site's files (`content/sites/`)

The rules the Rails fleet CMS kept, carried into the platform by PLAN G4 and explained in [`content/sites/README.md`](content/sites/README.md); what the Rails CMS did that the platform does not do yet is in [`docs/plan/rails-cms-spec.md`](docs/plan/rails-cms-spec.md).

- **A stale write is refused twice** (the indexed digest, and the caller's base digest when the job names one), re-checked right before the atomic rename; an unchanged write-back writes nothing.
- **The catalog is Jekyll 4.4's reader**, not a glob; its fixture lists (`content/tests/fixtures/jekyll-site*.expected.json`) came from Jekyll 4.4.1's own reader — never re-baseline them by hand.
- **Every disk path is confined** (`sites/writer.py`): plain relative paths, no symlink at any component, the realpath inside the site's root.

## The monorepo (`workspace.yml`, `bin/zer0`)

Fourteen imported repositories, each a **source being absorbed** into the platform and `web/` (ADR 0006): keep them working, don't extend them. Explained in [`docs/MONOREPO.md`](docs/MONOREPO.md) and [`tools/workspace/README.md`](tools/workspace/README.md).

- **`workspace.yml` is the registry**; run a project's commands with `bin/zer0 run <task> <project>`, never restate them elsewhere.
- **A new directory under `packages/`, `sites/` or `apps/`, or a new top-level project, gets its `workspace.yml` entry in the same change**, with a root workflow or `ci: none — <reason>`, or `bin/zer0 check` fails.
- **Only the root `.github/workflows/` runs**, path-filtered per project; nested workflow files are reference copies.
- **Nothing under `packages/`, `sites/` or `apps/` assumes it is the git root**; resolve paths from the file.
- **A file two projects need is `vendored:`** in `workspace.yml` with one source: edit the source, `bin/zer0 vendor --write`, read the diff.
- **A Jekyll site lists `AGENTS.md` and `CLAUDE.md` under `exclude:`**, or Jekyll publishes them.
- **This repository is the only home** (ADR 0002): change an imported project here, never in its original; originals publish until cutover C1–C7, so don't archive one `docs/MONOREPO.md` still lists. The theme is the exception ([ADR 0005](docs/adr/0005-theme-goes-home.md)): `jekyll-theme-zer0` is developed in `bamr87/zer0-mistakes`, never here; a site here consumes it as the gem or `remote_theme` it declares until it moves to the Jekyll-theme option (PLAN P2), and a theme change is a pull request there.

## Fleet context

One of ~40 repositories managed by the [bamr87/bamr87 hub](https://github.com/bamr87/bamr87) (registry `_data/projects.yml`, standards in `specs/`), as a submodule: commit and push here first; the hub bumps its pointer afterwards. Prefer the hub's `templates/` kits; don't edit the logic of the hub-seeded `ci.yml` (`standard-ci@v2`) and `markdown-oneline.yml`. Every workflow is in [`docs/CICD.md`](docs/CICD.md) (`web.yml` gates `web/`, including the generated client's drift against the OpenAPI document; `extension.yml` the extension, including a change to `web/packages/`, which `dist/studio.js` is built from); `claude.yml` (`@claude`) is the only one that calls a model, and the one lane in `fleet.manifest.yml`. Hub loops reach it by PR or label: the `fleet-pulse` doctor, the `issue-pipeline`, the fan-outs and `token-rotation`.

## Standard deviations

Five. The first three are dated 2026-09-09 and are all consequences of consuming the hub's engines package rather than copying it; the last two, dated 2026-10-22, are the same choice made for `web/` for the same reason — generated output that a floating version would churn.

- **The lockfile is committed**, against the hub's `lockfiles: never-commit` posture. `npm ci` needs it, and so does the reusable relock job; more importantly an exact-pinned engines version is only reproducible with one.
- **`@bamr87/fleet-engines` is exact-pinned**, against the hub's always-latest convention. A bump changes generated goldens, so it is a deliberate `chore(deps)` pull request whose diff a person reads, not an ambient upgrade.
- **`yaml` is bundled** — exact-pinned with the engines, because the engines read workflow files with it — and since PLAN G10 it is also what core reads front matter, site configs and manifests with, in the extension host and in the MCP server alike (one of `CORE_LIBRARIES`; ADR 0006 decision 9).

## Governance

Read [`docs/constitution.md`](docs/constitution.md) before changing anything: it is the highest-precedence rule set here and wins over this file when they disagree. It changes only through a numbered record in [`docs/amendments/`](docs/amendments/), ratified by the maintainer merging the PR; agents propose, never merge. Every user-facing feature has a stable id in [`features/features.yml`](features/features.yml) with `status`, location and the PRD requirement ids it serves; the PRD's "Feature catalog" block is generated from it (`python3 <bamr87/bamr87>/tools/governance_lint.py prd-sync . --write`; check with `… check .`). Never hand-edit that block or `CHANGELOG.md`.
- **`web/package-lock.json` is committed**, against the hub's `lockfiles: never-commit` posture. `npm ci` in `web.yml` and in the platform image's Node stage needs it, and the studio's build and tests then run on the versions they were checked against.
- **`openapi-typescript` is exact-pinned** in `web/packages/api`, against the always-latest convention. Its output is committed (`src/schema.d.ts`) and drift-checked against `schemas/openapi/openapi.json`, so a new generator version would fail the check with no change to the API; a bump is a deliberate `chore(deps)` change that regenerates the file in the same commit. Every other `web/` dependency takes caret ranges and moves when the lockfile is refreshed.
- **Lockfile committed** (2026-09-09), against `lockfiles: never-commit`: `npm ci` and the relock job need it, and the exact-pinned engines are only reproducible with one.
- **`@bamr87/fleet-engines` exact-pinned** (2026-09-09), against always-latest: a bump changes goldens, so it is a deliberate `chore(deps)` PR.
- **`yaml` bundled** (2026-09-09): exact-pinned with the engines, which read workflow files with it; since PLAN G10 core reads front matter, site configs and manifests with it too, in the extension host and the MCP server alike (one of `CORE_LIBRARIES`).
- **`web/package-lock.json` committed** (2026-10-22), against `lockfiles: never-commit`: `npm ci` in `web.yml` and the platform image's Node stage need it.
- **`openapi-typescript` exact-pinned** (2026-10-22) in `web/packages/api`, against always-latest: its committed output is drift-checked against `schemas/openapi/openapi.json`, so a new generator version would fail the check with no API change; a bump regenerates the file in the same commit.
- **UPS-DOC-08:** the prose is over the 2,000-word budget: during the overhaul AGENTS.md carries ADR 0006's target and its must-not list on top of the rules today's build still enforces; their commands blocks come on top.
