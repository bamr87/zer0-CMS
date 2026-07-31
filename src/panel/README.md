# `src/panel` — the metadata panel's host

One file. `PanelProvider` is the `vscode.WebviewViewProvider` behind the
`zer0Cms.panel` sidebar view: it builds the snapshot the webview draws, owns the
whitelist that decides which webview intents become actions, and implements the
two imperative posts that three commands need.

The UI itself is `src/webview/panel/**` — vanilla TypeScript, bundled to
`dist/panel.js`, no framework. Read `src/webview/panel/README.md` for the
sections; read this file for what the host does with them.

## What the host owns

### 1. The view model

Everything the panel draws arrives as one full `PanelState` snapshot (decision
D4). There are no incremental patches, so the webview holds no derived state
that could disagree with the disk.

`buildState()` reads, on every post:

| Slice | Source |
|---|---|
| `initialized`, `developer` | `hasProjectConfig()`, `context.extensionMode` |
| `fileName` / `filePath` | the tracked active editable file |
| `sections` | `zer0Cms.panel.sections` |
| `fields`, `contentTypeName` | `resolveContentType` → `inlineFieldCollections` |
| `contentTypeHint` | `missingFields(ct, data)` |
| `metadata`, `fmError` | `readArticle(filePath)` |
| `violations` | `validateFields` |
| `seo` | `getArticleDetails` → `seoInsights` + `keywordAnalysis` |
| `governance` | the draft queue, `guardWithWorkspace`, `evaluate*Gates`, the ledger |
| `recent` | `store.current().pages`, grouped by content folder, 10 per folder |
| `settings` | four booleans from the resolved config |

Nothing is cached between posts. `currentConfig()` is uncached by design, so a
setting flipped thirty seconds ago is honoured without a window reload.

Posts are debounced (80 ms) and coalesced: a save, a store refresh and a
configuration change landing together produce one snapshot, not three.

### 2. The intent whitelist

Inbound `{type:'command', id}` messages are looked up in a
`Record<CommandId, Handler>` after **two** checks:

```ts
if (!isCommandId(id) || !Object.hasOwn(this.handlers, id)) { log.warn(…); return; }
```

Both are load-bearing. `isCommandId` rejects anything outside the closed
`CommandId` union in `src/webview/shared/protocol.ts`. `Object.hasOwn` rejects
an id that would resolve through `Object.prototype` — without it a forged
`{"id":"toString"}` looks like a handler and is callable. An id that fails
either check is logged and dropped, so a forged intent provably runs no handler.

Two further allow-lists sit behind individual handlers:

- **`updateSetting`** accepts four keys (`autoUpdateModifiedDate`,
  `openOnSupportedFile`, `seoEnabled`, `agentEnabled`) and boolean values only.
  It is an intent, not a path into the settings store.
- **`openLink`** opens `https:` and `http:` and refuses everything else. A
  `command:` link posted from a webview is an escalation, not a documentation
  link.

### 3. Decision D5, at the two places it matters

`draft.approve` and `draft.publish` do **not** go through
`vscode.commands.executeCommand`. They call the injected `GovernanceActions` —
the same `doApprove`/`doPublish` that `src/commands/governance.ts` registers for
the command palette, which re-read the draft from disk, re-run the brand guard,
re-evaluate `evaluatePublishGates()` and ask modally before writing a byte.

The webview supplies a draft path and nothing else. The blockers rendered under
a disabled button are advisory; the ones that decide are computed again, later,
somewhere else.

The panel's own governance evaluation is deliberately cheaper than
`collectGateContext`: it runs the brand guard but does **not** build a publish
preview, because a preview resolves the source page and renders the artifact the
target would write — right to do once when somebody presses Publish, wrong to do
on every change of active editor. The consequence is bounded and named in the
code: the panel can omit the `previewFailed` blocker, and it only knows about
`requiredFieldMissing` when the draft's source is the file on screen.

### 4. The panel bridge

`zer0Cms.collapseSections`, `focusTags` and `focusCategories` are commands whose
whole effect is inside the webview. `setPanelBridge(this)` (from
`src/commands/content.ts`) registers `collapseAll()` and `focus(target)`, and the
registration is disposed with the view — so a command invoked after the panel is
closed logs rather than posting into a dead webview. The dependency points
panel → commands, never the reverse.

## The request channel

`ViewMsg.request` is how a field widget asks the host to compute something. The
op vocabulary is closed by `RequestOp`; these are the payload and result shapes
the widgets in `src/webview/panel/fields/**` are written against.

| op | payload | result |
|---|---|---|
| `generateSlug` | `{ title?: string }` | `{ slug: string }` — prefix/suffix applied |
| `searchContent` | `{ contentType?: string; query?: string }` | `PageEntry[]`, capped at 50 |
| `resolvePlaceholder` | `{ value: string }` | `{ value: string }` |
| `taxonomyOptions` | — | `TaxonomyOptions` |
| `pickImage` | `{ multiple?: boolean }` | `string[]` — site-rooted when `content.publicFolder` is set, else document-relative |
| `pickFile` | `{ multiple?: boolean; extensions?: string[] }` | `string[]` — document-relative |
| `guardText` | `{ text: string }` | `GuardFindingView[]` |
| `previewDraft` | `{ draftPath: string }` | `{ artifact: string; url: string \| null }` |

A handler that throws replies `{error}` rather than rejecting: the webview's
`Messenger.request` shows the message in the control that asked, and a rejected
promise nobody sees would leave that control in its loading overlay until the
ten-second timeout.

## Writes

`updateField` re-reads the article from disk rather than trusting the snapshot
the webview rendered — between the render and the click somebody may have saved
the file, and the line surgery in `writeArticle` (decision D7) against a stale
copy would put the change on the wrong line. A dirty editor is saved first, for
the same reason `activeArticle()` does it: otherwise the buffer overwrites us
the moment the user saves.

Clearing a field posts `value: undefined`, which the host resolves to that
field's declared `emptyValueFor(...)` — not to the literal string `undefined`.

`addTaxonomy` writes `zer0.json`, not the article. The article already carries
the value; what the user asked for by pressing `+` on an unknown pill is that it
stop being unknown.

## The page shell

`panelHtml()` builds a static page under:

```
default-src 'none';
style-src  ${cspSource} 'nonce-…';
script-src 'nonce-…';
font-src   ${cspSource};
img-src    ${cspSource} data: https:;
```

The nonce is 128 crypto-random bits regenerated on every render.
`localResourceRoots` is `[media/, dist/]` and nothing else.

**No file name, front-matter value, draft body or guard message is templated
into the HTML.** The page ships empty; every character of content arrives over
`postMessage` and is written with `textContent`. That is what makes
`default-src 'none'` a guarantee rather than a decoration — there is no code
path from a workspace file to markup, so the CSP has nothing to catch.

`enableCommandUris` is set **only** outside a Production extension host, and
only to the two commands the developer bar uses
(`workbench.action.webview.reloadWebviewAction`,
`workbench.action.webview.openDeveloperTools`). `enableCommandUris: true` would
let any anchor in the page invoke any command in the workbench.

## Related

- `src/webview/panel/README.md` — the sections this host feeds.
- `src/commands/governance.ts` — the gate. Read its header before changing
  anything about approve or publish.
- `media/panel.css` — every class name emitted by the sections.
