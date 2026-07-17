# `src/zer0/` — the zer0-CMS AI layer

These modules are the AI-augmentation grafted onto Front Matter. They were salvaged from the standalone prototype and **decoupled from any specific UI** so they can wire into Front Matter's own panels/commands.

| File | Role | Dependencies |
|---|---|---|
| `cms-contract.ts` | Reads the `.cms/` contract IT-Journey emits (content index, summary, schema) and runs the engine (`scripts/cms/cms.py`) + the mechanical normalizer. Pure `vscode` + node. | none new |
| `agent.ts` | Runs the `cms-curator` Claude Code skill via `@anthropic-ai/claude-agent-sdk` `query()`. Routes mutating tools through an `AgentReporter` for approve/deny. Loads the SDK via dynamic `import()` (ESM-safe), so it isn't webpack-bundled. | `@anthropic-ai/claude-agent-sdk` (runtime) |

## How it plugs into Front Matter

Nothing here is wired into Front Matter's `activate()` yet — that's the next phase. The intended integration points (all using FM's existing infrastructure):

1. **Commands** — register `zer0Cms.curateFile` / `zer0Cms.curateWorklist` /
`zer0Cms.runMechanical` alongside Front Matter's `frontMatter.*` commands (in `src/commands` registration), surfaced in the dashboard/panel.
2. **`AgentReporter`** — implement against Front Matter's **panel webview**
(`src/panelWebView`) or a dedicated webview view, so the agent transcript and the approve/deny diff cards render inside FM's UI. (The prototype implemented this interface with a standalone webview — see the it-journey repo history.)
3. **Content health** — surface `cms-contract`'s per-file health/issues as a
column/section in FM's **Contents dashboard** (`src/dashboardWebView`), reusing FM's content-type + folder model rather than a parallel tree.
4. **Schema reuse** — FM already reads `frontmatter.json`; `cms-contract`'s schema
loader (`.cms/schema/content-schema.json`) is derived from the same source, so the two agree.

## Auth (for the agent commands)

The agent needs a Claude credential the SDK can reach: be logged in with `claude` (Claude Code) or set `ANTHROPIC_API_KEY`. Without it, the agent reports a clear error and the rest of the CMS still works.

## Why decoupled

`agent.ts` depends only on the `AgentReporter` interface, not on a concrete webview, so the same agent logic runs whether driven by Front Matter's panel, a tree view, or a plain output channel. This keeps the AI layer independent of upstream UI churn when merging Front Matter updates.
