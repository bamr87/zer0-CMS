# `src/mcp` — the bundled MCP server

Three files that expose the CMS as sixteen tools over stdio, with the governance built into their shapes. Pure Node — see `../core/README.md` for the layering rule, which this directory is the second half of.

| File | Exports | Owner |
|---|---|---|
| `server.ts` | `SERVER_NAME`, `SERVER_VERSION`, `runServer` | WP07 |
| `tools.ts` | `PUBLISH_ENV_VAR`, `EXEC_ENV_VAR`, `SCAFFOLD_ENV_VAR`, `PYTHON_ENV_VAR`, `CONFIG_ENV_VAR`, `CONTENT_FIELDS`, `ToolArgs`, `ToolSchema`, `ToolDef`, `TOOLS`, `TOOLS_BY_NAME`, `ERROR_PREFIXES`, `isErrorText`, `publishEnabled`, `execEnabled`, `scaffoldEnabled`, `loadServerConfig` | WP07, WP1.3, WP2.5, WP4.3 |
| `cache.ts` | `loadContractCached`, `clearIndexCaches`, `cachedRootCount` | WP1.3 |

## Running it

```bash
node dist/mcp-server.js          # cwd is the workspace; nothing else required
ZER0_CMS_MCP_ALLOW_PUBLISH=1 node dist/mcp-server.js   # publishing armed
ZER0_CMS_MCP_ALLOW_EXEC=1 node dist/mcp-server.js      # zer0_contract may spawn
ZER0_CMS_MCP_ALLOW_SCAFFOLD=1 node dist/mcp-server.js  # zer0_lane_scaffold may write a lane
```

## The five environment variables

| Variable | Set by | Absent means |
|---|---|---|
| `ZER0_CMS_CONFIG` | the extension, always | `zer0.json` |
| `ZER0_CMS_MCP_ALLOW_PUBLISH` | the extension, from the **settings** layer | `zer0_publish` refuses |
| `ZER0_CMS_MCP_ALLOW_EXEC` | the extension, only in a **trusted** workspace | `zer0_contract` refuses |
| `ZER0_CMS_MCP_ALLOW_SCAFFOLD` | the extension, from the **settings** layer, in a **trusted** workspace, and only when `zer0Cms.fleet.enabled` is on for that folder | `zer0_lane_scaffold` refuses |
| `ZER0_CMS_PYTHON` | the extension, from the **settings** layer | the interpreter comes from the project layers |

None of them is ever `"0"`: `src/mcpRegistration.ts` sets a variable to `null`, which the VS Code API defines as *remove it from the child's environment*, so an inherited value in the extension host cannot leak into a server that is not allowed to use it. And none of them is written into `.vscode/mcp.json` — a file committed to a repository is the last place any of these belong, which is why a hand-started server reads and drafts but neither publishes nor spawns.

Inside VS Code the extension registers it through `vscode.lm.registerMcpServerDefinitionProvider` (`src/mcpRegistration.ts`), but standing it up by hand — Claude Code, a `.vscode/mcp.json` entry, a shell — is a supported way to run it, and the integration test spawns exactly this file.

## The sixteen tools, in order

The order in `TOOLS` is the order the test pins, and it is a safety ladder.

Tools 8–10 are the feedback loop, and they sit *after* `zer0_publish` because that is the order the work happens in: publish, read back what happened, decide what is next. `zer0_ingest` is the only one of the three that writes, and it writes aggregates into `.cms/`, never content.

| # | Tool | Writes | Notes |
|---|---|---|---|
| 1 | `zer0_status` | — | Config, contract, drafts, ledger, and whether publishing is armed. Start here. |
| 2 | `zer0_list_content` | — | Health / freshness / path. Falls back to a filesystem scan when `.cms/` is absent, and says so. |
| 3 | `zer0_get_content` | — | One page: its record, its issues **by lane**, and a whitelisted subset of its front matter. |
| 4 | `zer0_preview` | — | The **exact** artifact a publish would write, built by the configured target, plus the brand guard. |
| 5 | `zer0_draft` | one queue file | The doctrine-preferred path: the AI drafts, the human approves. Always `status: pending`. |
| 6 | `zer0_publish` | content + ledger | **Double-gated.** Off by default. |
| 7 | `zer0_worklist` | `.cms/distribution/worklists/` | The four catering lanes. |
| 8 | `zer0_ingest` | `.cms/distribution/performance.json` | Joins a platform's statistics onto content paths through the ledger — the input the worklist ranks on. Aggregate counts only. |
| 9 | `zer0_portfolio` | — | The published track record. Reads the ledger, so it works before any statistics exist. |
| 10 | `zer0_media` | — | Which pages have a preview image, and the generator command for each that does not. |
| 11 | `zer0_contract` | only with `normalize-apply` | Runs the repository's own engine. **Gated on `ZER0_CMS_MCP_ALLOW_EXEC`** — see below. |
| 12 | `zer0_fleet_status` | — | This repository's AI lanes as its local `fleet.manifest.yml` declares them. Reads the file only — **no network from this process** — so the switch state is reported as unknown; the dashboard reads it, behind a person's sign-in. |
| 13 | `zer0_audit` | — | Every page's front matter against the site's own schema, grouped by rule, with the change set that would repair each fixable finding **described and never applied**. |
| 14 | `zer0_harness_inventory` | — | This repository's whole AI harness, joined: roles, routines, workflows by runner shape, manifest lanes, switches, token **names**, the usage ledger, and every place two of those files disagree. Local files only. |
| 15 | `zer0_lane_preview` | — | Exactly what generating a new lane would write — workflow, agent, skill stub, manifest entry — rendered and returned. Same planner as the write. |
| 16 | `zer0_lane_scaffold` | 3–4 files | **Double-gated.** Off by default. Writes a lane's files; creates **no** repository variable. |

## The harness trio (14–16)

`zer0_harness_inventory` reads seven kinds of artefact — the manifest, the workflows, the agents, the skills, `_data/ai.yml`, the shared quarantine doc and the usage ledger — and reports the join plus the disagreements. Over lifehacker.dev that is 17 lanes, 26 workflows, 19 agents, 16 skills and 13 findings, twelve of which are the token-presence chains that repository's own `lint_tokens.rb` already lists as migrating. `section` and `limit` narrow it, because a model reading 26 workflows in full is a model reading a lot of YAML to answer one question. Switch **values** are absent and named as absent: they live in the repository's Actions variables, and only the editor's dashboard reads those, behind a person's sign-in. Token and secret names are shown; no value is ever read.

`zer0_lane_preview` renders every byte a scaffold would write, through the same `planScaffold` the write calls — which is what makes "the preview showed me something else" impossible rather than unlikely. It passes **no** `ctx.audit`: `src/core/harness/selfAudit.ts` imports `@bamr87/fleet-engines`, this bundle allows no bare import at all, and esbuild resolves the whole graph before it tree-shakes, so "the server never calls it" would not be a defence — reachability is. eslint bans that path from `src/mcp/**` for the same reason. The consequence is stated in the answer rather than hidden: what the preview carries is the house preflight, and the editor additionally runs the fleet's fifteen-rule workflow audit over the same files.

`zer0_lane_scaffold` is **the only write in this directory that is not content**, and it is gated three times, each refusing on its own with its own prose:

1. `ZER0_CMS_MCP_ALLOW_SCAFFOLD` in the environment — the publish flag's
reasoning pointed at the working tree, because on the other side of it is a *workflow file*. A `zer0.json` that arrived with a clone must not be able to arm the thing that writes the repository's next workflow, so the editor reads `zer0Cms.fleet.scaffoldAllow` from the settings layer alone and injects the flag only in a trusted workspace and only when the fleet console is enabled for that folder. That single bit therefore answers both settings-layer questions, which is why the tool passes `enabled: true` and `scaffoldAllow: true` into the gate rather than re-asking across a process boundary it cannot see over — refusal happens at gate one, in better words than the gate's.
2. `confirm: true` in the call.
3. `evaluateFleetGates('scaffold', …)` — the five blockers that decide whether
*this* lane may land here: a lane id the manifest already declares, a file already at that path, a variable another lane claims, and a lane the shared runner cannot express. Plus the house preflight: an `error`- or `fail`-severity finding blocks the write and names itself, which is how **a lane with no kill switch is never generated**.

`force` overrides exactly one refusal — "a file is already there" — and nothing else: not the environment flag, not `confirm`, not a duplicate lane id, not a failing preflight, and never a `factory--*` path or anything resolving outside the workspace root. It exists for the reason `publishPreview`'s does, and the parallel holds at the other end too: the editor's own `lane.scaffold` has no `force` at all, because nothing reachable from a keystroke passes one. Files are written with the exclusive `wx` flag unless `force` is set, and the manifest — the one file rewritten rather than created — is re-read and compared with the bytes the plan was built from before it is touched.

**It creates no repository variable, and it could not.** The lane it writes is inert until a person makes its `*_ENABLED` variable themselves; this process opens no socket, so there is no path from here to one. The answer says so every time, and so does the refusal when no switch was declared at all.

## Contracts worth knowing before you change anything

**stdout is the protocol channel, and the redirect must run first.** The first executable statements in `server.ts` capture `process.stdout.write` and point every `console.*` method at stderr. **Nothing may be imported at module scope** — with a bundler, dependencies evaluate *before* the entry file's body, so a static import would let a module-scope `console.log` three files away emit a line into the JSON-RPC stream before the redirect ever ran. That is not theoretical; it is what esbuild does with `bundle: true`. Everything the server needs is therefore loaded with `await import()` inside `bootstrap()`, and the only other imports in the file are type-only ones, which are erased. The startup banner goes to stderr too. If you add an import to `server.ts`, put it in `bootstrap`.

**`vscode` cannot appear anywhere in this graph.** The MCP esbuild bundle marks *nothing* external, so a stray editor import is a build error — `Could not resolve "vscode"` — rather than a crash inside somebody's MCP client half an hour later. eslint blocks it as well. This is decision D1, enforced twice.

**Handlers return prose, including for failures.** Every tool is `(cfg, args) => Promise<string>` and the string is written for a reader. `ERROR_PREFIXES` (`error:`, `refused:`, `blocked`, `not found`, `publishing is disabled`, `engine execution is disabled`, `scaffolding is disabled`) is how prose becomes `isError: true` — which is why every refusal in `tools.ts` is written to start with one of them. A new refusal needs a matching prefix or it will be reported as a success.

**`zer0_publish` is gated twice, and each gate refuses on its own.** The environment gate (`ZER0_CMS_MCP_ALLOW_PUBLISH`) and the call gate (`confirm: true`) produce different prose, so a refusal always names the exact thing that has to change. Nothing else in the file may short-circuit either. The environment flag is also folded into `governance.publishAllow` by `loadServerConfig`, so the core publish gate and the MCP gate cannot disagree — one switch, not two. A `zer0.json` claiming `publishAllow: true` still does not let an MCP client publish unless the process was started with the flag — and `src/mcpRegistration.ts` will not start it with the flag on the strength of that file either: the editor reads `zer0Cms.governance.publishAllow` from the settings layer alone when it decides what to inject.

**`zer0_contract` is the one tool that starts a process, and Workspace Trust is what decides.** This process cannot ask `vscode` anything, so the editor tells it: `ZER0_CMS_MCP_ALLOW_EXEC=1`, injected at resolve time and only when `vscode.workspace.isTrusted` (decision D13). Absent, the tool refuses with prose starting `engine execution is disabled` — which is in `ERROR_PREFIXES`, so it is reported as `isError: true` like every other refusal here. The practical effect is the one worth stating: **a server started by hand, or from a committed `.vscode/mcp.json`, spawns nothing at all**, because neither gets an `env`. In an untrusted workspace the editor does not even offer the server — `provideMcpServerDefinitions` returns `[]`.

**`ZER0_CMS_PYTHON` pins the interpreter to the settings layer**, exactly as `ZER0_CMS_MCP_ALLOW_PUBLISH` pins the publish gate. A `zer0.json` arrives with the clone and can name any binary on the machine; which binary runs is not its decision. The *script* is fenced separately and always: `evaluateExecGate` in `src/core/shared/trust.ts` refuses a path that resolves outside the workspace root whichever layer supplied it, and `src/core/contract/engine.ts` gives any run ten minutes before it kills it.

**Eight of the sixteen tools begin with a page-index scan, so the scan is cached for the life of the process.** `src/mcp/cache.ts` holds one `IndexCache` per workspace root and hands it back into `loadContractOrScan(cfg, log, cache)`; with no `.cms/` contract present — the common case, and a normal state — that turns a 44–123 ms full walk into a 7–22 ms `stat`-per-candidate. It stays correct without a timer because `buildIndex` invalidates itself: entries are keyed by mtime, and `IndexCache.fingerprint` covers a configuration change that alters the projection while every mtime stays put. The map lives in `cache.ts` alone so `tools.ts` has exactly one owner for it, and it is never written to disk — the *extension* persists its own in `workspaceState`, this one dies with the process.

**Configuration is re-read from disk on every tool call.** A long-lived server would otherwise keep gating against a `zer0.json` the author has since edited. Same rule as "the webview is never the gate": a stale snapshot is never the gate either.

**Tool calls are serialised.** JSON-RPC lets a client pipeline requests and `readline` delivers buffered lines all at once; without the queue in `enqueue()`, two `zer0_publish` frames sent back-to-back both read the ledger before either writes it, and publish-exactly-once quietly stops holding. This was an observed failure, not a hypothetical. `initialize`, `ping` and `tools/list` are deliberately *not* queued — they touch nothing and must stay answerable while a slow engine run is in flight.

**An unparseable line is skipped and the loop stays alive.** Clients emit stray output more often than anyone admits, and ending the session over one bad frame loses every pending call with it. A line that parses but is not a JSON object naming a method is dropped the same way.

**A message with no `id` is a notification** (`'id' in msg`, checked on the raw object) and gets no response — `notifications/initialized`, `notifications/cancelled`. `initialize` is answered before that check, because it always carries an id and answering it is the whole handshake.

**A tool that throws never kills the server.** The exception is caught in `callTool` and returned as `{ content: [{ type: 'text', text: 'tool error: …' }], isError: true }`. The next call still works. Error codes: `-32601` unknown method, `-32602` unknown tool, `-32603` an exception escaping `handle` (only when the message had an id).

**`zer0_audit` describes a fix and never applies one.** It is the read-only half of a pair: this tool says what is missing, malformed or duplicated and what change set `fixFor` would propose; the *editor's* `audit.fix` is the half that writes, and it re-reads the configuration, re-reads the site from disk, re-runs `auditPage`, renders a diff and asks a person before it does (decision D5). Nothing in this handler opens a file for writing, spawns anything or touches the network — the change sets it prints are computed by reading the article and are discarded with the answer.

**`zer0_audit` fills in the content folders it was not given.** A sister site that has never been opened in the editor has no `zer0.json` and therefore no `contentFolders`, and a scan over zero folders would honestly report zero findings about 382 files. So the handler detects the platform and applies `withPlatformDefaults`, which fills the *gap* only: a workspace that registered its own folders keeps every one of them. Measured against lifehacker.dev: 382 files, 0 errors, 2 warnings, about 120 ms including the second pass that reads every block for line numbers.

**`zer0_audit` says which schema answered, in words.** "Required" means something different when `frontmatter_schema.yml` said so, when the `.cms/` contract said so, and when nothing said so and the platform profile's own defaults filled in. A model reading `missing-key: layout` needs to know which of those it is looking at before it decides how much authority the finding carries, so the tool prints the source and a sentence about it rather than leaving the distinction to be inferred.

**It is the only tool that does not go through `src/mcp/cache.ts`.** The audit needs `PageEntry` values, not the `ContentRecord` projection `loadContractOrScan` returns, so it calls `buildIndex` itself with no cache — one full walk per call. That is a deliberate trade for a tool nobody calls in a loop; if it ever becomes hot, the fix is a second entry point in `cache.ts`, not a cache in this file.

**`zer0_get_content` whitelists front-matter keys.** `CONTENT_FIELDS` is an allow-list, not a block-list, for the same reason the LinkedIn port whitelisted its response fields: front matter is arbitrary user data and "everything except the keys we thought of" is not a boundary. Keys outside the list are reported by name only — the model learns they exist without learning their values.

**`initialize` echoes the client's protocol version** when it is one of `2024-11-05`, `2025-03-26`, `2025-06-18`; otherwise ours (`2025-06-18`) wins.

## Tests

`src/test/mcp.test.ts` spawns `dist/mcp-server.js` — the **shipped bundle**, not the sources — with an environment scrubbed of every `ZER0_*` and `ANTHROPIC_*` variable, and asserts: every stdout line parses as JSON, the banner is on stderr, the protocol version is echoed, exactly these sixteen tool names in this order, `zer0_preview` returns the artifact with `isError: false`, a raw garbage line does not kill the loop (`ping` still answers `{}` afterwards), `zer0_publish` while disabled returns `isError: true` starting with `publishing is disabled`, and an unknown method yields `-32601`.
