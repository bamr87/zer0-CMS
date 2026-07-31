# `src/webview` — the vanilla TypeScript UI

Three bundles, no framework: `dist/panel.js`, `dist/dashboard.js` and
`dist/agent.js`, each an esbuild IIFE with **zero** dependencies. What React,
Recoil, Tailwind, Headless UI, Radix and Downshift did in the fork this
replaces, five files in `shared/` do here.

```
shared/      the kernel every surface uses     (this work package)
panel/       the sidebar sections + 18 fields
dashboard/   the five routes
agent/       the transcript and approval cards
```

## The two rules

1. **No `innerHTML`, `outerHTML` or `insertAdjacentHTML`.** eslint fails the
   build on all three (`eslint.config.mjs`, block 3). Build DOM with `el()`;
   text goes in through `textContent`/`createTextNode`. The webview renders
   draft bodies, file names and guard messages — content the user or an AI
   wrote — so this is what makes the strict CSP meaningful rather than
   decorative.
2. **The webview is UI, never the gate.** A button posts
   `{ type: 'command', id }` — an intent and a target, never a payload and
   never an override. Every gate (the publish-allow flag, the brand guard, the
   ledger, draft status, required fields) is re-checked host-side in the same
   function the command palette calls. A check that lives only here is
   decoration.

Webview code may import from `src/core/**` (it is pure Node/ES and tree-shakes
fine) but never from `vscode`, `src/commands/**` or `src/views/**`.

## The kernel

| File | What it is |
|---|---|
| `shared/protocol.ts` | The typed message union in both directions, the `PanelState`/`DashboardState`/`AgentState` view models, and the closed `CommandId` union. No runtime code. |
| `shared/messenger.ts` | `acquireVsCodeApi()` wrapper: `post`, `command`, `request(op, payload)` with a requestId and a 10s timeout, `onState`, and the persisted `ViewUiState`. |
| `shared/dom.ts` | `el`, `icon`, `clear`, `append`, `on`, `debounce`, plus the four colour helpers behind the six derived design tokens. |
| `shared/state.ts` | `mountSections` — the section-level reconciler. |
| `shared/components.ts` | Eleven shared widgets: `collapsible`, `menuButton`, `modal`, `alert`, `slideOver`, `pagination`, `spinner`, `tagPill`, `validInfo`, `textField`, `toggle`. |

### The protocol, in one paragraph

Host → webview is a **single full `state` snapshot** plus four genuinely
imperative messages (`progress`, `focus`, `collapseAll`, `result`). There are no
incremental patches, so the webview holds no derived state beyond ephemeral
input focus and the persisted collapse map. Webview → host is six shapes:
`ready`, `updateField`, `addTaxonomy`, `command`, `request`, `setUiState`,
`log`. The fork had 12 + 52 message names on one surface and 11 + 40 on the
other; a snapshot plus an intent enum is auditable, and the enum is the point at
which the host decides what may run.

`request()` rejects after ten seconds. That is not defensive decoration: a field
shows a loading overlay while a request is in flight, so a reply the host never
sends would wedge that control forever.

### The reconciler, in one paragraph

A `Section<S>` declares an `id`, a `stale(prev, next)` predicate and a
`render(next, host)`. `mountSections(root, sections)` returns an update function;
each snapshot re-renders only the sections whose predicate says so. There is no
virtual DOM and no diffing — a section rebuild is `clear(host)` plus `render`.

The one subtlety is **focus**. Clearing a subtree destroys the element the user
is typing in, taking the caret and any IME composition with it. So a stale
section that contains `document.activeElement` is not rebuilt: the snapshot is
parked and flushed on the next `focusout`. Being late is correct; interrupting a
keystroke is not.

Use `staleOn(s => s.a, s => s.b)` for the common case. Keep the projections
primitive — returning an array or an object literal makes the section stale on
every snapshot, which is the bug this design exists to avoid.

### `el()`

```ts
el('button', { class: 'z-btn', type: 'button', disabled: true,
               dataset: { id: page.slug },
               attrs: { 'aria-pressed': 'false' },
               onclick: () => msg.command('openFile', page.filePath) },
   icon('eye'), 'Open', srOnly('Open this file'));
```

Props map to DOM properties when one exists and to attributes otherwise;
`class`, `dataset`, `attrs`, `style` and `on` are special-cased; any `on*` key
whose value is a function is registered with `addEventListener` so several
handlers can coexist. Children may be nodes, strings, numbers, nested arrays or
falsy holes (`cond && node` renders nothing when false).

## Field widgets

`FieldWidget`, `FieldFactory` and `FieldContext` live in `protocol.ts`.
`panel/fields/index.ts` owns a `Record<FieldType, FieldFactory>` registry plus
the shared chrome (title row, required asterisk, the mutually exclusive
required/description message, the loading overlay, the error fallback). A widget
implements `setValue`, `setLoading`, `setError`, `focus` and `dispose` — and
`dispose()` really must remove its listeners; there is a leak test that mounts
and disposes 500 times.

## Styling

Every class this code emits is styled in `media/`. Read `media/README.md` before
adding a rule; the short version is that only `media/tokens.css` may name a VS
Code theme variable, and everything else uses a `--z-*` token.

Class names carry two vocabularies on purpose. `.z-*` is the kernel;
`.metadata_field__*`, `.article__tags__*`, `.file_list__*`, `.collapsible__body`
and `.ext_link_block` are inherited names, kept so the panel code can be read
against the same UI recon that produced the stylesheets.
