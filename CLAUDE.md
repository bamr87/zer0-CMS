# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. It applies to any AI coding agent working in **zer0-CMS** (Claude Code, Copilot, Cursor).

zer0-CMS has two halves. `src/` is the **VS Code extension** — a lightweight, zero-runtime-dependency CMS that *edits* content in the editor: a metadata panel, dashboard, SEO insights, and a governed publishing path (draft → brand guard → human approval → publish → ledger). `rails/` is the **fleet CMS** — a Rails 8.1 app on Administrate 1.0 that indexes every registered Jekyll site into SQLite and writes edits back to the files (git stays the source of truth), draws a missing preview through zer0-image-generator, and hosts the ABC book wizard; `rails/lib` is a stdlib-only library (the Jekyll-exact catalog, front-matter surgery, the confined writer, `zer0 doctor`, the ABC generator). "Done" for a `rails/lib` change means `rails/bin/test-stdlib` passes with no bundler. "Done" for the app means `bin/rails test` and `bin/rails zeitwerk:check` pass, and — when `rails/Dockerfile` or `docker-compose.yml` changed — the image still builds, boots and answers `/up`. Do not call Rails "the content engine" — that name belongs to `.cms/` in `src/core/contract/`. Platform contract: `docs/PLATFORM.md`. Stack contract: `docs/ZER0-STACK.md`. CI map: `docs/CICD.md`.

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
ruby bin/zer0-cms doctor ../../lifehacker.dev      # zer0 stack alignment; exit 1 on any error
ruby bin/zer0-cms new --theme "IT systems" --out ../../drsai   # an ABC book, headless
bundle install && bin/rails db:prepare
SITES_DIR=$HOME/github bin/rails server            # http://localhost:3000/admin
bin/rails test && bin/rails zeitwerk:check         # the app; image-engine tests need python3 + PyYAML
# Docker, from the repository root (127.0.0.1 only): http://localhost:3001/admin
SITES_DIR=$HOME/github docker compose up --build
SITES_DIR=$HOME/github docker compose --profile imagegen up --build   # + zer0-image-generator on :3000

python3 tools/unwrap-prose.py --write   # fix the markdown one-paragraph-per-line CI gate
```

`extension.test.ts` and `multiroot.test.ts` need a real extension host (`multiroot` has its own entry in `.vscode-test.mjs`: `npx vscode-test --label multiroot`), and `mcp.test.ts` needs `dist/mcp-server.js`, so the fourteen-suite command above leaves all three out; `out/test/mcp.test.js` does run under plain Mocha once `npm run compile` has built the bundle. On headless Linux `npm test` shells out to `xvfb-run` itself (`test-runner.js`); `ZER0_CMS_NO_XVFB=1` forces the plain path.

## Extension architecture — the rules the build enforces

- **`src/core/` and `src/mcp/` must not import `vscode`.** They are pure Node. eslint blocks it, and the MCP bundle (which marks nothing external) turns a stray import into a build error. If core needs the editor, take it as a parameter or an injected callback. `npm run compile` failing with `Could not resolve "vscode"` *is* this gate firing.
- **`src/webview/` must not import `vscode`, `commands/` or `views/`** — it runs in a browser context and talks to the host over `postMessage` only.
- **Zero *shipped* runtime dependencies** (decision D3, amended by D14 — see `docs/ARCHITECTURE.md`). `dependencies` is empty and stays empty. A build-time library may be bundled by esbuild from `devDependencies`, but only when it is named in that target's allow-list in `esbuild.js`: today that is `@bamr87/fleet-engines` and its `yaml`, admitted to `dist/extension.js` alone (they enter the bundle when a host surface consumes the seam). **The MCP bundle allows no bare import at all** — the gate that has always guarded `vscode` now guards every package, so `dist/mcp-server.js` stays standalone. `@anthropic-ai/claude-agent-sdk` remains the one optional, dynamically-imported exception. YAML-subset parsing, globbing, date formatting, JSONC and Python-parity JSON output stay hand-rolled in `src/core/shared/`.
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
- **Vendored files are byte-identical copies, never edited here:** `app/assets/stylesheets/zer0-tokens.css` (kit `zer0-ui-tokens`, from zer0-image-generator), `lib/zer0_cms/data/abc_art_styles.yml` (zer0-image-generator), `lib/zer0_cms/data/frontmatter_schema.yml` (zer0-mistakes). Re-sync them with `cp` and check with `cmp`.
- The ABC wizard exports only into an explicit Jekyll root; bundled themes generate offline, anything else falls back to Claude. Never hand-edit a generated book in drsai; re-run the wizard.

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`/`style`).
- Default branch is `main` — branch from it and open a PR; never push to it directly.
- README-First, README-Last: read the nearest `README.md` before changing a directory, and update it after. The dense ones are `src/README.md`, `src/core/README.md`, `src/test/README.md` and `docs/ARCHITECTURE.md`.
- One paragraph per line in markdown — CI enforces it (`tools/unwrap-prose.py`).
- Every source file opens with a short block comment saying what it is and why it exists.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or leave empty exception handlers — eslint errors on all four.

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents. `.github/workflows/ci.yml` and `markdown-oneline.yml` are thin hub-seeded callers — don't edit their logic. `extension.yml` is this repo's own and gates the extension alone; the Rails half has two of its own, both filtered to `rails/**` — `abc-engine.yml` (`rails/lib` with no bundler, Ruby 3.3 and 4.0.5) and `rails-app.yml` (the app with its bundle, Zeitwerk, and a production boot) — so an extension pull request no longer runs Ruby and a Rails change no longer downloads VS Code. `zer0-doctor.yml` is the reusable consumer-contract check content repositories call. `release.yml` calls the hub's release-please workflow and then a repo-owned marketplace job — see `docs/RELEASING.md`. `claude.yml` is the `@claude` mention lane (`anthropics/claude-code-action@v1`), the only workflow that calls a model and the one lane `fleet.manifest.yml` declares; `codeql-analysis.yml` is GitHub CodeQL (`github/codeql-action@v4`).

## Standard deviations

Three, all dated 2026-09-09 and all consequences of consuming the hub's engines package rather than copying it.

- **The lockfile is committed**, against the hub's `lockfiles: never-commit` posture. `npm ci` needs it, and so does the reusable relock job; more importantly an exact-pinned engines version is only reproducible with one.
- **`@bamr87/fleet-engines` is exact-pinned**, against the hub's always-latest convention. A bump changes generated goldens, so it is a deliberate `chore(deps)` pull request whose diff a person reads, not an ambient upgrade.
- **`yaml` is bundled.** The hand-rolled YAML subset in `src/core/shared/config.ts` reads front matter and manifests; GitHub Actions workflow files exceed it (anchors, merge keys, multi-line flow collections), and the engines answer that with the `yaml` package. It is bundled into the extension host only, never into the MCP server.
