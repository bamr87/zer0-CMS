# AGENTS.md — working rules for AI coding agents in zer0-CMS

This is the canonical agent file for the whole repository. It applies to every coding agent (Claude Code, Copilot, Cursor, Codex). Every `CLAUDE.md` in the tree is a pointer that imports the `AGENTS.md` beside it; edit the `AGENTS.md`, never the pointer. Each project under `packages/`, `sites/` and `apps/` has its own `AGENTS.md`, which governs work inside that tree — read it before touching the tree.

## What this repo is — the target (ADR 0006, read this first)

**zer0-CMS is becoming a comprehensive application for content work — writing articles, creating content, brainstorming ideas, gathering information, operating a news site and writing books — with AI integrations and pipelines and workflows throughout, and every AI result something a person reviews.** Everything below serves that. It is being rebuilt — rewritten where a port would not scale — into **one Python platform with a React frontend**: a complete, modern CMS on established libraries, with an AI content layer that helps create and develop content, that manages, monitors and improves the sites it serves (AIEO included), and into which every repository that was merged here is **absorbed with its content, features and capabilities intact**. The decision is [ADR 0006](docs/adr/0006-one-python-platform.md); the target is described in [`docs/plan/TARGET.md`](docs/plan/TARGET.md); the order of work is [`docs/plan/PLAN.md`](docs/plan/PLAN.md) § 3; every capability — what the platform must do, on which surfaces, and what each merged repository brings — is the ledger [`docs/plan/capabilities.yml`](docs/plan/capabilities.yml).

- **Backend:** `content/`, Django + Wagtail **used as a headless library** (page tree, revisions, workflow, StreamField, images). It is the system of record, the agent runtime and the only server. Its agent-native rules ([ADR 0001](docs/adr/0001-target-architecture.md), [ADR 0004](docs/adr/0004-one-platform.md)) carry over unchanged.
- **Frontend:** `web/`, one React + TypeScript + Vite codebase with two halves: the **studio**, where people *manage*, *review* and *create* content and operate everything the absorbed apps did; and the **site renderer**, which turns each site's content into its static public site. It reaches the platform only through its APIs.
- **Client:** `src/`, the VS Code extension, is **built from the studio's code** — same TypeScript, React, libraries and generated client; its webviews render the studio's workspaces from `web/packages/`, and its own code is a thin VS Code host plus file mode. A studio capability without its extension counterpart is a gap the ledger reports.
- **AI content layer:** provider adapters behind one registry, assistants, pipelines, output schemas, briefs and conversations — barodybroject's model rebuilt onto the platform's agent runtime, every generation an async, costed, reviewable run (TARGET.md § The AI content layer).
- **Workspaces:** the studio is organised around what people do — Write, Create, Ideas, Research, Newsroom, Books, Sites — on one runtime of AI pipelines, editorial workflows and automations (TARGET.md § What it is for).
- **Content in the database, files generated:** every site and book lives in the platform and also exists as a generated, committed, re-importable file tree (a site's source, a book's `library/<slug>/`).
- **Sites:** manage (registry, settings, render, deploy), monitor (uptime, links, performance, accessibility, SEO, analytics, AIEO scores) and improve (agents propose changes from those signals; a person accepts them). Sites render with React by default; zer0-mistakes survives only as an option — render a site with that theme and deploy it with a Jekyll server.
- **No Ruby.** The workspace tool (`bin/zer0`) is Python already (PLAN P5); the Rails fleet CMS, the image generator's gem and the sites' Jekyll builds are being ported away, and until they are, a ratchet in CI stops Ruby from growing or spreading.
- **Every merged repository is absorbed, not discarded:** parodynews (formerly barodybroject — every one of its capabilities), aieo, books, the image generator, the Rails CMS, the workspace tool and the nine sites' content. A source directory is deleted only when the ledger shows every capability `done` (with a test) or `dropped` by the owner.

**What an agent must not do** — each of these has happened, or is the next obvious mistake:

- Add Ruby anywhere, or build a feature on Rails, Jekyll or the image-generator gem that a later milestone would have to port. `tools/check_absorption.py` fails CI on new Ruby.
- Add screens to the Wagtail admin. New UI is React in `web/`, with its extension counterpart or a recorded gap.
- Call a model provider's SDK outside the adapter registry, or add a second LLM client, ledger or registry.
- Port a merged app's models and views one to one. Map its capabilities onto the platform's model (TARGET.md § Rules that keep models and views manageable) and import its data.
- Hand-roll what an established library already does (an editor, a diff, auth, a job queue, a schema validator, a query cache, a YAML or glob parser) without a reason in the pull request. **Less code is better**: configure a library, reuse a shared package, delete what the platform or a library now covers.
- Build an extension UI separately from the studio's. Extension webviews render `web/packages/` workspaces; the extension's own code is the VS Code host.
- Build a capability that only an API can reach. A capability is done when a person can use it from its studio workspace (and, where it belongs next to a file, from the extension).
- Add a dependency on zer0-mistakes — a vendored file, a fixture checkout, a CI job against it, a design port, an overlay. Only the Jekyll-theme option names it (`theme_allowed:` in the ledger); its home is `bamr87/zer0-mistakes` ([ADR 0005](docs/adr/0005-theme-goes-home.md)).
- Hand-edit a generated file tree (a site's exported source, a book's `library/<slug>/`) as if it were the source. Edit in the platform; the files are regenerated.
- Delete a source directory, a site or a capability because it looks obsolete, or mark a capability `dropped`. Deletion follows the ledger, and dropping is the owner's decision.
- Run a fleet-wide kit (docs framework, governance, standards) over an imported project as if it were a live product. Imported projects under `apps/`, `packages/`, `rails/` and `sites/` are **sources being absorbed**; fleet kits apply to the platform, `web/` and the extension.
- Pick work by "the first unchecked box" in the plan. The order of work is PLAN § 3's list; older phases keep boxes later decisions overtook.
- Stack a pull request on another unmerged branch. Base every pull request on `main` (#52 merged into a dead branch and left `main` contradicting the owner for a day).

**Today's code vs. the target.** Until a milestone lands, the code as it is wins over the plan: the rules below that describe today's Rails app and Jekyll sites are enforced by today's build and still hold — keep them working, but do not extend them. When a rule below and ADR 0006 seem to disagree about *new* work, ADR 0006 wins.

## Layout

Today the repository holds three products of its own and the imported sources still being absorbed (`web/` arrives in PLAN P4):

- `content/` is the **platform** — the Django 5.2 + Wagtail project: page models, revisions, the agent harness and its tool registry, suggestions, the content graph, the outbox, the GraphQL/REST APIs, the MCP server, and the operational baseline (`content/ops/`: probes, request ids, the error envelope, JSON logging, throttling, OpenAPI).
- `src/` is the **VS Code extension** — a lightweight, zero-runtime-dependency CMS that *edits* content in the editor: a metadata panel, dashboard, SEO insights, and a governed publishing path (draft → brand guard → human approval → publish → ledger). It becomes a client of the platform with the studio's capabilities (ADR 0006 decision 9, PLAN G10) and keeps its file mode.
- `rails/` is the **fleet CMS** — a Rails 8.1 app on Administrate 1.0 that indexes every registered Jekyll site into SQLite and writes edits back to the files (git stays the source of truth), draws a missing preview through zer0-image-generator, and hosts the ABC book wizard; `rails/lib` is a stdlib-only library (the Jekyll-exact catalog, front-matter surgery, the confined writer, `zer0 doctor`, the ABC generator). Being absorbed by the platform (PLAN G4, G5, G9) and then deleted — no Ruby remains (ADR 0006); its invariants below hold until each gate is green.

"Done" for a `rails/lib` change means `rails/bin/test-stdlib` passes with no bundler. "Done" for the Rails app means `bin/rails test` and `bin/rails zeitwerk:check` pass, and — when `rails/Dockerfile` or `docker-compose.yml` changed — the image still builds, boots and answers `/up`. "Done" for `content/` is [`content/AGENTS.md`](content/AGENTS.md)'s definition: `pytest -q`, `makemigrations --check`, ruff, the recorded evals, and the three committed schemas (GraphQL, the agent schema, OpenAPI) unchanged. Do not call Rails "the content engine" — that name belongs to `.cms/` in `src/core/contract/`. Platform contract: `docs/PLATFORM.md`. Stack contract: `docs/ZER0-STACK.md`. CI map: `docs/CICD.md`.

## Workflow

**During the overhaul, work lands directly on `main`** (the owner's direction of 2026-10-21: "these are breaking changes and a complete overhaul. no need for PRs until there's a working system"). Until the owner says the system works: no pull requests and no long-lived branches; commit each milestone to `main` as its own series of Conventional Commits, run its tests (rule 2) before every push, and put the commands and results in the commit message body instead of a PR description. Parallel work happens in short-lived worktrees that are merged into `main` and deleted the same day. History is still never rewritten (rule 4).

1. **One milestone at a time.** Pick the first milestone in `docs/plan/PLAN.md` § 3 **Order of work** that is not done and whose predecessors have landed — not the first unchecked box in the file. Work on `main` (or in a worktree merged back into `main` the same day). Don't mix milestones in one commit; spin unrelated fixes into their own commits.
2. **Run the tests.** Before every push to `main`, run that milestone's test commands from `docs/plan/PLAN.md` plus `bin/zer0 check` and `python3 tools/check_absorption.py`, and run `bin/zer0 run test` for every affected project. Put the commands and results in the commit message body. Never mark a box done with red or skipped tests.
3. **Keep PLAN checkboxes and the ledger updated** in the same commits: tick the tasks you finished, add sub-tasks you discovered, add a note under the milestone if you deviated and why, and set the status (and proof) of every `capabilities.yml` row the PR moved.
4. **Git hygiene.** No force-push, no history rewrites on shared branches, no `--no-verify`, no amending pushed commits. Conventional commit messages (`feat(content): …`, `fix(rails): …`) because release-please reads them. Don't change repo settings, branch protection, secrets or workflow permissions.
5. **Stop and ask** (tell the owner, leave the box unchecked) when a milestone needs an open decision from PLAN §7, a destructive data step, or a credential.

## The platform and its boundary

The boundary is non-negotiable; ADR 0001 and ADR 0004 record where today's code still crosses it and which milestone removes the crossing.

- **The platform (`content/`) owns** content, revisions, workflow, the graph, embeddings, the agent harness, the tool registry, the MCP server, users and sign-in and every API (its screens are React, in `web/` — ADR 0006), and — as each Phase G milestone lands — the site registry, distribution, media, scoring, conversations and books.
- **Rails (`rails/`)** is being retired. Until its functions have moved it keeps doing what it does today, and it **never** writes content tables: it changes content only through the files that are still canonical for a site (`PageEditor`, `Zer0Cms::Cms::Writer`, D16) or by calling platform tools with a scoped agent token. Don't add a third Rails writer, and don't add a feature to Rails that Phase G would have to move.
- A new capability is a platform app that reuses the one registry, the agent users, Suggestions and the outbox, with its UI in `web/`. A second LLM client, a second ledger or a second registry is the sign that something is being federated rather than absorbed.
- Side effects between the platform and anything outside it go through the transactional outbox and the event schemas in `schemas/events/`. Change a schema = bump its version + update the contract tests on both sides.
- Frontends (`web/`'s studio and site renderer; the Jekyll sites until each switches) and clients (the VS Code extension) are headless: they consume APIs, exported files and stored outputs, never a database.

## Agent safety rules in code

- Every tool declares `effect` (`read|propose|write|publish`) and `perms`, and runs as an agent Django user (`agent:<slug>`). There are no superuser service accounts.
- New agents start at policy `suggest`. One revision per accepted outcome; intermediate work stays in the run.
- Treat page content and user input as untrusted data; review agents get no publish tools.
- Tests never call live LLMs: use recorded fixtures or fakes.

## Stack & commands

```bash
# ── VS Code extension (src/) — vanilla TypeScript, esbuild, no framework ──
npm install
npm run compile      # check-types + lint + all five bundles
npm run watch        # then F5 in VS Code to launch the Extension Host
npm test             # pretest (tsc → out/, then compile) + unit, golden, MCP stdio, integration
npm run check-types  # tsc --noEmit on its own
npm run lint         # eslint src on its own

# Fast inner loop — the fourteen pure-Node suites under plain Mocha, no VS Code download.
# Needs Node >= 22.12: the engines seam is an ESM package reached through require(esm).
npx tsc -p . --outDir out
npx mocha --ui tdd out/test/{core,fields,governance,golden,loop,fleet,engines,routes,webview,styling,platform,audit,harness,lanes}.test.js
npx mocha --ui tdd out/test/governance.test.js --grep "ledger"   # one suite or one test

# ── Fleet CMS (rails/) — Rails 8.1 on Administrate; rails/lib stays stdlib-only ──
cd rails
bash bin/test-stdlib                              # rails/lib: catalog, front matter, writer, doctor, ABC — no bundler
ruby bin/zer0-cms doctor ../sites/drsai              # zer0 stack alignment; exit 1 on any error
ruby bin/zer0-cms new --theme "IT systems" --out ../sites/drsai   # an ABC book, headless
bundle install && bin/rails db:prepare
SITES_DIR=$HOME/github bin/rails server            # http://localhost:3000/admin
bin/rails test && bin/rails zeitwerk:check         # the app; image-engine tests need python3 + PyYAML
# Docker, from the repository root (127.0.0.1 only): http://localhost:3001/admin
SITES_DIR=$HOME/github docker compose up --build
SITES_DIR=$HOME/github docker compose --profile imagegen up --build   # + zer0-image-generator on :3000

python3 tools/unwrap-prose.py --write --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$'   # fix the markdown one-paragraph-per-line CI gate (its two excludes)

# ── The platform (content/) — Django 5.2 + Wagtail 7.4; see content/AGENTS.md ──
cd content
pip install -r requirements-dev.txt
python manage.py migrate && python manage.py sync_agents --publish   # agent users, definitions, evals → live
python -m pytest -q -m "not slow"                  # the fast tier; drop -m for the big-site round trips
DATABASE_URL=postgres://… python -m pytest -q      # the same suite on Postgres + pgvector
python manage.py makemigrations --check --dry-run && ruff check . && ruff format --check .
python manage.py run_evals --all --recorded        # every agent's eval suite, no network
python manage.py spectacular --format openapi-json --urlconf ops.openapi --fail-on-warn --file ../schemas/openapi/openapi.json   # the committed OpenAPI document
python manage.py import_jekyll --site drsai --path ../sites/drsai   # a site → pages (idempotent)
python manage.py roundtrip_jekyll --path ../sites/drsai             # import → export → byte-compare
# Docker, from the repository root: http://localhost:8000 (/admin/, /graphql/, /api/v2/, /mcp/, /healthz, /readyz, /version)
docker compose --profile content up -d --wait db redis content worker beat relay

# ── The workspace (every project in the repository) — Python 3.9+ and PyYAML, nothing else ──
python3 -m pip install pyyaml     # the tool's one dependency
bin/zer0 list                     # projects, paths, what each publishes and what gates it
bin/zer0 run check --affected     # the fast tier of everything this branch touched (+ dependents)
bin/zer0 check                    # registry, paths, workflows and vendored copies all agree
bin/zer0 doctor                   # zer0 doctor over every in-repo site (runs rails/bin/zer0-cms: needs Ruby until G4)
bin/zer0 tags                     # this repo's release tags vs. those inherited from the Front Matter fork
python3 -m unittest discover tools/workspace   # the tool's tests, with the golden replay of its Ruby predecessor
```

`extension.test.ts` and `multiroot.test.ts` need a real extension host (`multiroot` has its own entry in `.vscode-test.mjs`: `npx vscode-test --label multiroot`), and `mcp.test.ts` needs `dist/mcp-server.js`, so the fourteen-suite command above leaves all three out; `out/test/mcp.test.js` does run under plain Mocha once `npm run compile` has built the bundle. On headless Linux `npm test` shells out to `xvfb-run` itself (`test-runner.js`); `ZER0_CMS_NO_XVFB=1` forces the plain path.

## Extension architecture — the rules the build enforces

- **`src/core/` and `src/mcp/` must not import `vscode`.** They are pure Node. eslint blocks it, and the MCP bundle (which marks nothing external) turns a stray import into a build error. If core needs the editor, take it as a parameter or an injected callback. `npm run compile` failing with `Could not resolve "vscode"` *is* this gate firing.
- **`src/webview/` must not import `vscode`, `commands/` or `views/`** — it runs in a browser context and talks to the host over `postMessage` only.
- **Zero *shipped* runtime dependencies** (decision D3, amended by D14 — see `docs/ARCHITECTURE.md`). `dependencies` is empty and stays empty. A build-time library may be bundled by esbuild from `devDependencies`, but only when it is named in that target's allow-list in `esbuild.js`: today that is `@bamr87/fleet-engines` and its `yaml`, admitted to `dist/extension.js` alone (they enter the bundle when a host surface consumes the seam). **The MCP bundle allows no bare import at all** — the gate that has always guarded `vscode` now guards every package, so `dist/mcp-server.js` stays standalone. `@anthropic-ai/claude-agent-sdk` remains the one optional, dynamically-imported exception. YAML-subset parsing, globbing, date formatting, JSONC and Python-parity JSON output stay hand-rolled in `src/core/shared/`. *ADR 0006 decision 9 amends this: the extension moves onto the studio's libraries, bundled through this same allow-list, and G10 replaces the hand-rolled helpers — until G10 lands, keep the build gates green and do not add new hand-rolled helpers.*
- **The engines seam is never re-exported.** `src/core/fleet/engines.ts` is the only file that imports `@bamr87/fleet-engines`, and `src/core/index.ts` never re-exports it — the package's `FleetLane`/`FleetManifest`/`parseFleetManifest` collide with names this repo already declares, and `export *` breaks on a duplicate. Convert at the boundary through `src/core/fleet/adapters.ts` instead, and keep this repo's tristate (`null` = "the manifest did not say") rather than adopting the package's defaults.
- **No `innerHTML` in `src/webview/`.** Build DOM with `el()`, assign text with `textContent`.
- **The webview is UI, never the gate.** Buttons post an intent and a target — never a payload or an override. Every gate is re-checked host-side in the same function the command palette calls. A disabled button is a courtesy to the person, not a control.
- Golden fixtures under `src/test/fixtures/golden/` are generated, never hand-edited: `generate.py` (the Python publishing lane) writes the ledger and the worklist pair, and `engines/`, `lanes/` and `platform/` each have their own `generate.mjs`. Regenerate one and read the diff; never edit one to make a test pass.
- Import core through the barrel (`../core`), not from individual files. Cross-cutting types are declared once in `src/core/shared/types.ts` — redeclaring a name makes `export *` ambiguous and breaks the barrel for everyone.

### The five bundles (`esbuild.js`)

`dist/extension.js` (node; `vscode` + agent SDK external) · `dist/mcp-server.js` (node; **nothing** external — the layering gate) · `dist/panel.js` · `dist/dashboard.js` · `dist/agent.js` (browser, iife). `media/*.css` and the codicon font are copied into `dist/media/` at build time; a missing codicon file is a deliberate build error, because without it every icon renders empty and the build still looks green.

### Invariants that are easy to break

- **Configuration is three layers** (VS Code settings → `zer0.json` → `package.json` defaults), and `src/config.ts` reads settings through `inspect()` rather than `get()` on purpose: every setting has a default, so `get()` always returns a value and `zer0.json` could never win. Keep only what a human actually set. Nothing is cached — `currentConfig()` re-reads on every call, which is why flipping `publishAllow` takes effect without a window reload.
- **Front matter is edited by line surgery.** `updateFrontMatterKeys()` rewrites only the lines belonging to changed keys, so untouched lines come out byte-identical and comments and hand-formatting survive. Dates stay strings end to end — round-tripping through a JS `Date` is how a CMS silently shifts published timestamps by a timezone.
- **The ledger is keyed by canonical URL** and written byte-compatible with Python's `json.dump` (`sort_keys`, `ensure_ascii`, indent 2, trailing newline). That is what lets this extension and the CI lane share one queue without double-publishing, and what keeps the file from churning in git.
- **The fleet plan is data, and two guards keep it a boundary.** Every GitHub call the console can make is a declared entry with a sentence naming *the repository's own* thing it returns. `fleetSurfaceIsRepoScopedOnly` admits only an allow-list of sub-roots, whole-segment — never a prefix match, which would let the next endpoint anyone adds through. `fleetPlanHasNoMergeVerbs` refuses `/merge`, `/reviews`, `/update-branch`, `/actions/secrets`, `/collaborators`, any `DELETE` and any write to `/labels`. Both are asserted from both directions. This console never merges, approves, closes, removes a review label or reads a secret; those are the boundary, not a backlog.
- **A cell nobody has read says so.** `unknown` must look different from `off`, and nothing renders `0` where the truth is "nobody measured" — `listVariables`, `listWorkflows`, `recentRuns` and `openPulls` returning `null` rather than `[]` on 403/404 is that rule in the type system.
- **A generated lane is files, never an armed loop.** Scaffolding writes a workflow, an agent, a skill stub and a manifest entry for a person to review and commit — and deliberately does **not** create the lane's `*_ENABLED` repository variable, because writing a file somebody reads and arming a loop to run are different powers. Nothing generated may omit its kill switch, weaken a guardrail, or target a `factory--*.yml` (GitFactory compiles those; this console does not own them). A lane the generator cannot express honestly is refused with reasons — `classifyExpressibility` returning `bespoke` is a feature, not a gap.
- **A window holds many sites, and a command acts on the one it was given.** `Zer0Shell.store` is the *active* site's store; a command invoked on a file resolves that file's folder and reads its configuration instead. `workspaceFolders[0]` is never the answer — `src/config.ts` resolves the active folder through a resolver the registry installs. One `WorkspaceStore` per folder; never a second store on a folder that already has one, or its watchers, scans and cache writes all double.
- **The platform is a profile, and Jekyll's answers are pinned.** Nothing platform-specific may be hard-coded outside `src/core/platform/profiles/`. `src/test/fixtures/golden/platform/` records what the pre-profile code computed for the fixture pages; regenerate it with its own `generate.mjs` and read the diff — a byte change there is a behaviour change and needs a reason, not a re-baseline.
- **`.cms/` absence is a normal state, not an error.** With no contract, the page index supplies the same `ContentRecord` shape with `health: -1` and `freshness: 'unknown'`. Report less; never invent a health score.
- **MCP registration is two-phase.** `provideMcpServerDefinitions` may be cached, so it returns an empty `env`; `resolveMcpServerDefinition` runs at server start and is the only place the publish flag or a secret is read — and it reads the **settings** layer, not the merged config, because a cloned repo's `zer0.json` must not be able to arm an agent to publish. When publishing is off the env var is set to `null` (remove it), not `"0"` and not merely omitted.
- **The MCP server learns Workspace Trust from its environment.** It is a separate process, so the editor carries trust across as `ZER0_CMS_MCP_ALLOW_EXEC` — `'1'` only in a trusted workspace, `null` (removed) otherwise — and `zer0_contract`, which spawns the repository's own engine, refuses without it. `ZER0_CMS_MCP_ALLOW_SCAFFOLD` is the same shape for `zer0_lane_scaffold` (settings-layer `fleet.scaffoldAllow`, `fleet.enabled`, trust). A hand-started server therefore reads and drafts but neither publishes, spawns nor scaffolds.
- **`src/core/harness/` is one vocabulary for the editor agent and CI.** `resolveHarnessProfile` is the only place a run's roles, skills and model are decided — settings, then `zer0.json`, then the site's `_data/ai.yml`, then the built-in default — and `toSdkOptions` / `toRunnerInvocation` / `toAiLaneWith` project that one value to the editor or to CI. Lane generation (`lanes.ts`, `render.ts`, `preflight.ts`, `selfAudit.ts`, `manifestWrite.ts`) lives beside it; see `src/core/harness/README.md`.
- **Context keys: eleven, and every one gates something.** Grep `package.json` for a key before adding one; `uiState.ts` mirrors each in memory and only calls `setContext` on a change. `zer0Cms:workspace:trusted` is the exception that proves the rule — it gates `when` clauses, but no gate *relies* on it: every function that spawns re-asks `workspaceTrusted()`, because a context key is a rendering hint and a trust decision is not.
- **The Fleet console: the webview sends `{repo, lane}` and nothing else; the host re-reads the manifest and derives the value.** `doToggleSwitch`/`doDispatchLane` and the three run verbs (`doRerunLastFailure`, `doCancelNewest`, `doToggleWorkflowFile`) in `src/commands/fleet.ts` re-read `fleet.manifest.yml` from disk, re-run `evaluateFleetGates()` and derive a toggle's new value from the variable as GitHub reports it, never from a message. The master gate `zer0Cms.fleet.dispatchAllow` is read from the settings layer only (`settingsFleetDispatchAllow()`); `zer0.json` cannot arm it. Network happens only from an explicit user action, through the `fetch` injected into `core/fleet/github.ts`, never at activation (decision D11) — and every call is in `FLEET_PLAN` or the client refuses it. The MCP server's `zer0_fleet_status` reads the local manifest and nothing else.

### Adding a command

Declare it in `package.json` under `contributes.commands` (with any `when` clause in `contributes.menus`), `register(shell, id, …)` it in the `src/commands/*.ts` file that owns its subject, add the id to `ALL_COMMAND_IDS` in `src/commands/index.ts`, and add it to `ALL_COMMANDS` in `src/test/extension.test.ts` — bumping that list's `54` assertion, because the test compares its own copy against the registered commands and, in order, against the manifest. An id inside an existing module needs no `extension.ts` change; a new command *module* also needs its `register*Commands(shell)` call in `activate()` (ten today). Any action that writes, publishes or approves must route through a function the command palette also calls, and that function must re-read state from disk and re-run `evaluateGates()` before acting.

## Fleet CMS architecture (`rails/`) — the invariants

- **Git is the source of truth; SQLite is an index** (decision D16). `Site#sync!` rebuilds `Site`/`Page`/`Asset`/`Term` rows from disk in one transaction. Never write content through ActiveRecord: `PageEditor` and `Zer0Cms::Cms::Writer` are the only writers, and every write re-syncs the path. A page row is never saved from a form — the editor's values are virtual attributes read from the file.
- **A stale write is refused, twice.** The on-disk digest must equal the indexed digest, and the form's `base_digest` must equal it too. The write re-checks the bytes right before an atomic rename. An unchanged save writes nothing — `page_editing_test.rb` proves it for every indexed fixture file.
- **`rails/lib` is stdlib-only** (decision D15). CI runs its tests with no `bundle install` on Ruby 3.3 and 4.0.5; a gem reached from `lib/` is exactly the regression `abc-engine.yml` catches. Rails-only code stays in `app/`.
- **The catalog is Jekyll's reader, not a glob.** It transcribes Jekyll 4.4's reader rules, and `test/fixtures/jekyll-site`'s expected lists were generated by Jekyll 4.4.1 (`bin/jekyll-parity`). Never re-baseline them by hand; a non-markdown page with front matter (`search.json`) is deliberately not indexed.
- **Every disk path is confined.** Sites are stored as realpaths strictly inside `SITES_DIR`; every read and write goes through `SitePath` (no `..`, `lstat` on every component so symlinks are refused, a realpath check); `source:` and `collections_dir:` that escape the root are refused.
- **`ImageEngine` is the only file that loads or runs zer0-image-generator.** The engine writes the preview key itself, so its write is replaced through `PageEditor#replace_engine_write!`; its subprocess gets no credentials. The locked 0.6.0 gem is Python; the facade backend activates by itself once a release ships `Zer0ImageGenerator::Facade`.
- **Access is loopback or a password.** `AccessGuard` reads `REMOTE_ADDR` and every `X-Forwarded-For` hop, never `remote_ip`. Compose publishes on 127.0.0.1 and trusts the Docker gateway only because of that binding; never publish the port elsewhere without `ZER0_CMS_PASSWORD`.
- **No inline script or style.** The CSP has a per-request nonce and no `unsafe-inline`. Administrate's compiled JS/CSS is deliberately not loaded (it would start a second Turbo); flashes are escaped because they carry repository text.
- **Vendored files are byte-identical copies, never edited here:** `app/assets/stylesheets/zer0-tokens.css` (kit `zer0-ui-tokens`, from zer0-image-generator), `lib/zer0_cms/data/abc_art_styles.yml` (zer0-image-generator), `lib/zer0_cms/data/frontmatter_schema.yml` (zer0-mistakes). They are declared under `vendored:` in the root `workspace.yml`: re-sync with `bin/zer0 vendor --write` and read the diff; `bin/zer0 check` (and CI) fails while any copy differs from its source.
- The ABC wizard exports only into an explicit Jekyll root; bundled themes generate offline, anything else falls back to Claude. Never hand-edit a generated book in drsai; re-run the wizard.

## The monorepo (`packages/`, `sites/`, `apps/`) — `workspace.yml` and `bin/zer0`

Fourteen repositories live here, each imported with full history and each a **source being absorbed** into the platform and `web/` (ADR 0006; its capabilities are rows in `docs/plan/capabilities.yml`): the image generator (`packages/zer0-image-generator/`), the books app (`packages/books/`), nine sites (`sites/drsai/`, `sites/zer0-pages/`, `sites/zer0-pages-remote/`, `sites/zer0-demo-cookbook/`, `sites/zer0-demo-garden/`, `sites/1987/`, `sites/2005/`, `sites/irony-works/`, `sites/wargames/`) and two apps (`apps/parodynews/`, `apps/aieo/`), next to this repository's own extension, Rails app and content plane. `docs/MONOREPO.md` explains the design; `tools/workspace/README.md` documents the tool.

- **`workspace.yml` is the registry, and `bin/zer0` reads it.** Every project is an entry: its path, kind, dependencies, what it publishes, the root workflow that gates it, its zer0 site root, and its `setup`/`check`/`test`/`build` commands. Run a project's commands with `bin/zer0 run <task> <project>`, or from inside its directory; never restate them in a second place. `bin/zer0 run check --affected` is the fast loop for a branch.
- **A new directory under `packages/`, `sites/` or `apps/` — or a new top-level project such as `content/` — is a new entry in `workspace.yml` in the same change**, with a root workflow (or `ci: none — <reason>`). `bin/zer0 check` fails otherwise, and so does `zer0-workspace.yml` on every pull request.
- **Each project keeps its own `AGENTS.md`** (with a `CLAUDE.md` pointer beside it), which governs work inside it. Only the root `.github/workflows/` runs. A project's root workflow is path-filtered to its own tree and runs inside it. Nested `.github/workflows/` files that remain are reference copies of what is not ported yet.
- **Nothing under `packages/`, `sites/` or `apps/` may assume it is the git root.** `git rev-parse --show-toplevel` is zer0-CMS; resolve paths from the file instead.
- **A file that must exist in two projects is `vendored:` in `workspace.yml`**, with its one source. Edit the source, then run `bin/zer0 vendor --write` and read the diff. `bin/zer0 check` fails while a copy differs.
- **A Jekyll site excludes its agent files.** A site's `_config.yml` lists `AGENTS.md` and `CLAUDE.md` under `exclude:`, or Jekyll publishes them.
- **This repository is the only home** ([ADR 0002](docs/adr/0002-one-home-cutover.md)): make every change to an imported project here, never in its original. The originals still publish the gems, the Pages sites, the Azure deploy and the `remote_theme` until cutover milestones C1–C7 move each one, so do not archive one while `docs/MONOREPO.md` § What still depends on the original repositories still lists it. The theme is the exception ([ADR 0005](docs/adr/0005-theme-goes-home.md)): `jekyll-theme-zer0` is developed in `bamr87/zer0-mistakes`, with its Rails studio, never here; a site in this repository consumes it as the gem or `remote_theme` it declares until it moves to the Jekyll-theme option (PLAN P2) — after which only that option names the theme — and a theme change is a pull request there.

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`/`style`).
- Default branch is `main`. During the overhaul commits go straight to it (see § Workflow); once the owner declares a working system, changes return to branches and pull requests.
- README-First, README-Last: read the nearest `README.md` before changing a directory, and update it after. The dense ones are `src/README.md`, `src/core/README.md`, `src/test/README.md` and `docs/ARCHITECTURE.md`.
- One paragraph per line in markdown — CI enforces it (`tools/unwrap-prose.py`, skipping `SCHEMA.md` and `CHANGELOG.md`; pass the same two `--exclude` patterns locally, as the command above does).
- Every source file opens with a short block comment (or module docstring) saying what it is and why it exists.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or leave empty exception handlers — eslint errors on all four.
- CI goes through the hub's `standard-ci@v2` (root `ci.yml`) plus one path-filtered root workflow per project; releases go through release-please in manifest mode. Don't add nested release-please configs. Docs that change behaviour are updated in the same PR.

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents. `.github/workflows/ci.yml` and `markdown-oneline.yml` are thin hub-seeded callers — don't edit their logic. `extension.yml` is this repo's own and gates the extension alone; the Rails half has two of its own, both filtered to `rails/**` — `abc-engine.yml` (`rails/lib` with no bundler, Ruby 3.3 and 4.0.5) and `rails-app.yml` (the app with its bundle, Zeitwerk, and a production boot) — so an extension pull request no longer runs Ruby and a Rails change no longer downloads VS Code. `content.yml` gates the content plane alone (pytest on SQLite and on Postgres, migrations, schema drift). `zer0-doctor.yml` is the reusable consumer-contract check content repositories call. `release.yml` calls the hub's release-please workflow and then a repo-owned marketplace job — see `docs/RELEASING.md`. `claude.yml` is the `@claude` mention lane (`anthropics/claude-code-action@v1`), the only workflow that calls a model and the one lane `fleet.manifest.yml` declares; `codeql-analysis.yml` is GitHub CodeQL (`github/codeql-action@v4`).

## Standard deviations

Three, all dated 2026-09-09 and all consequences of consuming the hub's engines package rather than copying it.

- **The lockfile is committed**, against the hub's `lockfiles: never-commit` posture. `npm ci` needs it, and so does the reusable relock job; more importantly an exact-pinned engines version is only reproducible with one.
- **`@bamr87/fleet-engines` is exact-pinned**, against the hub's always-latest convention. A bump changes generated goldens, so it is a deliberate `chore(deps)` pull request whose diff a person reads, not an ambient upgrade.
- **`yaml` is bundled.** The hand-rolled YAML subset in `src/core/shared/config.ts` reads front matter and manifests; GitHub Actions workflow files exceed it (anchors, merge keys, multi-line flow collections), and the engines answer that with the `yaml` package. It is bundled into the extension host only, never into the MCP server.
