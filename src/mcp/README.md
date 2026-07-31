# `src/mcp` — the bundled MCP server

Two files that expose the CMS as eight tools over stdio, with the governance built into their shapes. Pure Node — see `../core/README.md` for the layering rule, which this directory is the second half of.

| File | Exports | Owner |
|---|---|---|
| `server.ts` | `SERVER_NAME`, `SERVER_VERSION`, `runServer` | WP07 |
| `tools.ts` | `PUBLISH_ENV_VAR`, `CONFIG_ENV_VAR`, `CONTENT_FIELDS`, `ToolArgs`, `ToolSchema`, `ToolDef`, `TOOLS`, `TOOLS_BY_NAME`, `ERROR_PREFIXES`, `isErrorText`, `publishEnabled`, `loadServerConfig` | WP07 |

## Running it

```bash
node dist/mcp-server.js          # cwd is the workspace; nothing else required
ZER0_CMS_MCP_ALLOW_PUBLISH=1 node dist/mcp-server.js   # publishing armed
```

Inside VS Code the extension registers it through `vscode.lm.registerMcpServerDefinitionProvider` (`src/mcpRegistration.ts`), but standing it up by hand — Claude Code, a `.vscode/mcp.json` entry, a shell — is a supported way to run it, and the integration test spawns exactly this file.

## The eight tools, in order

The order in `TOOLS` is the order the test pins, and it is a safety ladder.

| # | Tool | Writes | Notes |
|---|---|---|---|
| 1 | `zer0_status` | — | Config, contract, drafts, ledger, and whether publishing is armed. Start here. |
| 2 | `zer0_list_content` | — | Health / freshness / path. Falls back to a filesystem scan when `.cms/` is absent, and says so. |
| 3 | `zer0_get_content` | — | One page: its record, its issues **by lane**, and a whitelisted subset of its front matter. |
| 4 | `zer0_preview` | — | The **exact** artifact a publish would write, built by the configured target, plus the brand guard. |
| 5 | `zer0_draft` | one queue file | The doctrine-preferred path: the AI drafts, the human approves. Always `status: pending`. |
| 6 | `zer0_publish` | content + ledger | **Double-gated.** Off by default. |
| 7 | `zer0_worklist` | `.cms/distribution/worklists/` | The four catering lanes. |
| 8 | `zer0_contract` | only with `normalize-apply` | Runs the repository's own engine. |

## Contracts worth knowing before you change anything

**stdout is the protocol channel, and the redirect must run first.** The first executable statements in `server.ts` capture `process.stdout.write` and point every `console.*` method at stderr. **Nothing may be imported at module scope** — with a bundler, dependencies evaluate *before* the entry file's body, so a static import would let a module-scope `console.log` three files away emit a line into the JSON-RPC stream before the redirect ever ran. That is not theoretical; it is what esbuild does with `bundle: true`. Everything the server needs is therefore loaded with `await import()` inside `bootstrap()`, and the only other imports in the file are type-only ones, which are erased. The startup banner goes to stderr too. If you add an import to `server.ts`, put it in `bootstrap`.

**`vscode` cannot appear anywhere in this graph.** The MCP esbuild bundle marks *nothing* external, so a stray editor import is a build error — `Could not resolve "vscode"` — rather than a crash inside somebody's MCP client half an hour later. eslint blocks it as well. This is decision D1, enforced twice.

**Handlers return prose, including for failures.** Every tool is `(cfg, args) => Promise<string>` and the string is written for a reader. `ERROR_PREFIXES` (`error:`, `refused:`, `blocked`, `not found`, `publishing is disabled`) is how prose becomes `isError: true` — which is why every refusal in `tools.ts` is written to start with one of them. A new refusal needs a matching prefix or it will be reported as a success.

**`zer0_publish` is gated twice, and each gate refuses on its own.** The environment gate (`ZER0_CMS_MCP_ALLOW_PUBLISH`) and the call gate (`confirm: true`) produce different prose, so a refusal always names the exact thing that has to change. Nothing else in the file may short-circuit either. The environment flag is also folded into `governance.publishAllow` by `loadServerConfig`, so the core publish gate and the MCP gate cannot disagree — one switch, not two. A `zer0.json` claiming `publishAllow: true` still does not let an MCP client publish unless the process was started with the flag — and `src/mcpRegistration.ts` will not start it with the flag on the strength of that file either: the editor reads `zer0Cms.governance.publishAllow` from the settings layer alone when it decides what to inject.

**Configuration is re-read from disk on every tool call.** A long-lived server would otherwise keep gating against a `zer0.json` the author has since edited. Same rule as "the webview is never the gate": a stale snapshot is never the gate either.

**Tool calls are serialised.** JSON-RPC lets a client pipeline requests and `readline` delivers buffered lines all at once; without the queue in `enqueue()`, two `zer0_publish` frames sent back-to-back both read the ledger before either writes it, and publish-exactly-once quietly stops holding. This was an observed failure, not a hypothetical. `initialize`, `ping` and `tools/list` are deliberately *not* queued — they touch nothing and must stay answerable while a slow engine run is in flight.

**An unparseable line is skipped and the loop stays alive.** Clients emit stray output more often than anyone admits, and ending the session over one bad frame loses every pending call with it. A line that parses but is not a JSON object naming a method is dropped the same way.

**A message with no `id` is a notification** (`'id' in msg`, checked on the raw object) and gets no response — `notifications/initialized`, `notifications/cancelled`. `initialize` is answered before that check, because it always carries an id and answering it is the whole handshake.

**A tool that throws never kills the server.** The exception is caught in `callTool` and returned as `{ content: [{ type: 'text', text: 'tool error: …' }], isError: true }`. The next call still works. Error codes: `-32601` unknown method, `-32602` unknown tool, `-32603` an exception escaping `handle` (only when the message had an id).

**`zer0_get_content` whitelists front-matter keys.** `CONTENT_FIELDS` is an allow-list, not a block-list, for the same reason the LinkedIn port whitelisted its response fields: front matter is arbitrary user data and "everything except the keys we thought of" is not a boundary. Keys outside the list are reported by name only — the model learns they exist without learning their values.

**`initialize` echoes the client's protocol version** when it is one of `2024-11-05`, `2025-03-26`, `2025-06-18`; otherwise ours (`2025-06-18`) wins.

## Tests

`src/test/mcp.test.ts` spawns `dist/mcp-server.js` — the **shipped bundle**, not the sources — with an environment scrubbed of every `ZER0_*` and `ANTHROPIC_*` variable, and asserts: every stdout line parses as JSON, the banner is on stderr, the protocol version is echoed, exactly these eight tool names in this order, `zer0_preview` returns the artifact with `isError: false`, a raw garbage line does not kill the loop (`ping` still answers `{}` afterwards), `zer0_publish` while disabled returns `isError: true` starting with `publishing is disabled`, and an unknown method yields `-32601`.
