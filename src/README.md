# `src/` — the extension

Three layers, and the boundary between them is enforced by the build rather than by good intentions.

| Layer | Directories | May import `vscode`? |
|---|---|---|
| **Core** | `core/` | **No.** Pure Node, unit-testable, reused by the MCP server. |
| **MCP** | `mcp/` | **No.** Bundled with an empty `external` list, so a stray import is a build error. |
| **Webview** | `webview/` (file mode); `../web/packages/` (platform mode, built into `dist/studio.js`) | **No.** Runs in a browser context; talks to the host over `postMessage`. |
| **Shell** | this directory, `commands/`, `views/`, `panel/`, `dashboard/`, `agent/`, `studio/` | Yes — and only here. |

`eslint.config.mjs` blocks the import; `esbuild.js` turns it into a build failure for the MCP graph. See `core/README.md` for why.

---

## The shell files

| File | What it is |
|---|---|
| `extension.ts` | `activate()` in twelve ordered steps. Wires; never implements. |
| `config.ts` | The only translator between VS Code settings + `zer0.json` and the core's `Zer0Config`. |
| `logger.ts` | An `OutputChannel` wearing the core's `LogSink` face. |
| `store.ts` | `WorkspaceStore` — one `Snapshot` per site, read by the trees and both webviews. |
| `sites.ts` | `SiteRegistry` — one store per open folder, which one is active, the resolver `config.ts` asks, and the Sites view model. |
| `siteRule.ts` | `resolveActiveSite` — the active-site rule, pure, so the fast suite can test it. |
| `uiState.ts` | The eleven context keys, the status bar item, the notification helpers. |
| `diagnostics.ts` | Required-field diagnostics, drawn inside the front-matter block. |
| `mcpRegistration.ts` | The two-phase MCP server definition provider, plus the `.vscode/mcp.json` fallback. |
| `studio/studio.ts` | Platform mode (PLAN G10): the studio's workspaces in the dashboard panel, the Metadata view and the AI panel — the page each loads (`core/studio/page.ts`), one `StudioBridge` per webview (`core/studio/bridge.ts`), the open file's path for the page view, the person's token in SecretStorage per platform origin, event streams with the token as a header. Nothing per workspace: `@zer0/ui`'s `WORKSPACES` decides what the dashboard shows. |

Everything above is called by `commands/`, `views/`, `panel/`, `dashboard/` and `agent/`. Nothing above imports them, except `extension.ts`, which imports everything and is imported by nothing.

---

## Six things that are easy to get wrong

### 1. `currentConfig()` is not cached, `explicit()` is why the three layers work, and the scope is the site

Every one of the 44 contributed settings declares a default in `package.json`, so `getConfiguration('zer0Cms').get('governance.publishAllow')` returns `false` even for a user who has never opened the settings UI. If the settings layer were built from `get()`, it would always have a value, and `zer0.json` could never win for any key that also has a setting — three layers collapsing into one. `config.ts` therefore reads through `inspect()` and keeps only the values a human actually set (folder → workspace → global scope).

Nothing is cached. `currentConfig()` re-reads the settings and re-parses `zer0.json` on every call. That is what makes "flip `zer0Cms.governance.publishAllow` and the next publish gate sees it" true without a window reload. Multi-root did not change that and must not: if a per-site console is too slow, say so — do not put a cache behind the rule.

Every file-layer function takes an optional `scope`, and `SiteRegistry` installs the resolver that answers it. So `currentConfig()` with no argument means **the active site** rather than "folder zero", and `currentConfig(uri)` means "the site that owns that file". A command invoked on a file resolves the second — `siteTarget(arg)` in `commands/project.ts` is the one helper that does it, and the reason it exists is a bug class: approving a draft in one repository while the console is pointed at another would read the wrong banned-patterns file, the wrong ledger and the wrong publish target, and every one of them would look like it worked.

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
calls; `emptySnapshot()` is a real, renderable `Snapshot`. That is now a property of the *resolver* as much as of the store: `WorkspaceStore` asks `workspaceRoot(this.folder)`, and a resolver that fell back to `workspaceFolders[0]` would make a folderless store watch a folder nobody gave it. `multiroot.test.ts` pins it from that side.
- **One store per open folder.** `SiteRegistry` builds them, keeps them across a
folder change rather than re-creating them, and disposes the ones whose folder closed. N stores are N watcher sets and **zero** scans: the first scan is still the background refresh `extension.ts` kicks off for the active site, and the other sites are read when a surface asks (`refreshAll()`, from the Sites tab).

### 3. Context keys: eleven, and every one gates something

`zer0Cms:enabled`, `:file:isValid`, `:dashboard:open`, `:governance:enabled`, `:contract:present`, `:agent:enabled`, `:agent:running`, `:folder:registered`, `:fleet:enabled`, `:workspace:trusted`, `:sites:multi`.

Upstream shipped fourteen, of which five were dead — including the one gating its *initialize project* command, which made that command unreachable in exactly the workspace that needed it. The rule: grep `package.json` for the key before adding one. `uiState.ts` mirrors each key in memory and only calls `setContext` when the value changes, so the active-editor listener can run on every keystroke without flooding the command bus.

### 4. Diagnostics live inside the fences, and SEO is not a diagnostic

`rangeForViolation()` walks the violation's key path segment by segment, narrowing to each parent's children, and clamps the result to the block's content lines. A key that does not exist yet gets the block's first content line — where it would be written. A file with no front matter gets no diagnostics at all: it has not violated a schema, it has not claimed one.

Title length, description length and keyword density are **advice**, and advice belongs in the panel where it can be weighed. Putting it in the Problems panel next to compiler errors is how you train people to ignore the Problems panel.

### 5. The MCP registration is two-phase, and that is the security design

`provideMcpServerDefinitions` is called eagerly and may be cached, so it returns definitions with an **empty `env`** — command, argv, cwd, version, nothing else. `resolveMcpServerDefinition` runs once, at server start, and is the only place the publish flag and any secret are read.

It returns **one definition per configured folder**, plus the active one whether or not it carries a project config, each with its own `cwd` and — in a multi-root window — the folder's name in its label. `resolveMcpServerDefinition` then resolves the folder back from the server's own `cwd` and reads every flag scoped to it. That is what makes a `resource`-scoped `governance.publishAllow` mean what it says: arming publishing for the one repository you operate does not arm it for the other eleven folders open in the same window.

The publish flag comes from the **settings** layer, not from the merged configuration. `zer0.json` ships with the repository, and past `ZER0_CMS_MCP_ALLOW_PUBLISH` the only remaining gate on `zer0_publish` is `confirm: true` — a value the model supplies to itself. A cloned repo whose `zer0.json` said `publishAllow: true` would otherwise arm an agent to publish with no human act anywhere in the chain. The in-editor gates keep reading the merged value: they are behind a modal a person answers.

When publishing is off, `ZER0_CMS_MCP_ALLOW_PUBLISH` is set to `null`, which the API defines as *remove this variable from the child's environment*. Not `"0"` (a string something might later read as present) and not merely omitted (which would let an inherited `ZER0_CMS_MCP_ALLOW_PUBLISH=1` in the extension host's own environment leak through). No secret ever appears in a static definition, a setting, `.vscode/mcp.json`, or a log line — the log records that a value was injected, never the value.

---

### 6. Platform mode is a different webview, not a different panel

With `zer0Cms.platform.url` set (settings layer only, trusted workspaces only; https, or http on this machine), `zer0Cms.dashboard` opens the studio panel and `zer0Cms.agent.open` the AI panel. The Metadata view decides per file: the studio's page editor for a file the platform has a page for (`Studio.modeFor` asks `?source=` with the file's path from its folder, the folder's name first), file mode for any other — a site still on files, a file never imported, a platform that cannot be reached — and `PanelProvider` remounts in place when the answer changes. The webview is the studio's code (`web/packages/webview`), so a feature for it goes into `@zer0/ui`, never into `src/`. What the host owns is the gate: `sendToPlatform` re-checks every request on the URL it sends (the path as the platform routes it, the method, the two headers the platform reads, a modal before a live-site change) and is the only thing that ever holds the token. `zer0Cms.dashboard.files` always opens the file-mode dashboard, and the fleet, monitor, audit, harness and draft commands open it through that command, so they reach file mode in either mode.

## Adding a command

1. Declare it in `package.json` under `contributes.commands`, with any `when`
   clause it needs in `contributes.menus`.
2. Implement it in the matching `commands/*.ts`, taking the `Zer0Shell`.
3. Add the id to `ALL_COMMAND_IDS` in `commands/index.ts`, and to `ALL_COMMANDS` in `src/test/extension.test.ts` with its `57` count bumped. An id inside an existing module needs no `extension.ts` change; a new command module also needs its `register*Commands(shell)` call in `activate()`.

The only three commands `extension.ts` registers itself are `zer0Cms.dashboard`, `zer0Cms.dashboard.close` and `zer0Cms.dashboard.files`, because the dashboard panel is a singleton the shell owns and no command module does.

## Adding a privileged action

Re-read decision D5 first. Any action that writes, publishes or approves must route through a function the command palette also calls, and that function must re-read state from disk and re-run `evaluateGates()` before acting. A check performed in a webview is decoration.

The Fleet console (`commands/fleet.ts`) is the worked example for an action that reaches another system: the same four steps, `evaluateFleetGates()` in place of `evaluateGates()`, and decision D11 on top — the credential is obtained lazily inside the action, the network goes through a `fetch` injected into `core/fleet`, and nothing runs at activation.
