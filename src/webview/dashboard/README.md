# `src/webview/dashboard` — the editor-tab surface

Five routes in one esbuild bundle (`dist/dashboard.js`), no framework, no
runtime dependencies. `main.ts` boots, holds the view-local UI state and owns
the route table; every other file here renders one part of the page.

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

The last four export `render(host, state)`: clear `host`, build the route into
it from the `DashboardState` snapshot, return. They hold no snapshot of their
own beyond the staged-edit map described below.

**Gate order on boot** (PLAN §3.2): `settings === null` → spinner;
`showWelcome || !initialized || contentFolders.length === 0` → Welcome; else
the persisted route.

## The two rules, on this surface

1. **No `innerHTML`.** Everything is `el()` and `textContent`. This surface
   renders draft bodies, guard messages and file paths — text a human or an AI
   wrote — which is exactly why the strict CSP has to be more than decoration.
2. **The webview is UI, never the gate.** Every button posts
   `{ type: 'command', id, args }` where `args` is a *target*: which draft,
   which folder, which setting key. There is no `force`, no `skipGuard`, no
   resolved artifact travelling back up the wire. The host re-reads state from
   disk and re-runs `evaluateGates()` in the same function the command palette
   calls.

## Drafts (`governance.ts`)

The queue is grouped by status in lifecycle order — Pending, Approved,
Published, then an `Other` bucket that only appears when the queue holds a
status nobody's lifecycle knows about. Group counts come from
`DraftsState.counts`, which the host computes over the whole queue.

The review pane draws three things the core decided, not this file:

- **The fold rule at exactly 140 characters**, labelled
  `… see more (LinkedIn folds around 140 characters)` and styled as a dashed
  rule (`.z-review__fold`). It is drawn **only** when the trimmed commentary is
  longer than the fold — a 90-character post has no fold and drawing one would
  be a lie. `FOLD` mirrors `core/governance/guard.ts`; that module reads the
  filesystem, so a browser bundle cannot import it. If one moves, move the
  other.
- **Guard findings with `info` filtered out.** `guardText()` always emits
  exactly one `info` — the fold preview — so listing it would hang a permanent
  "finding" under every clean draft. The rule above *is* that finding.
- **The blocker note in the gate's own order.** `evaluateGates()` returns
  blockers cheapest-and-most-fundamental first, so
  `Publish disabled: a; b.` already leads with what to fix first. Re-sorting or
  de-duplicating here would make this screen and the confirmation modal
  disagree about the same draft.

Approve is enabled only for a `pending` draft and relabels to `Approved` once
the draft has moved on. Both Approve and Publish post
`{ type:'command', id, args:{ draftPath } }` and nothing else.

## Catering (`catering.ts`)

This screen and `.cms/distribution/worklists/<date>-catering.md` are two
renderings of one `CateringPlan`, so they use the same sentences and the same
arithmetic: lane headings and hints are `core/catering/worklist.ts`'s, the
empty states arrive in `CateringState.emptyStates` (sourced from that module;
`EMPTY_STATES` here is only the fallback for a host that sent a blank), and
`formatThousands` / `formatPercent` / `roundHalfEven` are re-derived — Python's
half-to-even rounding included — because the worklist's copies sit behind a
module that touches the filesystem.

A health of `-1` means "the engine never scored this page". It renders as an em
dash (`.z-lane__unknown`), exactly as the worklist's `healthCell` writes it,
and never as `-1`. **Generate worklist** posts `catering.worklist`; the host
rebuilds the plan from disk and writes the file, so this screen's numbers are
never the input to it. An absent `.cms/` is a normal state (D9) and renders as
an empty state offering **Run CMS engine**.

## Settings (`settings.ts`)

Two sections, one write op.

*General* renders `SettingsState.general` — the host names every key, so the
webview can only ever hand back a key the host itself offered. Edits are
**staged** in a module-level map and flushed by **Save**, one
`{ type:'command', id:'updateSetting', args:{ key, value } }` per changed key.
That is what makes "Save is disabled until something changed" a fact about the
data rather than a flag somebody has to remember to set. The map survives a
state snapshot (a half-typed page size must not be erased by an unrelated
refresh) and an entry clears itself the moment the host reports the value it
was asking for — so a refused write visibly stays dirty. **Cancel** drops the
staged edits and repaints.

*Content folders* lists the registered folders with a content-type menu and an
unregister button. Register/unregister post `registerFolder` /
`unregisterFolder`; with a `{ path }` target they skip the folder dialog.
Content-type assignment posts `updateSetting` with:

```jsonc
{ "key": "contentFolder.contentTypes", "path": "<absolute folder path>", "value": ["default"] }
```

`value` is the folder's whole content-type list after the toggle, and `path`
names which folder. The host owns whether that key exists — see
`FOLDER_CONTENT_TYPES_KEY`.

## Welcome (`welcome.ts`)

Four steps, not the fork's nine: framework presets, network-fetched
configuration templates, the Astro collection walker, the taxonomy import, the
Git question and the sponsor links are all gone. Completion is derived from
real state, never from a "you clicked it" flag:

| id | Step | Complete when |
|---|---|---|
| `init` | Initialize project | `state.initialized` — the config file is on disk |
| `folder` | Register a content folder | a folder is registered |
| `contentType` | Create your first content type | a content type is defined |
| `dashboard` | Open the dashboard | there is content to show |

Exactly one step is `is-active`: the first that is not finished.

The host may refine any of them by sending `WelcomeState.steps`; an entry whose
`id` matches one above overrides that step's name, description, status and
action. It cannot add or remove steps — four is the shape of the screen.

**Open the dashboard** clears this screen's own state: it drops the persisted
`route`, posts `{ type:'setUiState', key:'welcome', value:'false' }` so the
host stops forcing the welcome gate, and asks for a fresh snapshot with
`refresh`. The host still owns the gate — if the project genuinely is not set
up it sends `showWelcome` again and we land right back here, which is correct.

## Styling

Every class emitted here is dressed by `media/dashboard.css` (and
`media/base.css` for the kernel widgets). The dashboard bundle does **not**
load `media/panel.css`, so the panel's `.z-pill--*` status variants are not
available: draft status uses `.z-status` with `--scheduled` for `pending` and
`--draft` for an unrecognised status. Only `media/tokens.css` may name a VS
Code theme variable.
