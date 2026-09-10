# Architecture

zer0-CMS is a VS Code extension with a hard internal boundary. This document explains where the boundary is, why it is there, and what it buys.

## Design decisions D1–D14

These fourteen decisions are the reason the code looks the way it does. They were made before the first line was written and lived, until now, only in a design conversation — fifteen source and doc files cited them as `PLAN §x.y` against a document that was never in this repository. They are restated here from the code, so a citation resolves and an amendment has somewhere to land. Each names the mechanism that enforces it, because a decision no mechanism defends is a preference.

| # | Decision | Enforced by |
|---|---|---|
| **D1** | **`src/core` and `src/mcp` are pure Node.** The editor API is available only in the shell (`extension.ts`, `config.ts`, `commands/`, `views/`, `panel/`, `dashboard/`, `agent/`). If core needs the editor, it takes a parameter or an injected callback. | eslint `no-restricted-imports`; the MCP bundle's empty `external` list turns a stray import into a build error; every core test runs without an extension host |
| **D2** | **Configuration is three layers** — VS Code settings, then `zer0.json`, then the manifest defaults — resolved per key. `src/config.ts` reads settings through `inspect()` rather than `get()`, because every setting has a default and `get()` would always return one, so `zer0.json` could never win. Nothing is cached: `currentConfig()` re-reads on every call, which is why flipping a gate takes effect without a window reload. | `explicit()` in `src/config.ts`; `resolveConfig` is pure and shared by the extension, the MCP server and the tests |
| **D3** | **Zero *shipped* runtime dependencies.** `dependencies` is `{}` and stays `{}`. *Amended 2026-09-09 (see D14):* build-time libraries may be bundled by esbuild from `devDependencies` when they are named in the bundler's allow-list. The Claude Agent SDK remains the one optional, dynamically-imported exception. | `dependencies: {}`; the bare-import gate in `esbuild.js`; a test that `dist/mcp-server.js` contains no third-party package |
| **D4** | **One full-state snapshot per render.** The host posts a whole `state` object; the webview never asks for a fragment. A protocol with a hundred wire names has a hundred entry points to audit. | `WorkspaceStore`'s single `Snapshot`; the `RequestOp` union is eight named operations, not an open channel |
| **D5** | **The webview is UI, never the gate.** A button posts an intent and a target — never a payload, never an override. Every gate is re-checked host-side, in the same function the command palette calls, after re-reading state from disk. A disabled button is a courtesy to the person, not a control. | `doApprove`/`doPublish`/`doToggleSwitch`/`doDispatchLane` re-read and re-evaluate; the message shapes carry ids only |
| **D6** | **Eighteen field types, not the upstream twenty-two.** The five dropped (`dataFile`, `dataBlock`, `block`, `fieldCollection` as a storage type, `dropdown`) either needed a second configuration file or duplicated another type. | `FIELD_TYPES` and its test; `schemas/zer0.schema.json` |
| **D7** | **Front matter is edited by line surgery.** Only the lines belonging to changed keys are rewritten; untouched lines come out byte-identical, so comments and hand-formatting survive. Dates stay strings end to end. | `updateFrontMatterKeys`; full re-serialization is a documented fallback, not the path |
| **D8** | **Publishing is an interface, not a vendor.** `PublishTarget` has a pure `build` and an effectful `send`; the registry is open. A target's `build` never touches the network or the disk, which is what makes a preview provably free of side effects. | `registerTarget`/`targetById`; a throwing-`fetch` plus tree-snapshot test per target |
| **D9** | **`.cms/` absence is a normal state.** With no contract, the page index supplies the same `ContentRecord` shape with `health: -1`, `freshness: 'unknown'` and `UNKNOWN_COUNT` sentinels. Report less; never invent a number. | `pageToRecord`; `countLabel`; the contract's `{present: false}` branch |
| **D10** | **`canUseTool` is the single agent gate.** `allowedTools` is never passed to the SDK, because a tool allow-list negotiated at session start cannot show a person the diff it is about to write. Read-only tools run freely; everything else goes through an approve/deny card. | `QueryOptions` deliberately omits `allowedTools`; `READ_ONLY_TOOLS` |
| **D11** | **Network only from an explicit user action.** Activation opens no socket, and neither does the MCP server process. A GitHub session is obtained lazily inside the action, asked for per request, and never stored. Every call the console can make is declared as data and checked against that plan before a socket opens. | `FLEET_PLAN`; `fleetSurfaceIsRepoScopedOnly`; the injected `fetch`; a suite that intercepts `fetch` to prove it from outside |
| **D12** | **A site's platform is a profile, resolved once, never guessed twice.** Jekyll, MkDocs, Wiki.js, Hugo, Docusaurus, Astro and a generic fallback are data — content roots, front-matter dialect and keys, the draft convention, date keys and formats, the slug and permalink rules, output directories to skip, the serve command and preview URL. Detection is by marker file; an explicit `platform.id` in `zer0.json` always wins; zer0-mistakes is an **overlay on Jekyll**, never a sibling identity. Nothing platform-specific is hard-coded outside a profile. | `src/core/platform/`; a golden that pins the Jekyll projection byte-for-byte against the pre-refactor code |
| **D13** | **VS Code Workspace Trust is the outer gate; the settings-only switches are the inner one.** The extension declares `untrustedWorkspaces: limited`. In an untrusted workspace it reads and edits front matter but runs nothing: not the content engine, not a placeholder script, not the verify command, not the agent, and it registers no MCP server. Trust is re-checked inside every function that spawns, not only in a `when` clause. | `capabilities.untrustedWorkspaces.restrictedConfigurations`; `evaluateExecGate`; `workspaceTrusted()` inside `mcpPublishAllowed`, `settingsFleetDispatchAllow` and `settingsFleetScaffoldAllow` |
| **D14** | **A build-time dependency is bundled and allow-listed; a runtime dependency is still forbidden.** `@bamr87/fleet-engines` (and the `yaml` it needs) are exact-pinned `devDependencies`, and the bundler's allow-list admits them into `dist/extension.js` alone — so they enter the shipped bundle when, and only when, a surface in the extension host consumes the seam. The MCP bundle allows **no** bare import, so the layering gate that has always guarded `vscode` now guards every package. One seam, `src/core/fleet/engines.ts`, is the only importer, and it is never re-exported through the core barrel: everything else takes the engines as injected data, which is why the seam can stay out of the MCP graph entirely rather than relying on tree-shaking to remove it. | the per-target bare-import gate in `esbuild.js`; the metafile assertion on `dist/mcp-server.js`; eslint patterns forbidding the seam under `src/mcp/**` |

**Why the engines arrive by dependency rather than by copy.** The audit rulebook, the workflow-facts scanner and the metrics engine already exist twice in this fleet — once in GitFactory's browser app and once in the hub's package — and the two copies have already diverged by one rule. A third copy inside this extension would diverge again, silently, and the two consoles would then disagree about whether a lane is safe. Consuming the published package is what keeps one answer.

## The layer map

```
┌──────────────────────────────────────────────────────────────┐
│ src/webview/            vanilla TS + CSS, runs in a browser  │
│   shared/  panel/  dashboard/  agent/                        │
│   • no `vscode`, no innerHTML, no framework                  │
└───────────────▲──────────────────────────────────────────────┘
                │  postMessage: an intent and a target
┌───────────────┴──────────────────────────────────────────────┐
│ src/  (the shell)       the only code that imports `vscode`  │
│   extension.ts  config.ts  store.ts  logger.ts               │
│   commands/  views/  panel/  dashboard/  agent/              │
└───────────────▲──────────────────────────────────────────────┘
                │  plain values in, plain values out
┌───────────────┴──────────────────────────────────────────────┐
│ src/core/               pure Node. No `vscode`, ever.        │
│   shared/  content/  governance/  catering/  contract/       │
│   analytics/  portfolio/  media/  fleet/                     │
└───────────────▲──────────────────────────────────────────────┘
                │
┌───────────────┴──────────────────────────────────────────────┐
│ src/mcp/                the standalone MCP server            │
│   also pure Node — it runs outside the extension host        │
└──────────────────────────────────────────────────────────────┘
```

## Why `src/core` cannot import `vscode`

Three enforcement mechanisms, on purpose:

1. **eslint** — `no-restricted-imports` on `src/core/**` and `src/mcp/**`.
2. **The MCP bundle** — `esbuild.js` builds `dist/mcp-server.js` with an **empty `external` list**. A stray `import 'vscode'` anywhere in that import graph fails the build, loudly, at build time, instead of crashing inside somebody's MCP client at runtime.
3. **The tests** — `src/core` is exercised by plain unit tests that never launch an extension host, which is only possible because it has no editor dependency.

The payoff is not tidiness. It is that **the same publish gate runs identically from a command, a webview and an MCP client**, because all three call the same pure function. There is one gate to audit.

## The five bundles

| Bundle | Platform | External |
|---|---|---|
| `dist/extension.js` | node20, cjs | `vscode`, `@anthropic-ai/claude-agent-sdk` |
| `dist/mcp-server.js` | node20, cjs | *nothing* |
| `dist/panel.js` | browser, iife | nothing |
| `dist/dashboard.js` | browser, iife | nothing |
| `dist/agent.js` | browser, iife | nothing |

`media/*.css` is copied to `dist/media/` at build time and loaded through `webview.asWebviewUri`.

## The webview contract

**One full-state message per render.** The host posts a single `state` snapshot; the webview posts back one of a small set of message shapes carrying an intent and a target.

This replaces the more common pattern — every control talking to the host with its own message name — for one reason: a protocol with a hundred wire names has a hundred entry points to audit, and each one is a place where a webview can ask for something a person did not.

The rule that follows from it:

> **The webview is UI, never the gate.**
>
> A button posts `{type: 'command', id: 'draft.publish', args: {draftPath}}`. It does not post the payload to publish, the guard result, or an override flag. The host re-reads the draft from disk, re-runs the guard, and re-evaluates every blocker before it does anything — in the same function the command palette calls.

A disabled Publish button in the webview is a courtesy to the person, not a security control.

## Security posture of the webviews

- Strict CSP with a per-render nonce; `default-src 'none'`.
- No external resources of any kind — no CDN, no font fetch, no image host.
- Content is inserted with `textContent` via `el()`. `innerHTML`, `outerHTML` and `insertAdjacentHTML` are eslint errors in `src/webview/**`.
- Colours come from VS Code theme variables only, mapped through one file (`media/tokens.css`) so themes stay consistent and the rest of the CSS never touches `--vscode-*` directly.

## Front matter is edited by line surgery

`updateFrontMatterKeys(raw, changes)` rewrites **only the lines belonging to changed keys** and appends new keys before the closing fence. Untouched lines come out byte-identical.

This is why comments and hand-formatting survive an edit from the panel, and it is deliberate rather than incidental: a CMS that reformats a file on every field change makes its own diffs unreadable and its users distrust it. Full re-serialization exists as a documented fallback for changes the line-locator cannot resolve.

Dates stay strings through the whole pipeline. Round-tripping a date through a JS `Date` is how CMSes silently shift published timestamps by a timezone.

## The `.cms/` contract, and its absence

When the repo runs a content engine, `.cms/index/content-index.json` gives per-file health, freshness, and typed issues split into **mechanical** (a script can fix it) and **substantive** (a person has to) lanes.

When it does not, `loadContract()` returns `{present: false}` and the page index supplies the same `ContentRecord` shape with `health: -1` and `freshness: 'unknown'`. The distributable rule degrades honestly to "not a draft and has a title".

Absence is a normal state, not an error. The UI reports less; it does not break, and it does not pretend to know a health score it has not been given.

## The ledger

A flat JSON file keyed by **canonical URL**, written atomically with Python-compatible formatting (`sort_keys`, `ensure_ascii`, 2-space indent, trailing newline).

Two properties matter:

- **Idempotency.** Whichever lane publishes first — this extension or a CI workflow — the other one sees the key and skips. That is the whole reason the key is the canonical URL rather than a file path or a timestamp.
- **Byte compatibility.** Both lanes write the same file in the same repo. If the two serializers disagreed by so much as a space, the file would churn on every run and the git history would be noise. Golden fixtures in `src/test/fixtures/golden/` pin this.

## Activation

`activate()` does no network I/O, no telemetry, and no auth check. In a folderless window it installs zero watchers and returns. The store keeps one snapshot for all four tree views and both webviews, with refreshes coalesced through a single in-flight promise so a burst of file events costs one rebuild.

## The Fleet console

The first surface in the extension that talks to another system. It reads this repository's `fleet.manifest.yml` (spec `fleet/v1`, from bamr87/wtd's `docs/FLEET-SPEC.md`): the AI lanes, each with its harness, its workflow file, its triggers, its `*_ENABLED` repository-variable switch, the tokens it spends and the guardrails it declares. The dashboard's Fleet tab draws that table and, from GitHub, two more columns — the switch's current value and the workflow's newest run — and offers two verbs: flip the switch, or dispatch the lane once.

**What it reads, declared before it is read.** `core/fleet/github.ts` lists every call as data — three `GET`s (a variable, a workflow's newest run, the default branch) and three writes (`PATCH`/`POST` a variable, `POST` a dispatch) — and `fleetSurfaceIsRepoScopedOnly` is a test that every path sits under the repository's own `/actions/` and never names a person. The client refuses a request outside that plan before opening a socket, and the suite intercepts `fetch` to prove it from the outside. No secret is ever read: the manifest names tokens, the console shows names.

**The gates.** `evaluateFleetGates(mode, input)` is `governance/approval.ts` with a different vocabulary and the same properties: pure, a fixed and tested blocker order (`noWorkspace, dispatchDisabled, noCredential, manifestAbsent, laneUnknown, laneHasNoSwitch, laneNotDispatchable, guardrailViolation`), and a master gate nothing overrides. That gate is `zer0Cms.fleet.enabled` **and** `zer0Cms.fleet.dispatchAllow`, and the second is read from the VS Code settings layer alone — a `zer0.json` or a manifest arriving with a cloned repository cannot arm it, for the reason the MCP publish flag cannot be armed by a file. `guardrailViolation` refuses a lane whose own manifest admits to merging or writing to the default branch. Both privileged actions (`doToggleSwitch`, `doDispatchLane` in `src/commands/fleet.ts`) re-read the configuration, re-read the manifest from disk, re-run the gate and ask modally — naming the repository, the lane, the variable and the value — inside the same function the palette calls. The webview sends `{lane}` and nothing else; a toggle's new value is derived host-side from the variable as fetched a moment earlier, never from a message.

**Decision D11.** The activation promise above stands. The relaxation is exactly this: network happens only from an explicit user action — the Refresh button, a toggle, a dispatch, or opening the Fleet tab (a passive read that never prompts for sign-in) — through a `fetch` the shell injects into the core's client, and never at activation. The credential is `vscode.authentication.getSession('github', …)`, obtained lazily inside the action and asked for per request; the extension stores no token. The bundled MCP server keeps its side of the rule absolutely: `zer0_fleet_status` reads the local manifest and reports the switch state as unknown, because that process never opens a socket.

Slice 1 is one repository and two verbs. A multi-repo roster, the facts and audit engines, and any MCP write tool come from the hub's `@bamr87/fleet-engines` package in slice 2.

## Where the AI lives

Two separate, independently-disableable surfaces:

- **The MCP server** (`src/mcp/`) — twelve tools for any MCP client. The doctrine-preferred path is `zer0_draft`: the model writes a draft, a person approves it. `zer0_publish` needs an environment flag *and* a per-call confirmation.
- **The agent** (`src/agent/`) — the Claude Agent SDK, loaded through a dynamic import so it is never bundled, gated on a setting that defaults to off, and absent from the dependency tree unless you ask for it. Read-only tools run freely; every mutating tool goes through an approve/deny card showing the diff.

Neither is required to use the CMS, and neither can publish without walking through the same gate a human command does.

## The contract map

This console is one of several tools operating the same fleet, and almost nothing it consumes is its own invention. Each row names who owns a shape, what this repository consumes of it, and where that consumption is pinned so a drift upstream is a failing test rather than a surprise.

| Contract | Owner | What this console consumes | Pinned here |
|---|---|---|---|
| `fleet/v1` manifest | `bamr87/wtd`, `docs/FLEET-SPEC.md` | the lanes, their harness, triggers, `*_ENABLED` switch, tokens and guardrails | `src/core/fleet/manifest.ts` keeps its own tolerant parser (a wrong `spec_version` is refused, an unsaid guardrail stays `null` rather than becoming `false`), with a parity test against the package's parser over every committed manifest in the fleet |
| `@bamr87/fleet-engines` | the hub, `templates/fleet-engines` | workflow facts, the audit rulebook, run metrics, harness health, the hub reader, the roster helpers | one seam, `src/core/fleet/engines.ts`, never re-exported through the barrel; goldens carry the engines version that generated them |
| the `ai-runner` kit | the hub, `.github/actions/claude-run` and `.github/workflows/ai-lane.yml` | the reusable lane's inputs and the caller template a generated lane is written from | a stamped vendored copy under `media/templates/`, byte-compared against a fixture copy of the hub's, with a drift test on the input list |
| `wtd fleet adopt` derivation | `bamr87/wtd` | how a workflow becomes a lane: the harness patterns, the switch pick, the token list | a TypeScript port used only to **agree**, never to overwrite a committed manifest; where the two disagree, the console shows a drift row |
| the front-matter rule ids | `lifehacker.dev`, `scripts/ci/lint_frontmatter.rb` | the names of the audit's findings | the same id strings, one test per rule, so an issue filed from CI and one raised in the editor dedupe against each other |
| the GitFactory deep link | `bamr87/gitorio` | the roster URL this console hands off to | asserted **parseable by** that app's own parser, not byte-equal to its writer |

**The division of labour.** GitFactory designs and observes in the browser and owns the workflow files it compiles. `wtd` owns deriving a manifest from workflows. The hub owns the runtime, the registry and the engines. This console operates, inside the editor, on files a person already has open. Where those boundaries touch a write, the rule is written down in `src/core/fleet/README.md` and defended by a test.

## What this console will never do

It never merges, approves, closes, or removes a review label. It never reads or writes an Actions secret. It never opens a socket during activation, from the bundled MCP server, or on a timer. It never stores a credential. It never edits a workflow file GitFactory compiled. It never writes a manifest field it derived rather than read. Each of those is a test, not a promise: the fleet plan is data, and two guards assert both that every declared call stays inside this repository's own sub-resources and that no declared call is a merge verb.

## Security: the five execution vectors

Five paths in this extension can start a process, and Workspace Trust is the outer gate on all of them: the content engine, the front-matter normalizer, a `placeholders[].script`, the verify command, and the AI agent. In an untrusted workspace every one refuses — as a result value, never as a thrown exception — and the extension registers no MCP server at all, because that server would inherit the same reach.

The inner gate is different in kind. A cloned repository ships its own `zer0.json`, so anything that arms a write is read from the VS Code settings layer alone and never from the file: publishing, fleet dispatch, and lane scaffolding. A path that resolves outside the workspace root is refused whichever layer supplied it. The `when` clause on a command is the courtesy; the check inside the function is the gate, and it re-reads trust rather than trusting a context key that was set at activation.

## Appendix: the inherited design baseline

Fifteen files in this repository cite a plan document by section number. That document was a design conversation, not a file, and it was never committed — `git log --diff-filter=D` finds no deletion because there was nothing to delete. What those sections actually govern is restated below, from the code, so the citations resolve. Where a number appears, the test that pins it is named, because a number in prose rots and a number in a test cannot.

**The panel's sections** (cited as §3.1). Seven section ids exist — governance, metadata, seo, actions, recent, settings, other — and `zer0Cms.panel.sections` chooses which appear and in what order. Their order in `PANEL_SECTION_IDS` is the render order; each section's collapse state persists under `zer0Cms:Panel:collapse_<id>`, where the absent value means expanded and the string `'false'` means collapsed.

**The dashboard's routes** (cited as §3.2). `DASHBOARD_ROUTES` is the closed set of route ids in display order; `DASHBOARD_TABS` is the subset currently offered, in the same relative order. Rendering passes three gates in this order and no other: no snapshot yet renders a loader with a five-second escape hatch; an uninitialized project or one with no content folders renders Welcome alone, with no tab bar; otherwise the persisted route renders if the host offered it, and degrades to Contents if it did not. A tab the host drops — Distribution without a `.cms/` contract, Fleet with the fleet console off — is absent from `state.tabs`, which is what makes a stale persisted route degrade rather than blank the page.

**The request operations** (cited as §4.3). `RequestOp` is a closed union of named operations the webview may ask the host to perform and await a reply for. It is deliberately not an open channel: a new operation is a new literal, reviewed, and implemented in exactly one host.

**The webview's chrome** (cited as §4.4). `localResourceRoots` is limited to the extension's own `dist/media`; the Content-Security-Policy is `default-src 'none'` with a per-render nonce for script and style, the webview's own source for fonts and images, and no host anywhere in it. Only the route id is templated into the HTML shell — everything else is built as DOM with `textContent`. `enableCommandUris` names exactly two workbench commands, both developer affordances, because `true` would let any anchor in the page invoke any command in the editor.

**The persisted view state** (cited as §4.5). `UI_STATE_KEYS` is the only set of workspace-state keys a webview may write, and a key not in that table is refused rather than written. The seven existing keys keep their historical names verbatim; new keys use the `zer0Cms:Dashboard:<Route>:<Name>` family.

**The contribution surface** (cited as §5.1). Commands, settings, context keys, tree views, routes, request operations and MCP tools are the extension's public API, and each count is asserted by a test rather than described here: the command list in the extension-host suite, the setting ids against the manifest in the same suite, the route registry in its own suite, and the MCP tool list in the stdio suite. Adding to any of them means editing the manifest, the code, the count assertion and the documentation together — which is the point of pinning them.
