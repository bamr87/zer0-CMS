# `src/webview/dashboard` — the editor-tab surface

Five routes in one esbuild bundle (`dist/dashboard.js`), no framework, no runtime dependencies. `main.ts` boots, holds the view-local UI state and owns the route table; every other file here renders one part of the page.

```
main.ts        boot, gate order, route table, the section reconciler
header.ts      tab bar, toolbars, filters, sorting, grouping, pagination
contents.ts    grid / list cards, the item menu, bulk selection
structure.ts   the folder-tree browser
governance.ts  the Drafts route — queue + review pane
catering.ts    the Catering route — four distribution lanes
settings.ts    the Settings route — General + Content folders
welcome.ts     the Welcome route — four onboarding steps
```

The last four export `render(host, state)`: clear `host`, build the route into it from the `DashboardState` snapshot, return. They hold no snapshot of their own beyond the staged-edit map described below. `header.ts`, `contents.ts` and `structure.ts` instead take the `DashboardContext` `main.ts` owns, because they need the view-local state as well as the snapshot.

**Gate order on boot** (PLAN §3.2): `settings === null` → spinner;
`showWelcome || !initialized || contentFolders.length === 0` → Welcome; else
the persisted route. `showWelcome` is derived as `!initialized`, not remembered as a first-run flag — a remembered flag would deadlock against Welcome's "Open the dashboard" step, which clears only its own state.

## Boot and state (`main.ts`)

Two kinds of state, kept apart deliberately. Everything about *the workspace* — pages, drafts, lanes, settings, folders — arrives as one full `DashboardState` snapshot (decision D4) and is never mutated here. Everything about *this view of it* — route, layout, sort order, page number, ticked rows — lives in `DashboardUi`, the only mutable state in the bundle.

`patch()` is the single writer: it merges, mirrors the four durable preferences into workspace state via `setUiState`, bumps a revision counter and re-renders. That revision is what keeps each section's `stale()` down to two identity comparisons — a snapshot changes `state`, a click changes `revision`, and nothing else can change either. The mount spinner has the same five-second escape hatch the panel has: a dropped `ready` must cost an empty page you can refresh, never a loading bar with no way out.

**Search is a request, not a filter.** The box debounces at 500 ms and asks the host to run `searchPages` over the page index; filtering the posted array here would search whatever slice happened to arrive. Replies carry a sequence number, so a slow answer to an abandoned query cannot overwrite a fast answer to the current one. One consequence worth keeping: when a snapshot lands while a query is active the query is re-issued, because search hits are a copy of the index taken at request time and a stale hit can name a file the snapshot just reported deleted.

## Chrome (`header.ts`)

One tab bar for every route, plus — on Contents only — the five-row toolbar stack: create/refresh/search, the draft-state tabs with view switcher, filters and grouping and sorting, pagination, and the selection actions. The other four routes get the tab bar and nothing else, because a sort control above a draft queue is a control that does nothing.

Three behaviours here are contracts, not preferences: **sorting is disabled while a search query is active** (the host returns hits in relevance order and a sort would discard the ranking, so the control greys rather than silently ignoring you); **pagination is hidden while grouping is active and in Structure view**; and **View and Rename are enabled at exactly one selection** — not zero, not two — while Delete works on any non-empty selection and always confirms first.

There is no separate developer bar. `.developer__bar` is styled only in `panel.css`, which this bundle does not load, and inline `style` attributes are blocked by the CSP. The two `command:` URIs moved into the tab bar's right-hand action cluster, still gated on `state.developer` and still the only two the host's `enableCommandUris` allow-list contains.

## Contents (`contents.ts`, `structure.ts`)

`processPages()` is the whole data path and it is a straight line: pages → draft-state tab → filter dimensions → sort → group → page, with the host's search hits replacing the input wholesale when a query is running. It is memoised per context object in a `WeakMap`, and `header.ts` calls the same function to draw the pagination bar — so the strip that says "page 3 of 7" and the list that shows page 3 cannot disagree about what a page is. Search skips sorting; grouping disables paging.

`draftStateOf(page, now)` exists twice on purpose — here and in `src/dashboard/dashboardPanel.ts`, which computes the tab counts. The webview cannot import host code, so both files carry a comment naming the other; if one changes and the other does not, a tab promises a count it does not deliver.

**Card images are remote-only.** A card renders `<img>` for an `https:` or `data:` reference only. `localResourceRoots` is `media/` + `dist/` (PLAN §4.4), so a workspace image has no loadable URI here, and widening the roots across the repository for a thumbnail is not a trade worth making. Everything else draws the markdown glyph.

The item menu is View / Rename / Reveal in file explorer / Delete. Pin, Move to folder, Smart rename, Open on website and custom actions are all on PLAN §3.2's drop list. Delete confirms once, in the webview, and then goes to the OS trash host-side — it is not a governed action, there is no ledger record, and two modals per click is not a safety feature.

`structure.ts` draws the same pages arranged as they sit on disk, with a Home/Back/breadcrumb toolbar that scopes the tree. **Indentation is content, not style:** under `style-src <cspSource> 'nonce-…'` an inline `style` attribute is blocked — a nonce cannot apply to an attribute — so `style="padding-left:40px"` would silently do nothing. Depth is a `z-tree__indent` span of non-breaking spaces, and a future stylesheet can give that class a width and take over cleanly. **Create content names a folder, not a path to write:** the button posts `createContentInFolder` with a workspace-relative directory and the host resolves it, picks the type, applies the prefix chain and decides the filename.

## The two rules, on this surface

1. **No `innerHTML`.** Everything is `el()` and `textContent`. This surface
renders draft bodies, guard messages and file paths — text a human or an AI wrote — which is exactly why the strict CSP has to be more than decoration.
2. **The webview is UI, never the gate.** Every button posts
`{ type: 'command', id, args }` where `args` is a *target*: which draft, which folder, which setting key. There is no `force`, no `skipGuard`, no resolved artifact travelling back up the wire. The host re-reads state from disk and re-runs `evaluateGates()` in the same function the command palette calls.

## Drafts (`governance.ts`)

The queue is grouped by status in lifecycle order — Pending, Approved, Published, then an `Other` bucket that only appears when the queue holds a status nobody's lifecycle knows about. Group counts come from `DraftsState.counts`, which the host computes over the whole queue.

The review pane draws three things the core decided, not this file:

- **The fold rule at exactly 140 characters**, labelled
`… see more (feeds fold around 140 characters)` and styled as a dashed rule (`.z-review__fold`). It is drawn **only** when the trimmed commentary is longer than the fold — a 90-character post has no fold and drawing one would be a lie. The sentence names no vendor because decision D8 generalises publish away from any single network, and it is byte-identical to `FOLD_LABEL` in `src/webview/panel/governance.ts`: two surfaces, one rule, one wording. `FOLD` mirrors `core/governance/guard.ts`; that module reads the filesystem, so a browser bundle cannot import it. There are three copies of the number and they move together.
- **Guard findings with `info` filtered out.** `guardText()` always emits
exactly one `info` — the fold preview — so listing it would hang a permanent "finding" under every clean draft. The rule above *is* that finding.
- **The blocker note in the gate's own order.** `evaluateGates()` returns
blockers cheapest-and-most-fundamental first, so `Publish disabled: a; b.` already leads with what to fix first. Re-sorting or de-duplicating here would make this screen and the confirmation modal disagree about the same draft.

Approve is enabled only for a `pending` draft and relabels to `Approved` once the draft has moved on. Both Approve and Publish post `{ type:'command', id, args:{ draftPath } }` and nothing else.

## Catering (`catering.ts`)

This screen and `.cms/distribution/worklists/<date>-catering.md` are two renderings of one `CateringPlan`, so they use the same sentences and the same arithmetic. The empty states arrive in `CateringState.emptyStates`, which the host builds by importing `LANE_EMPTY_STATES` from `core/catering/worklist.ts` — the module that also writes them into the generated file, so there is exactly one definition behind both. `EMPTY_STATES` here is the fallback for a host that sent a blank, and it is the only copy of those sentences that is not the export: this bundle cannot reach `worklist.ts`, which imports `contract.ts`, which imports `node:fs`. Lane headings and hints, and `formatThousands` / `formatPercent` / `roundHalfEven` — Python's half-to-even rounding included — are re-derived here for the same reason. Each copy carries a comment naming its twin; edit both in one commit.

A health of `-1` means "the engine never scored this page". It renders as an em dash (`.z-lane__unknown`), exactly as the worklist's `healthCell` writes it, and never as `-1`. **Generate worklist** posts `catering.worklist`; the host rebuilds the plan from disk and writes the file, so this screen's numbers are never the input to it. An absent `.cms/` is a normal state (D9) and renders as an empty state offering **Run CMS engine**.

## Settings (`settings.ts`)

Two sections, one write op.

*General* renders `SettingsState.general` — the host names every key, so the webview can only ever hand back a key the host itself offered. Edits are **staged** in a module-level map and flushed by **Save**, one `{ type:'command', id:'updateSetting', args:{ key, value } }` per changed key. That is what makes "Save is disabled until something changed" a fact about the data rather than a flag somebody has to remember to set. The map survives a state snapshot (a half-typed page size must not be erased by an unrelated refresh) and an entry clears itself the moment the host reports the value it was asking for — so a refused write visibly stays dirty. **Cancel** drops the staged edits and repaints.

*Content folders* lists the registered folders with a content-type menu and an unregister button. Register/unregister post `registerFolder` / `unregisterFolder`; with a `{ path }` target they skip the folder dialog. Content-type assignment posts `updateSetting` with:

```jsonc
{ "key": "contentFolder.contentTypes", "path": "<absolute folder path>", "value": ["default"] }
```

`value` is the folder's whole content-type list after the toggle, and `path` names which folder. The host owns whether that key exists — see `FOLDER_CONTENT_TYPES_KEY`.

## Welcome (`welcome.ts`)

Four steps, not the fork's nine: framework presets, network-fetched configuration templates, the Astro collection walker, the taxonomy import, the Git question and the sponsor links are all gone. Completion is derived from real state, never from a "you clicked it" flag:

| id | Step | Complete when |
|---|---|---|
| `init` | Initialize project | `state.initialized` — the config file is on disk |
| `folder` | Register a content folder | a folder is registered |
| `contentType` | Create your first content type | a content type is defined |
| `dashboard` | Open the dashboard | there is content to show |

Exactly one step is `is-active`: the first that is not finished.

The host may refine any of them by sending `WelcomeState.steps`; an entry whose `id` matches one above overrides that step's name, description, status and action. It cannot add or remove steps — four is the shape of the screen.

**Open the dashboard** clears this screen's own state: it drops the persisted `route`, posts `{ type:'setUiState', key:'welcome', value:'false' }` so the host stops forcing the welcome gate, and asks for a fresh snapshot with `refresh`. The host still owns the gate — if the project genuinely is not set up it sends `showWelcome` again and we land right back here, which is correct.

## Styling

Every class emitted here is dressed by `media/dashboard.css` (and `media/base.css` for the kernel widgets). The dashboard bundle does **not** load `media/panel.css`, so the panel's `.z-pill--*` status variants are not available: draft status uses `.z-status` with `--scheduled` for `pending` and `--draft` for an unrecognised status. Only `media/tokens.css` may name a VS Code theme variable.
