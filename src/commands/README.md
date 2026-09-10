# `src/commands/` — the command layer

Forty-one commands, eight files, and one rule that matters more than the other forty: **`governance.ts`, `fleet.ts` and `audit.ts` hold the only gates.** Three more files — `contract.ts`, `content.ts` and `agent.ts` — hold the *other* kind of gate, the one Workspace Trust decides; see "Trust is re-checked inside the function" below, which `audit.ts` also belongs to because `audit.verify` is the fifth execution vector.

Everything here may import `vscode`. Nothing here implements domain logic — the bodies ask questions (which folder? which content type? are you sure?), call into `src/core`, and report what happened. When a command starts formatting front matter or computing a slug, it is doing `src/core`'s job.

---

## The inventory

| File | Commands | LOC |
|---|---|---|
| `project.ts` | `init`, `refresh`, `cache.clear`, `showOutput`, `openFile`, `registerFolder`, `unregisterFolder` | 369 |
| `content.ts` | `createContent`, `createContentInFolder`, `generateSlug`, `setLastModified`, `insertImage`, `collapseSections`, `focusTags`, `focusCategories` | 523 |
| `contentType.ts` | `contentType.generate`, `contentType.addMissingFields`, `contentType.set` | 253 |
| `governance.ts` | `draft.new`, `draft.review`, `draft.approve`, `draft.publish`, `draft.guard`, `draft.preview` | 676 |
| `contract.ts` | `contract.run`, `contract.normalizePreview`, `contract.normalizeApply`, `catering.worklist` | 320 |
| `agent.ts` | `agent.open`, `agent.start`, `agent.stop`, `mcp.writeWorkspaceConfig` | 194 |
| `fleet.ts` | `fleet.open`, `fleet.refresh`, `fleet.toggleSwitch`, `fleet.dispatchLane` | 574 |
| `audit.ts` | `audit.open`, `audit.fix`, `audit.verify` | 761 |
| `index.ts` | barrel + `ALL_COMMAND_IDS` | 128 |

`dashboard` and `dashboard.close` are registered by `extension.ts`, beside the panel object they operate on. They are still listed in `ALL_COMMAND_IDS`, because that list is about the contribution surface and not about which file happens to hold the closure.

### Three places, on purpose

An id has to appear in `contributes.commands` (`package.json`), in a `register(shell, id, …)` call here, and in `ALL_COMMAND_IDS`. Nothing in TypeScript connects the first two, and both failure modes are silent — a contributed id with no handler is a palette entry that does nothing; a handler with no contribution is a command nobody can find. `extension.test.ts` compares all three, so skipping one fails loudly instead of quietly.

---

## Decision D5 — the gate

> The webview is UI, never the gate.

`doApprove` and `doPublish` in `governance.ts` are the **only** functions that change a draft's lifecycle state, and every surface reaches them:

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

A webview button posts `{type:'command', id:'draft.publish', args:{draftPath}}` — an intent and a target. No payload, no `force`, no "the user already confirmed". The host looks the id up in its `Record<CommandId, Handler>` and calls the function above; anything it does not recognise is logged and dropped.

Three consequences worth stating:

1. **The webview's own gate render is advisory.** Both surfaces call
`evaluateGates()` to grey out a button and write the `Publish disabled: a; b.` note. That render can be stale, forged, or simply wrong. It is never what decides.
2. **No command passes `force`.** `publishPreview` accepts it, because a human
who has read the guard findings may overrule them, and the MCP lane and CI need the seam. Nothing reachable from a keystroke does.
3. **`publishDisabled` is not overridable at all.** `force` does not clear it
in the core, and no surface offers a way around it. A workspace that has not set `zer0Cms.governance.publishAllow` cannot publish, full stop.

The draft's status is flipped **after** the target reports success. A target failure must never leave a queue file claiming it published. A *ledger skip* — the URL was already recorded — still flips it, because the artifact genuinely is out there; that matches the CI lane, and the two have to agree.

### The same gate, for the audit's fix-it

`doFixIssue` in `audit.ts` is the third pair's single half, and it is the strictest of the three because it rewrites a file in the repository rather than a queue file or a remote variable. The webview posts `{type:'command', id:'audit.fix', args:{path, kind}}` — a file and a rule id, never a change set — and the host then, in this order: re-reads the configuration with `currentConfig()`; re-reads the **whole site** from disk through `scanSite`, which re-detects the platform, rebuilds the page index and re-reads every block; re-runs `auditPage` for that one file and looks the finding up **again** by `kind`; asks `fixFor` for the change set; renders it through `dryRunFix`; opens the two sides in a real diff editor over the `zer0cms-audit:` `TextDocumentContentProvider` this module registers; asks modally, naming the file, the rule and the change; and only then calls `writeArticle`.

The re-lookup in step three is the point of the whole ordering. A `kind` that no longer fires means the file changed under the person between the scan and the click, and applying `missing-key:date` to a file that has since acquired a date would write a second, wrong one. It refuses, in words, and says why. `fixFor` returning `null` — every rule for which no mechanical repair is honest — is the same kind of refusal, and so is every case `dryRunFix` declines: TOML and JSON front matter, a nested path under a scalar, and any block the parser could not read.

Both sides of the diff are **virtual**. Diffing the proposal against the `file:` URI would compare it with whatever an unsaved editor buffer happens to hold, and the bytes this flow read from disk are the bytes it is proposing to rewrite; showing anything else would be showing a diff of a different question.

`auditDryRun(shell, target)` is the read-only half of the same derivation — the `auditDryRun` request the Audit tab's "Preview the fix" button makes — and both it and `doFixIssue` go through one `deriveFix`, because a preview computed by a different code path from the write it previews is a preview of a different question. `auditStateFrom` / `auditStateFromScan` build the `AuditState` slice the dashboard renders: they live here rather than in `dashboardPanel.ts` because two things in that slice are derivations rather than copies — the collection per finding (the last segment of its page's registered folder, mirroring the private `collectionNameOf` in `core/content/audit.ts`) and the `scanned` count folded in beside the three severities — and a second copy of either would be a second answer to the same question.

`scanSite` also fills in `contentFolders` through `withPlatformDefaults` when the workspace registered none — that is what lets the audit read a sister site's 382 pages the first time it is opened rather than the zero folders it declared — and the `cfg` it returns, folders and all, is the one the fix is computed against.

### The same gate, for the fleet

`doToggleSwitch` and `doDispatchLane` in `fleet.ts` are the second pair, and they follow the diagram above line for line: `currentConfig()` uncached (with `zer0Cms.fleet.dispatchAllow` read from the settings layer alone through `settingsFleetDispatchAllow()`), `readFleetManifest()` from disk, `evaluateFleetGates()`, then `confirm()` naming the repository, the lane, the variable and the value. The dashboard's Fleet tab posts `{type:'command', id:'fleet.toggleSwitch', args:{lane}}` — a lane id and nothing else. A toggle's new value is `nextSwitchValue()` of the variable as GitHub reports it inside the action; `unknown` has no next value, so a failed read refuses rather than guesses.

**Decision D11** lives in this file's header. `extension.ts` still does no network and no auth on activation; the GitHub session is obtained lazily inside the action, every request goes through the `fetch` injected into `core/fleet/github.ts` (and is checked against `FLEET_PLAN` before it is sent), and no token is stored — the client asks VS Code for the session per request. Opening the tab is a passive read that never prompts; `fleet.refresh` is the interactive one.

---

## Trust is re-checked inside the function

Five paths in this extension can start a process (decision D13), and all five are now reachable from this directory: the content engine and the front-matter normalizer in `contract.ts`, a `placeholders[].script` through `content.ts`, the AI agent through `agent.ts`, and the site's own verification command through `audit.ts`. Every one re-asks `workspaceTrusted()` **inside the handler**. A `when` clause on a menu entry is a hint to the menu system; `capabilities.untrustedWorkspaces` drops only the *workspace-scoped* value of a restricted setting, so a `true` in somebody's user settings still arrives in a folder they just cloned; and the `zer0Cms:workspace:trusted` context key is a mirror that is only as fresh as the last time somebody set it. None of those is a gate.

- **`contract.ts`** — `requireTrust()` runs beside `requireWorkspace()` in all
three spawning handlers, and offers `workbench.trust.manage`. The core refuses a second time inside `runEngine`/`runNormalizer*`, as a value (`code: 1`, the reason on `stderr`), because "nothing rejects" is that module's older promise. Two checks on purpose: this one so a person reads a sentence, that one so no caller anywhere can spawn by forgetting. `engineFor(cfg)` is where trust and the interpreter's provenance are attached — `engineLayer()` over the settings snapshot's `cms` group and `zer0.json`'s, so the output channel can say whether the command about to run was named by a human or arrived with the clone.
- **`content.ts`** — `registerContentCommands` installs the core's trust
callback with `setPlaceholderTrust(workspaceTrusted)` at activation, because `src/core` cannot import `vscode` and its built-in default refuses. `createInto` then re-asks: creation still proceeds — editing front matter is allowed in an untrusted workspace — but when any placeholder names a script the person is told, before the file is written, that those tokens will come out as `<failed to process>`.
- **`agent.ts`** — `readyHost()` checks trust *before* `agent.enabled`, because
an untrusted folder is not a settings problem and offering "Enable it" would be the wrong sentence. `AgentPanel.start()` checks again, since the panel's composer reaches `start()` without passing through a command.
- **`audit.ts`** — `doVerify` is the fifth vector's handler. It re-asks
`workspaceTrusted()` before it even splits the argv, offers `workbench.trust.manage`, and then calls `runVerifyCommand` in `src/core/contract/engine.ts` rather than spawning: `node:child_process` is fenced by eslint to that file and `src/core/content/placeholders.ts`, which is what keeps the gate un-routable-around. The core refuses a second time inside the runner, as a value. An **unset** `zer0Cms.cms.verifyCommand` is a normal state rather than an error — most sites have no single verification entry point — and it is reported as the sentence that names the setting. `audit.fix` is deliberately *not* trust-gated: editing front matter is what decision D13 explicitly still allows in an untrusted workspace.

---

## Two bridges: how commands reach a webview

Three commands (`collapseSections`, `focusTags`, `focusCategories`) and three more (`agent.open` / `.start` / `.stop`) have their entire effect inside a webview that owns its own lifecycle. The host cannot do those things itself; it can only post a message to a view that may not exist yet.

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

this.registered.push(setAgentHost(this));   // open() / start(prompt?) / stop() / running
```

The agent panel keeps that registration in a list of its own rather than in the one `teardown()` empties when the webview closes: a closed panel must not uninstall the host that `agent.open` uses to reopen it. Until the constructor did this at all, nothing in `src/` ever installed a host and all four `zer0Cms.agent.*` commands ended at "the AI agent panel is not available in this window".

Both `set*` functions return a `Disposable` that unhooks only if the registration is still the current one, so a panel disposed after a replacement registered cannot unhook the replacement.

**With nothing registered the commands degrade, they do not throw.** `focusTags` still reveals the panel view (which is what causes the provider to resolve and register a bridge in the first place); `agent.start` says the agent is not available in this window. That is deliberate: the command palette has to keep working in a window where the panel was never opened and the agent was never enabled.

---

## Command arguments arrive in four shapes

The same command is invoked from the palette (no argument), the explorer context menu (a `Uri`), a tree row (a `TreeItem` subclass), and a webview (a string, or `{draftPath}`). `toFilePath(cfg, arg)` in `project.ts` and `draftPathFrom(cfg, arg)` in `governance.ts` are the two coercions; every handler starts with one of them and falls back to a `showQuickPick`.

A webview's string may be **workspace-relative** — it renders relative paths, so it names them that way — which is why the coercion takes a `Zer0Config`.

---

## The other things that are easy to get wrong

### `activeArticle()` saves a dirty document first

`writeArticle` writes to disk. An unsaved buffer over the same file is a second version racing to be last, and the editor wins whenever the user hits save. So `activeArticle()` calls `document.save()` before reading — visibly, not silently.

### Content-type and folder edits go to `zer0.json`, never to settings

Which folders hold content and what shape a page has is *repository* schema: it is reviewed in pull requests and has to be identical for everyone who checks the repository out. A user-scoped setting is none of those. `updateConfigFileJson` does a read-modify-write of the JSON rather than serialising a resolved `Zer0Config` back out, so hand-formatting and JSONC comments survive.

Folder paths are stored with the `[[workspace]]` token so a checkout at a different path still resolves.

### `resolveFolders()`, not `cfg.contentFolders`, when a real directory is needed

`cfg.contentFolders[].path` is absolute but may still be a **wildcard** (`[[workspace]]/pages/*`). `resolveFolders()` expands those into the concrete directories they stand for. Creating a file with the unexpanded form produces a directory literally named `*`, and prefix-matching a file against it never matches. Anything touching the disk uses the resolved list.

### `zer0Cms.init` has no `when` clause, and that is the fix

Upstream's equivalent was gated on a context key that only got set once a project config already existed — the initialize command was unreachable in exactly the workspace that needed it. Ours activates on `onCommand:` and is always visible. Do not add a `when`.

### The engine is optional and never rejects

`.cms/` absent is a normal state (decision D9). `runEngine` returns a code instead of throwing, and exit code `2` means "the normalizer found work", not "something broke". A refusal from the trust gate reads the same way — `code: 1` with the reason on `stderr` — and a run that hangs is killed after ten minutes. `contract.normalizePreview` writes nothing; the `--apply` variant is a separate command behind a modal that uses the word "rewrites", because it does, in bulk.

### Reports are untitled documents

Guard findings, engine output and publish previews open as untitled markdown. They are read once and closed. Writing them would litter the repository with files nobody asked for, and a preview that leaves artifacts behind has stopped being a preview.

---

## Adding a command

1. Add it to `contributes.commands` in `package.json`, with the `zer0-CMS`
   category, and to whatever menus should surface it.
2. `register(shell, 'my.command', handler)` in the file that owns its subject.
The wrapper turns a rejected promise into a notification instead of an unhandled rejection nobody sees.
3. Add the id to `ALL_COMMAND_IDS` in `index.ts`.
4. If a webview should be able to invoke it, add the literal to `CommandId` in
`src/webview/shared/protocol.ts` **and** a handler entry in the host's `Record<CommandId, Handler>`. Adding the literal alone grants nothing.
5. If it is privileged, it goes through `evaluateGates()` and a modal
confirmation, in the same function every other surface calls. Re-read state from disk first. A webview-only check is decoration.
