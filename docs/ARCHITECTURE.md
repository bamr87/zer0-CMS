# Architecture

zer0-CMS is a VS Code extension with a hard internal boundary. This document explains where the boundary is, why it is there, and what it buys.

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

## Where the AI lives

Two separate, independently-disableable surfaces:

- **The MCP server** (`src/mcp/`) — eleven tools for any MCP client. The doctrine-preferred path is `zer0_draft`: the model writes a draft, a person approves it. `zer0_publish` needs an environment flag *and* a per-call confirmation.
- **The agent** (`src/agent/`) — the Claude Agent SDK, loaded through a dynamic import so it is never bundled, gated on a setting that defaults to off, and absent from the dependency tree unless you ask for it. Read-only tools run freely; every mutating tool goes through an approve/deny card showing the diff.

Neither is required to use the CMS, and neither can publish without walking through the same gate a human command does.
