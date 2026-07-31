# `src/agent/` — the optional AI layer

Two files, one capability, and it is **off by default**.

| File | What it is |
|---|---|
| `agent.ts` | `CmsAgent` — loads the Claude Agent SDK, runs one pass, and routes every mutating tool call through a human. Imports `vscode` only for a warning, a notification and the extension path. |
| `agentPanel.ts` | The `AgentReporter` implementation as a `WebviewPanel`: transcript, status, approval cards, composer. Front end in `src/webview/agent/main.ts`. |

## The four properties that matter

1. **`zer0Cms.agent.enabled` defaults to `false`, and the check happens before
   the module loader.** With the flag off, `CmsAgent.run()` appends one system
   line, offers to open the setting, and returns. No dynamic import is
   attempted, so a user who never turns the agent on never pays for it — not in
   load time, not in memory, not in supply-chain surface.
2. **`@anthropic-ai/claude-agent-sdk` is an `optionalDependency`, never a
   `dependency`.** It is `external` in the esbuild bundle and reached through
   `new Function("m", "return import(m)")`, because esbuild does not rewrite
   `new Function` bodies and TypeScript's CommonJS emit would otherwise downlevel
   `import()` to `require()` — which cannot load an ESM-only package. Both the
   rejected import *and* a module without a `query` export are caught, and the
   message names **this** extension's installation root with a `npm install`
   suggestion.
3. **`canUseTool` is the only gate.** `READ_ONLY_TOOLS` — `Read`, `Grep`,
   `Glob`, `LS`, `TodoWrite`, `NotebookRead` — is auto-allowed. Everything else,
   including every tool a future SDK version introduces, fails closed through
   `requestApproval`, and a refusal returns `{ behavior: 'deny', message }` so
   the model learns why and can propose something else.
4. **`allowedTools` is not passed to `query()`.** This is decision D10 and it is
   the single most important line *not* in `agent.ts`. The salvaged original
   passed both `allowedTools: ['Read','Grep','Glob','LS']` and a `canUseTool`
   whose read-only set also contained `TodoWrite` and `NotebookRead`. Two
   overlapping permission mechanisms that disagree is a bug whichever one wins,
   and the SDK's own documentation is explicit that a tool matched by an allow
   rule **never reaches `canUseTool`** — so keeping `allowedTools` would silently
   bypass the gate for exactly the tools it lists.

## What changed from the salvaged `src/zer0/agent.ts`

`agent.ts`'s header comment carries the full table. In short: `allowedTools`
removed (D10); `describeTool('Bash', …)` summarises the actual command instead
of the constant string `"shell command"`; `render()`'s empty `catch {}` replaced
by an `error` transcript line; `any` removed from the public surface and the SDK
narrowed from `unknown` at the boundary; configuration taken as a typed
`Zer0Config['agent']` instead of read from an `itjCms.*` settings section that
was never declared in any manifest; and the load-failure message no longer names
`tools/cms-extension`, a directory that does not exist in this repository.

The `cms-curator` Claude Code skill the original depended on is also gone — it
lived in an unrelated workspace and was never shipped here. Its guidance is now
an `append` on the `claude_code` system-prompt preset: work the governed queue,
never self-approve or self-publish, never touch git.

## The wiring

```
src/commands/agent.ts   ──▶  AgentPanel.open() / .start(prompt) / .stop()
                                   │  implements AgentReporter
                                   ▼
                              CmsAgent.run(prompt)
                                   │  canUseTool
                                   ▼
                        AgentReporter.requestApproval(card)  ──▶  webview
```

`AgentPanel` is constructed with the `Zer0Shell` from `activate()`, the same
shape `DashboardPanel` takes:

```ts
const agentPanel = new AgentPanel(shell);
agentPanel.open();                  // zer0Cms.agent.open
await agentPanel.start(prompt);     // zer0Cms.agent.start
agentPanel.stop();                  // zer0Cms.agent.stop
agentPanel.running;                 // drives zer0Cms:agent:running
```

A fresh `CmsAgent` is built on every `start()` from `currentConfig().agent`, so
a settings change takes effect on the next run with no reload. The webview can
name `agent.send` / `agent.stop` / `agent.approve` / `agent.deny`, and nothing
else: inbound `command` messages are looked up in a `Record<CommandId, Handler>`
and an id with no handler is logged and dropped.

## Approvals never time out

`requestApproval()` parks a promise and resolves it only when the user answers,
`stop()` is called, or the panel is disposed. A timeout would deny a decision
someone was still making, and the SDK is happy to hold a tool call open
indefinitely. The corollary is that both teardown paths **must** resolve every
pending promise as `false` — `denyAllPending()` — or the SDK's `canUseTool` await
leaks and the run never unwinds. That is why `stop()` does two things, not one.

## Authentication

There is none here, deliberately. The SDK resolves credentials itself from an
active `claude` login or `ANTHROPIC_API_KEY`. This extension stores no token,
reads no secret, and adds nothing to `SecretStorage` for the agent.

## Styling

`src/webview/agent/main.ts` loads `media/{tokens,base,panel}.css` and adds its
own layout in a nonce'd `<style>` block inside `agentHtml()`. That block names
`--z-*` tokens only — `media/tokens.css` remains the one file in the repository
that knows a VS Code theme variable's name. It lives in `agentPanel.ts` rather
than in `media/` because the agent panel is the one surface that may be entirely
absent from a session, and keeping its ~40 rules out of the shared sheets means
the panel and dashboard do not carry them.
