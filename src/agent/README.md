# `src/agent/` — the optional AI layer

Two files, one capability, and it is **off by default**.

| File | What it is |
|---|---|
| `agent.ts` | `CmsAgent` — loads the Claude Agent SDK, runs one pass, and routes every mutating tool call through a human. Imports `vscode` only for a warning, a notification and the extension path. |
| `agentPanel.ts` | The `AgentReporter` implementation as a `WebviewPanel`: transcript, status, approval cards, composer. Front end in `src/webview/agent/main.ts`. |

## The five properties that matter

1. **`zer0Cms.agent.enabled` defaults to `false`, and the check happens before
the module loader.** With the flag off, `CmsAgent.run()` appends one system line, offers to open the setting, and returns. No dynamic import is attempted, so a user who never turns the agent on never pays for it — not in load time, not in memory, not in supply-chain surface.
2. **`@anthropic-ai/claude-agent-sdk` is an `optionalDependency`, never a
`dependency`.** It is `external` in the esbuild bundle and reached through `new Function("m", "return import(m)")`, because esbuild does not rewrite `new Function` bodies and TypeScript's CommonJS emit would otherwise downlevel `import()` to `require()` — which cannot load an ESM-only package. Both the rejected import *and* a module without a `query` export are caught, and the message names **this** extension's installation root with a `npm install` suggestion.
3. **`canUseTool` is the only gate.** `READ_ONLY_TOOLS` — `Read`, `Grep`,
`Glob`, `LS`, `TodoWrite`, `NotebookRead` — is auto-allowed. Everything else, including every tool a future SDK version introduces, fails closed through `requestApproval`, and a refusal returns `{ behavior: 'deny', message }` so the model learns why and can propose something else.
4. **`allowedTools` is not passed to `query()`.** This is decision D10 and it is
the single most important line *not* in `agent.ts`. The salvaged original passed both `allowedTools: ['Read','Grep','Glob','LS']` and a `canUseTool` whose read-only set also contained `TodoWrite` and `NotebookRead`. Two overlapping permission mechanisms that disagree is a bug whichever one wins, and the SDK's own documentation is explicit that a tool matched by an allow rule **never reaches `canUseTool`** — so keeping `allowedTools` would silently bypass the gate for exactly the tools it lists. A tool allow-list negotiated at session start cannot show a person the diff it is about to write; the card can.
5. **Workspace Trust is the outer gate, and it is asked twice.** The agent is
the fifth execution vector (decision D13): it edits files and runs commands inside the user's repository. `readyHost()` in `src/commands/agent.ts` checks `workspaceTrusted()` *before* it checks `agent.enabled`, because an untrusted folder is not a settings problem and "Enable it" would be the wrong sentence. `AgentPanel.start()` checks again, because the panel's composer posts `agent.send` straight into the handler table and never passes through a command. The surface is the courtesy; the function is the gate.

## What changed from the salvaged `src/zer0/agent.ts`

`agent.ts`'s header comment carries the full table. In short: `allowedTools` removed (D10); `describeTool('Bash', …)` summarises the actual command instead of the constant string `"shell command"`; `render()`'s empty `catch {}` replaced by an `error` transcript line; `any` removed from the public surface and the SDK narrowed from `unknown` at the boundary; configuration taken as a typed `Zer0Config['agent']` instead of read from an `itjCms.*` settings section that was never declared in any manifest; and the load-failure message no longer names `tools/cms-extension`, a directory that does not exist in this repository.

The `cms-curator` Claude Code skill the original depended on is also gone — it lived in an unrelated workspace and was never shipped here. Its guidance is now an `append` on the `claude_code` system-prompt preset: work the governed queue, never self-approve or self-publish, never touch git.

## What `QueryOptions` declares but does not yet set

`agent.ts`'s `QueryOptions` is the subset of the SDK's `Options` this extension touches, and it carries eight optional fields nothing sets today: `agent`, `agents`, `mcpServers`, `strictMcpConfig`, `settingSources`, `env`, `fallbackModel`, `maxBudgetUsd`. They are declared now because the point of this layer is that a run in the editor and a run in CI are the same run described twice, and the way that stays true is for the option and its command-line counterpart to sit side by side — each one's comment names the `claude` CLI flag (`--agent`, `--agents`, `--mcp-config`, `--strict-mcp-config`, `--setting-sources`, `--max-budget-usd`) that the hub's `claude-run` action and its `ai-lane.yml` inputs use for the same thing.

Two of them are shaped to prevent a mistake rather than to allow a value. `strictMcpConfig` is typed `true`, not `boolean`: the point is that *only* the servers named in `mcpServers` are attached, so a `.mcp.json` in a cloned repository cannot add one, and a field that can hold `false` is a field somebody eventually sets to `false`. `settingSources` is `[]` until both a trusted workspace and a person's per-run opt-in say otherwise, because `.claude/settings.json` is another file that arrives with the checkout and it can name hooks.

`MCP_READ_ONLY_TOOLS` is the seven `mcp__zer0-cms__*` names that never write — `zer0_status`, `zer0_list_content`, `zer0_get_content`, `zer0_preview`, `zer0_portfolio`, `zer0_media`, `zer0_fleet_status`. The five that are absent all write: a queue file, content plus the ledger, two things under `.cms/`, and the repository's own engine. It is a **list, not an allow-rule**: it is folded into `READ_ONLY_TOOLS` where the agent attaches the server, so those seven skip the card the way `Read` does, and it is never handed to the SDK as `allowedTools`.

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

**The constructor is what makes those four commands work.** Until it pushed `setAgentHost(this)`, nothing in `src/` ever installed a host and all four `zer0Cms.agent.*` commands ended at *"the AI agent panel is not available in this window"* — this section documented wiring that did not exist. The registration lives in a `registered` list rather than in `disposables`, because `disposables` is emptied by `teardown()` when the **webview** closes, and a closed webview must not uninstall the host that `agent.open` uses to bring it back. Only `dispose()` empties `registered`, and `setAgentHost` returns a disposable that unhooks only if this host is still the installed one.

`AgentPanel` is constructed with the `Zer0Shell` from `activate()`, the same shape `DashboardPanel` takes — `src/extension.ts` does it once, at step 8, and pushes the panel into `context.subscriptions`:

```ts
const agentPanel = new AgentPanel(shell);
agentPanel.open();                  // zer0Cms.agent.open
await agentPanel.start(prompt);     // zer0Cms.agent.start
agentPanel.stop();                  // zer0Cms.agent.stop
agentPanel.running;                 // drives zer0Cms:agent:running
```

A fresh `CmsAgent` is built on every `start()` from `currentConfig().agent`, so a settings change takes effect on the next run with no reload. The webview can name `agent.send` / `agent.stop` / `agent.approve` / `agent.deny`, and nothing else: inbound `command` messages are looked up in a `Record<CommandId, Handler>` and an id with no handler is logged and dropped.

## Approvals never time out

`requestApproval()` parks a promise and resolves it only when the user answers, `stop()` is called, or the panel is disposed. A timeout would deny a decision someone was still making, and the SDK is happy to hold a tool call open indefinitely. The corollary is that both teardown paths **must** resolve every pending promise as `false` — `denyAllPending()` — or the SDK's `canUseTool` await leaks and the run never unwinds. That is why `stop()` does two things, not one.

## Authentication

There is none here, deliberately. The SDK resolves credentials itself from an active `claude` login or `ANTHROPIC_API_KEY`. This extension stores no token, reads no secret, and adds nothing to `SecretStorage` for the agent.

## Styling

`agentHtml()` links `media/{tokens,base,panel}.css` and adds **nothing of its own**. There used to be about forty rules inlined in a nonce'd `<style>` block here, which made the agent panel's appearance the one part of this extension's styling that lived in a TypeScript string literal: invisible to the styling test, unreachable from the shared sheets, and re-parsed on every page render. They now live in `media/base.css` beside the widget kernel.

The class names this panel expects are the `z-agent__*` family that `src/webview/agent/main.ts` builds — `bar`, `spacer`, `status` (with `is-running`), `notice`, `log`, `line` (with the six `--user` / `--assistant` / `--tool` / `--system` / `--result` / `--error` modifiers), `gutter`, `role`, `text`, `card` (with `card__head`, `card__tool`, `card__summary`, `card__actions`), `diff` (with `is-add`, `is-del`, `is-meta`), `composer` (with `composer__row`) and `hint` — plus the `#z-agent` column itself. Every one of them names `--z-*` tokens only: `media/tokens.css` stays the single file in the repository that knows a VS Code theme variable's name.
