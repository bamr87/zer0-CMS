# `src/webview` — the vanilla TypeScript UI

Three bundles, no framework: `dist/panel.js`, `dist/dashboard.js` and `dist/agent.js`, each an esbuild IIFE with **zero** dependencies. What React, Recoil, Tailwind, Headless UI, Radix and Downshift did in the fork this replaces, seven files in `shared/` do here.

```
shared/      the kernel every surface uses     (this work package)
panel/       the sidebar sections + 18 fields
dashboard/   the six served routes, of eleven declared
agent/       the transcript and approval cards
```

## The two rules

1. **No `innerHTML`, `outerHTML` or `insertAdjacentHTML`.** eslint fails the
build on all three (`eslint.config.mjs`, block 3). Build DOM with `el()`; text goes in through `textContent`/`createTextNode`. The webview renders draft bodies, file names and guard messages — content the user or an AI wrote — so this is what makes the strict CSP meaningful rather than decorative.
2. **The webview is UI, never the gate.** A button posts
`{ type: 'command', id }` — an intent and a target, never a payload and never an override. Every gate (the publish-allow flag, the brand guard, the ledger, draft status, required fields) is re-checked host-side in the same function the command palette calls. A check that lives only here is decoration.

Webview code may import from `src/core/**` (it is pure Node/ES and tree-shakes fine) but never from `vscode`, `src/commands/**` or `src/views/**`.

## The kernel

| File | What it is |
|---|---|
| `shared/protocol.ts` | The typed message union in both directions, the `PanelState`/`DashboardState`/`AgentState` view models, and the closed `CommandId` union. No runtime code. |
| `shared/messenger.ts` | `acquireVsCodeApi()` wrapper: `post`, `command`, `request(op, payload)` with a requestId and a 10s timeout, `onState`, and the persisted `ViewUiState`. |
| `shared/dom.ts` | `el`, `icon`, `clear`, `append`, `on`, `debounce`, plus the four colour helpers behind the six derived design tokens. |
| `shared/svg.ts` | `svgEl`, `svgRoot` — `createElementNS` for the namespace `el()` cannot produce. |
| `shared/state.ts` | `mountSections` — the section-level reconciler. |
| `shared/components.ts` | Eighteen shared widgets: `collapsible`, `menuButton`, `modal`, `alert`, `slideOver`, `pagination`, `spinner`, `tagPill`, `validInfo`, `textField`, `toggle`, plus the seven operator primitives below. |
| `shared/form.ts` | `stagedForm` — a settings form whose edits are staged and flushed by Save, keyed by a form id. |

### The seven operator primitives

`statusPill`, `dataTable`, `emptyState`, `gatedButton`, `blockerNote`, `keyValueList` and `diffView` were each hand-rolled two or three times in `dashboard/{fleet,governance,catering}.ts` before they moved into `components.ts`. Five more tabs need all seven, and three copies of "what does a grey cell mean" is how two screens end up disagreeing about the same lane.

Two of them carry a rule rather than a look.

**`unknown` is not `neutral`.** `statusPill`'s five variants are `ok | warn | danger | neutral | unknown`, and the last one renders unfilled, dashed and italic rather than as another grey badge. A cell nobody has asked about — no credential, no read, no scan — must not look like a cell whose answer happens to be "no". The Fleet route's four honest switch states (`true`, `false`, `unset`, `unknown`) are where this came from, and it lives here now so the five new tabs inherit it rather than each remembering it.

**`gatedButton` is a courtesy, never a control.** It renders a disabled button plus the host's blocker sentence in the gate's own order, and posts `{ id, args }` — an intent and a target. Every gate is re-checked host-side in the same function the command palette calls, so a button that renders enabled when the gate says otherwise is a cosmetic bug, not an escalation. `verb` exists because "Switch off disabled: …" is not a sentence; the verb the gate refuses is the toggle, whatever the button is offering right now.

`dataTable` wraps its `<table>` in a `.z-table__scroll` box, because wide operator content — lane, harness, triggers, switch, run, cost — has to scroll in its own box or it takes the tab bar and the toolbar sideways with it. Numeric columns get `.z-table__num`, which is right-aligned with `font-variant-numeric: tabular-nums`; figures that do not line up cannot be compared by eye.

### Staged forms

`stagedForm({ key, items, onSave, onCancel })` is the Settings route's edit pattern, extracted. Controls write into a staged map, **Save** flushes it as `{key, value}` pairs, and the button is disabled exactly when the map is empty — which makes "Save is disabled until something changed" a fact about the data rather than a flag somebody has to remember to set. The map survives a state snapshot (a half-typed page size must not be erased by an unrelated refresh) and an entry clears itself the moment the host reports the value it was asking for, so a *refused* write visibly stays dirty.

The `key` is the point. It used to be one `pending` map at the Settings module's scope, which was correct for exactly as long as there was one form on screen; PR3's site profile and PR4's lane scaffolder are the second and third users. Two module-scoped maps under one key is not a bug you find by reading — it is a bug you find when somebody's half-typed cron minute lands in somebody else's page size.

It handles all seven `SettingItem.kind`s. A `multichoice` value travels as a comma-separated list of choice ids; `path` and `secretName` render monospaced with autocorrect off, and `secretName` says under the field that the console holds the *name* of a credential and never its value.

### The protocol, in one paragraph

Host → webview is a **single full `state` snapshot** plus four genuinely imperative messages (`progress`, `focus`, `collapseAll`, `result`). There are no incremental patches, so the webview holds no derived state beyond ephemeral input focus and the persisted collapse map. Webview → host is six shapes: `ready`, `updateField`, `addTaxonomy`, `command`, `request`, `setUiState`, `log`. The fork had 12 + 52 message names on one surface and 11 + 40 on the other; a snapshot plus an intent enum is auditable, and the enum is the point at which the host decides what may run.

`request()` rejects after ten seconds. That is not defensive decoration: a field shows a loading overlay while a request is in flight, so a reply the host never sends would wedge that control forever.

### The reconciler, in one paragraph

A `Section<S>` declares an `id`, a `stale(prev, next)` predicate and a `render(next, host)`. `mountSections(root, sections)` returns an update function; each snapshot re-renders only the sections whose predicate says so. There is no virtual DOM and no diffing — a section rebuild is `clear(host)` plus `render`.

The one subtlety is **focus**. Clearing a subtree destroys the element the user is typing in, taking the caret and any IME composition with it. So a stale section that contains `document.activeElement` is not rebuilt: the snapshot is parked and flushed on the next `focusout`. Being late is correct; interrupting a keystroke is not.

Use `staleOn(s => s.a, s => s.b)` for the common case. Keep the projections primitive — returning an array or an object literal makes the section stale on every snapshot, which is the bug this design exists to avoid.

### `el()`

```ts
el('button', { class: 'z-btn', type: 'button', disabled: true,
               dataset: { id: page.slug },
               attrs: { 'aria-pressed': 'false' },
               onclick: () => msg.command('openFile', page.filePath) },
   icon('eye'), 'Open', srOnly('Open this file'));
```

Props map to DOM properties when one exists and to attributes otherwise; `class`, `dataset`, `attrs` and `on` are special-cased; any `on*` key whose value is a function is registered with `addEventListener` so several handlers can coexist. Children may be nodes, strings, numbers, nested arrays or falsy holes (`cond && node` renders nothing when false).

**There is no `style` prop.** Every shell serves `default-src 'none'` with `style-src <cspSource> 'nonce-…'`, and a nonce cannot apply to an attribute — so an inline `style` is dropped by the browser with no console error and no visible failure. `el()` carried one for eleven call sites that had each been silently doing nothing since the day they were written; they are classes in `media/base.css` now (`.z-hidden`, `.z-center`, `.z-dim`, `.z-anchor`, `.z-row`, `.z-inset`, …) and `src/test/styling.test.ts` fails the build if the prop comes back.

`el()` is HTML-only, because `document.createElement` always produces an HTML element. An `<svg>` built that way is inert and every child inside it is an unknown tag that lays out as nothing, so a chart, a sparkline or a gauge goes through `svgEl()` in `shared/svg.ts`, which uses `createElementNS`. The no-markup rule applies there identically: an SVG document is a script host, so `innerHTML` on an `<svg>` is not a lesser risk.

## Field widgets

`FieldWidget`, `FieldFactory` and `FieldContext` live in `protocol.ts`. `panel/fields/index.ts` owns a `Record<FieldType, FieldFactory>` registry plus the shared chrome (title row, required asterisk, the mutually exclusive required/description message, the loading overlay, the error fallback). A widget implements `setValue`, `setLoading`, `setError`, `focus` and `dispose` — and `dispose()` really must remove its listeners. The leak test that mounts and disposes 500 times is `src/test/webview.test.ts`; it counts listeners on `document` and `window`, the two targets that outlive a widget, because a listener on a node the caller then drops is collected with the node and is not a leak.

## Styling

Every class this code emits is styled in `media/`. Read `media/README.md` before adding a rule; the short version is that only `media/tokens.css` may name a VS Code theme variable, and everything else uses a `--z-*` token. `src/test/styling.test.ts` greps for both violations — the theme variable and the `style` prop — so neither can spread quietly into a new tab.

Class names carry two vocabularies on purpose. `.z-*` is the kernel; `.metadata_field__*`, `.article__tags__*`, `.file_list__*`, `.collapsible__body` and `.ext_link_block` are inherited names, kept so the panel code can be read against the same UI recon that produced the stylesheets.
