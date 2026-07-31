# `src/commands/` — the command layer

Thirty-four commands, six files, and one rule that matters more than the other
thirty-three: **`governance.ts` holds the only gate.**

Everything here may import `vscode`. Nothing here implements domain logic — the
bodies ask questions (which folder? which content type? are you sure?), call
into `src/core`, and report what happened. When a command starts formatting
front matter or computing a slug, it is doing `src/core`'s job.

---

## The inventory

| File | Commands | LOC |
|---|---|---|
| `project.ts` | `init`, `refresh`, `cache.clear`, `showOutput`, `openFile`, `registerFolder`, `unregisterFolder` | 369 |
| `content.ts` | `createContent`, `createContentInFolder`, `generateSlug`, `setLastModified`, `insertImage`, `collapseSections`, `focusTags`, `focusCategories` | 488 |
| `contentType.ts` | `contentType.generate`, `contentType.addMissingFields`, `contentType.set` | 253 |
| `governance.ts` | `draft.new`, `draft.review`, `draft.approve`, `draft.publish`, `draft.guard`, `draft.preview` | 676 |
| `contract.ts` | `contract.run`, `contract.normalizePreview`, `contract.normalizeApply`, `catering.worklist` | 262 |
| `agent.ts` | `agent.open`, `agent.start`, `agent.stop`, `mcp.writeWorkspaceConfig` | 169 |
| `index.ts` | barrel + `ALL_COMMAND_IDS` | 113 |

`dashboard` and `dashboard.close` are registered by `extension.ts`, beside the
panel object they operate on. They are still listed in `ALL_COMMAND_IDS`,
because that list is about the contribution surface and not about which file
happens to hold the closure.

### Three places, on purpose

An id has to appear in `contributes.commands` (`package.json`), in a
`register(shell, id, …)` call here, and in `ALL_COMMAND_IDS`. Nothing in
TypeScript connects the first two, and both failure modes are silent — a
contributed id with no handler is a palette entry that does nothing; a handler
with no contribution is a command nobody can find. `extension.test.ts` compares
all three, so skipping one fails loudly instead of quietly.

---

## Decision D5 — the gate

> The webview is UI, never the gate.

`doApprove` and `doPublish` in `governance.ts` are the **only** functions that
change a draft's lifecycle state, and every surface reaches them:

```
command palette ─┐
drafts tree row ─┼─→ zer0Cms.draft.publish ─→ doPublish(shell, draftPath)
panel button ────┤                               │
dashboard button ┘                               ├─ currentConfig()          (fresh settings)
                                                 ├─ readDraft(path)          (fresh bytes)
                                                 ├─ buildPreview(…)          (fresh guard, fresh url)
                                                 ├─ getEntry(ledger, url)    (fresh ledger)
                                                 ├─ validateFields(source)   (fresh page)
                                                 ├─ evaluatePublishGates(…)  (the decision)
                                                 ├─ confirm(…, {modal:true}) (the human)
                                                 └─ publishPreview(…)        ← gates AGAIN, inside the write
```

A webview button posts `{type:'command', id:'draft.publish', args:{draftPath}}`
— an intent and a target. No payload, no `force`, no "the user already
confirmed". The host looks the id up in its `Record<CommandId, Handler>` and
calls the function above; anything it does not recognise is logged and dropped.

Three consequences worth stating:

1. **The webview's own gate render is advisory.** Both surfaces call
   `evaluateGates()` to grey out a button and write the `Publish disabled: a;
   b.` note. That render can be stale, forged, or simply wrong. It is never
   what decides.
2. **No command passes `force`.** `publishPreview` accepts it, because a human
   who has read the guard findings may overrule them, and the MCP lane and CI
   need the seam. Nothing reachable from a keystroke does.
3. **`publishDisabled` is not overridable at all.** `force` does not clear it
   in the core, and no surface offers a way around it. A workspace that has not
   set `zer0Cms.governance.publishAllow` cannot publish, full stop.

The draft's status is flipped **after** the target reports success. A target
failure must never leave a queue file claiming it published. A *ledger skip* —
the URL was already recorded — still flips it, because the artifact genuinely
is out there; that matches the CI lane, and the two have to agree.

---

## Two bridges: how commands reach a webview

Three commands (`collapseSections`, `focusTags`, `focusCategories`) and three
more (`agent.open` / `.start` / `.stop`) have their entire effect inside a
webview that owns its own lifecycle. The host cannot do those things itself; it
can only post a message to a view that may not exist yet.

So the dependency points **webview host → commands**, never the other way:

```ts
// src/panel/panelProvider.ts — in resolveWebviewView()
import { setPanelBridge } from '../commands/content';

this.disposables.push(
  setPanelBridge({
    collapseAll: () => void view.webview.postMessage({ type: 'collapseAll' }),
    focus: (target) => void view.webview.postMessage({ type: 'focus', target }),
  }),
);
```

```ts
// src/agent/agentPanel.ts — in the constructor
import { setAgentHost } from '../commands/agent';

this.disposables.push(setAgentHost(this));   // open() / start(prompt?) / stop() / running
```

Both `set*` functions return a `Disposable` that unhooks only if the
registration is still the current one, so a panel disposed after a replacement
registered cannot unhook the replacement.

**With nothing registered the commands degrade, they do not throw.**
`focusTags` still reveals the panel view (which is what causes the provider to
resolve and register a bridge in the first place); `agent.start` says the agent
is not available in this window. That is deliberate: the command palette has to
keep working in a window where the panel was never opened and the agent was
never enabled.

---

## Command arguments arrive in four shapes

The same command is invoked from the palette (no argument), the explorer
context menu (a `Uri`), a tree row (a `TreeItem` subclass), and a webview (a
string, or `{draftPath}`). `toFilePath(cfg, arg)` in `project.ts` and
`draftPathFrom(cfg, arg)` in `governance.ts` are the two coercions; every
handler starts with one of them and falls back to a `showQuickPick`.

A webview's string may be **workspace-relative** — it renders relative paths, so
it names them that way — which is why the coercion takes a `Zer0Config`.

---

## The other things that are easy to get wrong

### `activeArticle()` saves a dirty document first

`writeArticle` writes to disk. An unsaved buffer over the same file is a second
version racing to be last, and the editor wins whenever the user hits save. So
`activeArticle()` calls `document.save()` before reading — visibly, not
silently.

### Content-type and folder edits go to `zer0.json`, never to settings

Which folders hold content and what shape a page has is *repository* schema: it
is reviewed in pull requests and has to be identical for everyone who checks the
repository out. A user-scoped setting is none of those. `updateConfigFileJson`
does a read-modify-write of the JSON rather than serialising a resolved
`Zer0Config` back out, so hand-formatting and JSONC comments survive.

Folder paths are stored with the `[[workspace]]` token so a checkout at a
different path still resolves.

### `resolveFolders()`, not `cfg.contentFolders`, when a real directory is needed

`cfg.contentFolders[].path` is absolute but may still be a **wildcard**
(`[[workspace]]/pages/*`). `resolveFolders()` expands those into the concrete
directories they stand for. Creating a file with the unexpanded form produces a
directory literally named `*`, and prefix-matching a file against it never
matches. Anything touching the disk uses the resolved list.

### `zer0Cms.init` has no `when` clause, and that is the fix

Upstream's equivalent was gated on a context key that only got set once a
project config already existed — the initialize command was unreachable in
exactly the workspace that needed it. Ours activates on `onCommand:` and is
always visible. Do not add a `when`.

### The engine is optional and never rejects

`.cms/` absent is a normal state (decision D9). `runEngine` returns a code
instead of throwing, and exit code `2` means "the normalizer found work", not
"something broke". `contract.normalizePreview` writes nothing; the `--apply`
variant is a separate command behind a modal that uses the word "rewrites",
because it does, in bulk.

### Reports are untitled documents

Guard findings, engine output and publish previews open as untitled markdown.
They are read once and closed. Writing them would litter the repository with
files nobody asked for, and a preview that leaves artifacts behind has stopped
being a preview.

---

## Adding a command

1. Add it to `contributes.commands` in `package.json`, with the `zer0-CMS`
   category, and to whatever menus should surface it.
2. `register(shell, 'my.command', handler)` in the file that owns its subject.
   The wrapper turns a rejected promise into a notification instead of an
   unhandled rejection nobody sees.
3. Add the id to `ALL_COMMAND_IDS` in `index.ts`.
4. If a webview should be able to invoke it, add the literal to `CommandId` in
   `src/webview/shared/protocol.ts` **and** a handler entry in the host's
   `Record<CommandId, Handler>`. Adding the literal alone grants nothing.
5. If it is privileged, it goes through `evaluateGates()` and a modal
   confirmation, in the same function every other surface calls. Re-read state
   from disk first. A webview-only check is decoration.
