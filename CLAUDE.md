# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository. It applies to any AI coding agent working in **zer0-CMS** (Claude Code, Copilot, Cursor).

zer0-CMS has two halves. `src/` is the **VS Code extension** — a lightweight, zero-runtime-dependency CMS that *edits* content: a metadata panel over the active file's front matter, a content dashboard, SEO insights, and a governed publishing path (draft → brand guard → human approval → publish → idempotency ledger). It was once a fork of Front Matter CMS and keeps that interaction design on purpose, but shares no code with it; see `ATTRIBUTION.md`. `rails/` is the **ABC generator** — a Ruby on Rails app + stdlib-only Ruby library that *generates* content, starting with children's **ABC / alphabet books**: it writes the words, composes a text-free illustration prompt per letter (art styles shared with the `zer0-image-generator` plugin), and exports a Jekyll board book for **drsai** to publish. "Done" for a generator change means `ruby -Ilib test/zer0_cms/*.rb` passes and the wizard still emits a valid ABC Book Spec. It is gated by its own `abc-engine.yml`, not by the extension's workflow. Do not call it "the content engine" — that name belongs to the `.cms/` contract engine in `src/core/contract/`, and the collision has already confused readers.

## Stack & commands

```bash
# ── VS Code extension (src/) — vanilla TypeScript, esbuild, no framework ──
npm install
npm run compile      # check-types + lint + all five bundles
npm run watch        # then F5 in VS Code to launch the Extension Host
npm test             # pretest (tsc → out/, then compile) + unit, golden, MCP stdio, integration
npm run check-types  # tsc --noEmit on its own
npm run lint         # eslint src on its own

# Fast inner loop — the twelve pure-Node suites under plain Mocha, no VS Code download.
# Needs Node >= 22.12: the engines seam is an ESM package reached through require(esm).
npx tsc -p . --outDir out
npx mocha --ui tdd out/test/{core,fields,governance,golden,loop,fleet,engines,routes,webview,styling,platform,audit}.test.js
npx mocha --ui tdd out/test/governance.test.js --grep "ledger"   # one suite or one test

# ── ABC generator (rails/) — stdlib-only, no bundler needed ──
cd rails
ruby bin/zer0-cms styles                         # list ABC art styles
ruby bin/zer0-cms themes                         # list bundled A–Z lexicons
ruby bin/zer0-cms new --theme "IT systems" --out ../../drsai   # draft + export a book
ruby bin/zer0-cms new --theme "the ocean" --print              # preview, write nothing
ruby -Ilib test/zer0_cms/test_abc_engine.rb      # generator tests (16 runs, zero network)
bundle install && bundle exec puma -p 3000 config.ru   # optional web wizard (there is no bin/rails binstub)

python3 tools/unwrap-prose.py --write   # fix the markdown one-paragraph-per-line CI gate
```

`extension.test.ts` needs a real extension host and `mcp.test.ts` needs `dist/mcp-server.js`, so neither runs on the plain-Mocha path. On headless Linux `npm test` shells out to `xvfb-run` itself (`test-runner.js`); `ZER0_CMS_NO_XVFB=1` forces the plain path.

## Extension architecture — the rules the build enforces

- **`src/core/` and `src/mcp/` must not import `vscode`.** They are pure Node. eslint blocks it, and the MCP bundle (which marks nothing external) turns a stray import into a build error. If core needs the editor, take it as a parameter or an injected callback. `npm run compile` failing with `Could not resolve "vscode"` *is* this gate firing.
- **`src/webview/` must not import `vscode`, `commands/` or `views/`** — it runs in a browser context and talks to the host over `postMessage` only.
- **Zero *shipped* runtime dependencies** (decision D3, amended by D14 — see `docs/ARCHITECTURE.md`). `dependencies` is empty and stays empty. A build-time library may be bundled by esbuild from `devDependencies`, but only when it is named in that target's allow-list in `esbuild.js`: today that is `@bamr87/fleet-engines` and its `yaml`, admitted to `dist/extension.js` alone (they enter the bundle when a host surface consumes the seam). **The MCP bundle allows no bare import at all** — the gate that has always guarded `vscode` now guards every package, so `dist/mcp-server.js` stays standalone. `@anthropic-ai/claude-agent-sdk` remains the one optional, dynamically-imported exception. YAML-subset parsing, globbing, date formatting, JSONC and Python-parity JSON output stay hand-rolled in `src/core/shared/`.
- **The engines seam is never re-exported.** `src/core/fleet/engines.ts` is the only file that imports `@bamr87/fleet-engines`, and `src/core/index.ts` never re-exports it — the package's `FleetLane`/`FleetManifest`/`parseFleetManifest` collide with names this repo already declares, and `export *` breaks on a duplicate. Convert at the boundary through `src/core/fleet/adapters.ts` instead, and keep this repo's tristate (`null` = "the manifest did not say") rather than adopting the package's defaults.
- **No `innerHTML` in `src/webview/`.** Build DOM with `el()`, assign text with `textContent`.
- **The webview is UI, never the gate.** Buttons post an intent and a target — never a payload or an override. Every gate is re-checked host-side in the same function the command palette calls. A disabled button is a courtesy to the person, not a control.
- Golden fixtures under `src/test/fixtures/golden/` are generated by the Python publishing lane (`generate.py`). Regenerate them; never hand-edit one to make a test pass.
- Import core through the barrel (`../core`), not from individual files. Cross-cutting types are declared once in `src/core/shared/types.ts` — redeclaring a name makes `export *` ambiguous and breaks the barrel for everyone.

### The five bundles (`esbuild.js`)

`dist/extension.js` (node; `vscode` + agent SDK external) · `dist/mcp-server.js` (node; **nothing** external — the layering gate) · `dist/panel.js` · `dist/dashboard.js` · `dist/agent.js` (browser, iife). `media/*.css` and the codicon font are copied into `dist/media/` at build time; a missing codicon file is a deliberate build error, because without it every icon renders empty and the build still looks green.

### Invariants that are easy to break

- **Configuration is three layers** (VS Code settings → `zer0.json` → `package.json` defaults), and `src/config.ts` reads settings through `inspect()` rather than `get()` on purpose: every setting has a default, so `get()` always returns a value and `zer0.json` could never win. Keep only what a human actually set. Nothing is cached — `currentConfig()` re-reads on every call, which is why flipping `publishAllow` takes effect without a window reload.
- **Front matter is edited by line surgery.** `updateFrontMatterKeys()` rewrites only the lines belonging to changed keys, so untouched lines come out byte-identical and comments and hand-formatting survive. Dates stay strings end to end — round-tripping through a JS `Date` is how a CMS silently shifts published timestamps by a timezone.
- **The ledger is keyed by canonical URL** and written byte-compatible with Python's `json.dump` (`sort_keys`, `ensure_ascii`, indent 2, trailing newline). That is what lets this extension and the CI lane share one queue without double-publishing, and what keeps the file from churning in git.
- **The platform is a profile, and Jekyll's answers are pinned.** Nothing platform-specific may be hard-coded outside `src/core/platform/profiles/`. `src/test/fixtures/golden/platform/` records what the pre-profile code computed for the fixture pages; regenerate it with its own `generate.mjs` and read the diff — a byte change there is a behaviour change and needs a reason, not a re-baseline.
- **`.cms/` absence is a normal state, not an error.** With no contract, the page index supplies the same `ContentRecord` shape with `health: -1` and `freshness: 'unknown'`. Report less; never invent a health score.
- **MCP registration is two-phase.** `provideMcpServerDefinitions` may be cached, so it returns an empty `env`; `resolveMcpServerDefinition` runs at server start and is the only place the publish flag or a secret is read — and it reads the **settings** layer, not the merged config, because a cloned repo's `zer0.json` must not be able to arm an agent to publish. When publishing is off the env var is set to `null` (remove it), not `"0"` and not merely omitted.
- **Context keys: ten, and every one gates something.** Grep `package.json` for a key before adding one; `uiState.ts` mirrors each in memory and only calls `setContext` on a change. `zer0Cms:workspace:trusted` is the exception that proves the rule — it gates `when` clauses, but no gate *relies* on it: every function that spawns re-asks `workspaceTrusted()`, because a context key is a rendering hint and a trust decision is not.
- **The Fleet console: the webview sends `{lane}` and nothing else; the host re-reads the manifest and derives the value.** `doToggleSwitch`/`doDispatchLane` (`src/commands/fleet.ts`) re-read `fleet.manifest.yml` from disk, re-run `evaluateFleetGates()` and derive a toggle's new value from the variable as GitHub reports it, never from a message. The master gate `zer0Cms.fleet.dispatchAllow` is read from the settings layer only (`settingsFleetDispatchAllow()`); `zer0.json` cannot arm it. Network happens only from an explicit user action, through the `fetch` injected into `core/fleet/github.ts`, never at activation (decision D11) — and every call is in `FLEET_PLAN` or the client refuses it. The MCP server's `zer0_fleet_status` reads the local manifest and nothing else.

### Adding a command

Declare it in `package.json` under `contributes.commands` (with any `when` clause in `contributes.menus`), implement it in the matching `src/commands/*.ts` taking the `Zer0Shell`, and do **not** add a registration to `extension.ts` — the module registers itself. Any action that writes, publishes or approves must route through a function the command palette also calls, and that function must re-read state from disk and re-run `evaluateGates()` before acting.

## Engine architecture (`rails/`)

`lib/` is stdlib-only and gem-free by design — CI runs its tests with no `bundle install`, so a gem under `lib/` is exactly the regression that job catches. Rails-only code stays in `app/`. The wizard pipeline is theme → plan → art direction → per-letter → cover → validated `Spec` (`lib/zer0_cms/abc/`), written out by `jekyll_exporter.rb`. Bundled themes generate offline and deterministically; any other theme falls back to Claude and needs `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`. `lib/zer0_cms/data/abc_art_styles.yml` is a **byte-identical vendored copy** from `zer0-image-generator` — re-sync it rather than edit it; each style `id` is a cross-repo contract. Never hand-edit a generated book in drsai; re-run the wizard.

## Conventions

- Conventional Commits: `type(scope): description` (`feat`/`fix`/`docs`/`refactor`/`test`/`chore`/`ci`).
- Default branch is `main` — branch from it and open a PR; never push to it directly.
- README-First, README-Last: read the nearest `README.md` before changing a directory, and update it after. The dense ones are `src/README.md`, `src/core/README.md`, `src/test/README.md` and `docs/ARCHITECTURE.md`.
- One paragraph per line in markdown — CI enforces it (`tools/unwrap-prose.py`).
- Every source file opens with a short block comment saying what it is and why it exists.
- Don't suppress type errors (`as any`, `@ts-ignore`, `# type: ignore`) or leave empty exception handlers — eslint errors on all four.

## Fleet context

This repo is one of ~40 managed by the [bamr87/bamr87 dash](https://github.com/bamr87/bamr87) (registry: `_data/projects.yml`; tiered baseline: `docs/STANDARDS.md`). It is vendored there as a git submodule: commit and push changes **here** first — the hub only bumps its pointer afterwards. Shared CI, release, schema, and agent kits are seeded from the hub's `templates/`; prefer adopting those over hand-rolling equivalents. `.github/workflows/ci.yml` and `markdown-oneline.yml` are thin hub-seeded callers — don't edit their logic. `extension.yml` is this repo's own and gates the extension alone; the ABC generator has its own `abc-engine.yml`, filtered to `rails/**`, so an extension pull request no longer runs Ruby and a generator change no longer downloads VS Code. `release.yml` calls the hub's release-please workflow and then a repo-owned marketplace job — see `docs/RELEASING.md`.

## Standard deviations

Three, all dated 2026-09-09 and all consequences of consuming the hub's engines package rather than copying it.

- **The lockfile is committed**, against the hub's `lockfiles: never-commit` posture. `npm ci` needs it, and so does the reusable relock job; more importantly an exact-pinned engines version is only reproducible with one.
- **`@bamr87/fleet-engines` is exact-pinned**, against the hub's always-latest convention. A bump changes generated goldens, so it is a deliberate `chore(deps)` pull request whose diff a person reads, not an ambient upgrade.
- **`yaml` is bundled.** The hand-rolled YAML subset in `src/core/shared/config.ts` reads front matter and manifests; GitHub Actions workflow files exceed it (anchors, merge keys, multi-line flow collections), and the engines answer that with the `yaml` package. It is bundled into the extension host only, never into the MCP server.
