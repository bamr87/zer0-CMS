# `src/dashboard` — the dashboard host

One file: `dashboardPanel.ts`, the extension-host side of the
`zer0Cms.dashboard` editor tab. The UI it drives lives in
[`src/webview/dashboard/`](../webview/dashboard/README.md); this directory
contains no DOM code and the webview contains no `vscode` import. That split is
the whole architecture, and it is enforced by eslint and by the build.

```
src/dashboard/dashboardPanel.ts     ← you are here: state builder + intent router
        │  postMessage({type:'state', state})
        ▼
dist/dashboard.js  ←  src/webview/dashboard/{main,header,contents,structure}.ts
                                            {governance,catering,settings,welcome}.ts
        │  postMessage({type:'command', id, args})
        ▼
src/commands/**  ← the same functions the command palette calls
```

## What the host owns

| # | Job | Where |
|---|---|---|
| 1 | Building one full `DashboardState` snapshot per post | `buildState()` and the `build*` projections |
| 2 | The closed intent whitelist (`Record<CommandId, Handler>`) | `dispatch()` |
| 3 | Routing the two governed intents into the injected `GovernanceActions` | `runGovernance()` |
| 4 | Round-tripping the durable UI preferences through `workspaceState` | `UI_STATE_KEYS`, `writeUiState()` |
| 5 | Three request ops: `searchContent`, `guardText`, `previewDraft` | `handleRequest()` |
| 6 | The CSP'd page shell with a per-render nonce | `dashboardHtml()` |

Everything else — which tab is open, which sort order, which rows are ticked —
is view-local state that lives in the webview and is not authoritative
anywhere.

## Decision D5, concretely

`draft.approve` and `draft.publish` do **not** go through
`vscode.commands.executeCommand`. They call the `GovernanceActions` injected by
`extension.ts`, which are the very `doApprove`/`doPublish` closures
`src/commands/governance.ts` registers for the palette. Those re-read the draft
from disk, re-run the brand guard, re-evaluate `evaluatePublishGates()` and ask
modally before writing a byte.

The webview supplies a draft path and nothing else. The blockers rendered under
a disabled Publish button come from `buildReview()` and are **advisory**: the
ones that decide are computed again, later, in a different process boundary.

Deleting and renaming are not governed actions — nothing is written to the
ledger and no gate applies — so they are implemented here directly, against
`workspace.fs`, with `useTrash: true`. The webview confirms before posting the
intent; the host does not ask a second time, because deleting to the desktop
trash is recoverable and two modals for one click is not a safety feature.

## The intent whitelist

```ts
if (!isCommandId(id) || !Object.hasOwn(this.handlers, id)) { log.warn(…); return; }
```

Both checks matter. `isCommandId` rejects anything outside the closed
`CommandId` union in `protocol.ts`. `Object.hasOwn` rejects an id that would
resolve through `Object.prototype` — without it a forged `{"id":"toString"}`
looks like a handler and is callable. A forged intent provably runs nothing.

The same doctrine applies twice more: `UI_STATE_KEYS` is the only set of
workspace-state keys the webview can write, and `SETTING_KEYS` (plus the two
`dashboard.cardFields.*` members) is the only set of settings it can change.
`zer0Cms.governance.publishAllow` is deliberately **not** in that table — the
publish switch is not something a webview may flip.

## Durable UI state

Four preferences must survive the webview being disposed. They are stored under
the keys PLAN §4.5 names, inconsistent prefixes and all, because those are the
keys an existing workspace already holds:

| webview key | workspace-state key |
|---|---|
| `Contents:Sorting` | `zer0Cms:Dashboard:Contents:Sorting` |
| `Contents:Grouping` | `zer0Cms:Dashboard:Contents:Grouping` |
| `Contents:Tab` | `zer0Cms:Dashboard:Contents:Tab` |
| `PagesView` | `zer0Cms:PagesView` |
| `SelectedFolder` | `zer0Cms:SelectedFolder` |
| `Route` | `zer0Cms:Dashboard:Route` |
| `Drafts:Selected` | `zer0Cms:Dashboard:Drafts:Selected` |

Two of them feed back into the snapshot: `Contents:Sorting` becomes
`contents.defaultSorting` and `PagesView` becomes `contents.defaultView`, so a
reopened dashboard is sorted the way you left it. `Route` becomes the boot
route templated into the shell as `data-route`. `Drafts:Selected` is the one
key whose write triggers a re-post, because the review pane it selects is
built here rather than in the webview.

## The review pane is expensive, so it is built once

`buildDrafts()` summarises the whole queue but builds a `ReviewState` for
exactly one draft — the selected one, defaulting to the first `pending` entry.
That single build reads the draft, runs `guardWithWorkspace` and calls
`buildPreview`, which resolves the source page and composes the exact artifact
that would be published. A preview failure is not swallowed: it becomes the
`previewFailed` blocker, because "we could not build it" is itself a reason not
to publish.

## Deliberate simplifications

- **No image previews on content cards.** The webview's `localResourceRoots`
  are `media/` and `dist/` and nothing else (PLAN §4.4), so a workspace image
  has no loadable URI. Widening the roots to the whole repository to put a
  thumbnail on a card is not a trade worth making; `contents.ts` renders
  `<img>` only for `https:`/`data:` references and the markdown glyph
  otherwise.
- **The four lane empty-state sentences are duplicated** from
  `core/catering/worklist.ts`, where they are built inline rather than
  exported. `LANE_EMPTY` carries the same strings byte-for-byte and picks
  between lane B's two variants with the real `hasEvidence(plan)`. If that
  function's prose changes, this constant changes with it — the screen and the
  generated file disagreeing about the same empty lane is exactly the bug the
  constant exists to make obvious.
- **`customSorting` and `grouping` are read from `zer0.json` directly**
  (`customDashboardConfig()`), not from `Zer0Config`. They are a dashboard
  nicety rather than part of the content model, so `resolveConfig` has no field
  for them. Entries are coerced defensively and a `customSorting` id follows
  Front Matter's `<field>-<asc|desc>` convention, which is how the webview
  applies a sort it has never seen without a second schema.
- **`open(route)` routes a *new* panel only.** The route is validated against
  the closed route set and templated into `data-route`; an already-open panel
  is revealed. The manifest's `zer0Cms.dashboard` command takes no argument, so
  nothing in the shipped surface hits the other case.

## Changing this file

- A new intent needs three things: a literal in `CommandId`
  (`src/webview/shared/protocol.ts`), an entry in `this.handlers`, and a caller
  in the webview. Adding the literal alone grants nothing.
- A new piece of state belongs in `DashboardState` in `protocol.ts` first, then
  in `buildState()`. Do not smuggle data through `data-*` attributes on the
  shell — the one there now is a validated enum literal, and that is the whole
  budget.
- Nothing that renders belongs here. If you are writing `el(` in this
  directory, it is in the wrong file.
