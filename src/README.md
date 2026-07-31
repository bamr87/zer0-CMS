# `src/` — the extension

Three layers, and the boundary between them is enforced by the build rather than by good intentions.

| Layer | Directories | May import `vscode`? |
|---|---|---|
| **Core** | `core/` | **No.** Pure Node, unit-testable, reused by the MCP server. |
| **MCP** | `mcp/` | **No.** Bundled with an empty `external` list, so a stray import is a build error. |
| **Webview** | `webview/` | **No.** Runs in a browser context; talks to the host over `postMessage`. |
| **Shell** | this directory, `commands/`, `views/`, `panel/`, `dashboard/`, `agent/` | Yes — and only here. |

`eslint.config.mjs` blocks the import; `esbuild.js` turns it into a build failure for the MCP graph. See `core/README.md` for why.

---

## The shell files

| File | What it is |
|---|---|
| `extension.ts` | `activate()` in twelve ordered steps. Wires; never implements. |
| `config.ts` | The only translator between VS Code settings + `zer0.json` and the core's `Zer0Config`. |
| `logger.ts` | An `OutputChannel` wearing the core's `LogSink` face. |
| `store.ts` | `WorkspaceStore` — one `Snapshot` that all four trees and both webviews read. |
| `uiState.ts` | The eight context keys, the status bar item, the notification helpers. |
| `diagnostics.ts` | Required-field diagnostics, drawn inside the front-matter block. |
| `mcpRegistration.ts` | The two-phase MCP server definition provider, plus the `.vscode/mcp.json` fallback. |

Everything above is called by `commands/`, `views/`, `panel/`, `dashboard/` and `agent/`. Nothing above imports them, except `extension.ts`, which imports everything and is imported by nothing.

---

## Five things that are easy to get wrong

### 1. `currentConfig()` is not cached, and `explicit()` is why the three layers work

Every one of the 35 contributed settings declares a default in `package.json`, so `getConfiguration('zer0Cms').get('governance.publishAllow')` returns `false` even for a user who has never opened the settings UI. If the settings layer were built from `get()`, it would always have a value, and `zer0.json` could never win for any key that also has a setting — three layers collapsing into one. `config.ts` therefore reads through `inspect()` and keeps only the values a human actually set (folder → workspace → global scope).

Nothing is cached. `currentConfig()` re-reads the settings and re-parses `zer0.json` on every call. That is what makes "flip `zer0Cms.governance.publishAllow` and the next publish gate sees it" true without a window reload.

### 2. The store coalesces, debounces, and re-arms

- Concurrent `refresh()` calls share one in-flight promise: five callers, one
  scan, one `onDidChange`.
- Watcher events are debounced over 250 ms, because a `git checkout` is a
  hundred events about one thing.
- If the debounce fires while a rebuild is already running, the timer is
**re-armed rather than joined** — the change happened after that rebuild started reading, so joining it would return a snapshot that cannot contain the change.
- Watchers are disposed and rebuilt on a settings change, a `zer0.json` change
or a workspace-folder change. Content folders are configuration, so a config change *is* a watcher change.
- A folderless window installs **zero** watchers and makes **zero** filesystem
  calls; `emptySnapshot()` is a real, renderable `Snapshot`.

### 3. Context keys: eight, and every one gates something

`zer0Cms:enabled`, `:file:isValid`, `:dashboard:open`, `:governance:enabled`, `:contract:present`, `:agent:enabled`, `:agent:running`, `:folder:registered`.

Upstream shipped fourteen, of which five were dead — including the one gating its *initialize project* command, which made that command unreachable in exactly the workspace that needed it. The rule: grep `package.json` for the key before adding one. `uiState.ts` mirrors each key in memory and only calls `setContext` when the value changes, so the active-editor listener can run on every keystroke without flooding the command bus.

### 4. Diagnostics live inside the fences, and SEO is not a diagnostic

`rangeForViolation()` walks the violation's key path segment by segment, narrowing to each parent's children, and clamps the result to the block's content lines. A key that does not exist yet gets the block's first content line — where it would be written. A file with no front matter gets no diagnostics at all: it has not violated a schema, it has not claimed one.

Title length, description length and keyword density are **advice**, and advice belongs in the panel where it can be weighed. Putting it in the Problems panel next to compiler errors is how you train people to ignore the Problems panel.

### 5. The MCP registration is two-phase, and that is the security design

`provideMcpServerDefinitions` is called eagerly and may be cached, so it returns a definition with an **empty `env`** — command, argv, cwd, version, nothing else. `resolveMcpServerDefinition` runs once, at server start, and is the only place the publish flag and any secret are read.

When publishing is off, `ZER0_CMS_MCP_ALLOW_PUBLISH` is set to `null`, which the API defines as *remove this variable from the child's environment*. Not `"0"` (a string something might later read as present) and not merely omitted (which would let an inherited `ZER0_CMS_MCP_ALLOW_PUBLISH=1` in the extension host's own environment leak through). No secret ever appears in a static definition, a setting, `.vscode/mcp.json`, or a log line — the log records that a value was injected, never the value.

---

## Adding a command

1. Declare it in `package.json` under `contributes.commands`, with any `when`
   clause it needs in `contributes.menus`.
2. Implement it in the matching `commands/*.ts`, taking the `Zer0Shell`.
3. Do **not** add a registration to `extension.ts` — the module registers it.

The only two commands `extension.ts` registers itself are `zer0Cms.dashboard` and `zer0Cms.dashboard.close`, because the dashboard panel is a singleton the shell owns and no command module does.

## Adding a privileged action

Re-read decision D5 first. Any action that writes, publishes or approves must route through a function the command palette also calls, and that function must re-read state from disk and re-run `evaluateGates()` before acting. A check performed in a webview is decoration.
