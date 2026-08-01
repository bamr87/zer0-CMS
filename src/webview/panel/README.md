# `src/webview/panel` — the metadata panel's front end

The sidebar view, in six modules plus the field library. Bundled to `dist/panel.js` as an esbuild IIFE with zero dependencies; hosted by `src/panel/panelProvider.ts`, which is where the snapshot comes from and where every intent posted here is decided.

| File | What it draws |
|---|---|
| `main.ts` | Boot, section order, scroll restore, and the three imperative host messages. |
| `chrome.ts` | The collapsible frame and its collapse memory, the buttons, the loading overlay, and the three rows that are not sections. |
| `governance.ts` | Draft status, guard findings, the fold rule, ledger state, the three gated buttons. **New — not in the fork.** |
| `metadata.ts` | The content-type hint, the front-matter error state, and the field list. |
| `seo.ts` | The insights table, the keywords table, the hidden-chrome keyword editor. |
| `actions.ts` | Actions, Recently modified, Global settings, Other actions. |
| `fields/` | The eighteen field controls. See its own README. |

## The ten rows

PLAN §3.1, top to bottom. `main.ts` mounts all ten once; each decides for itself whether a given snapshot gives it anything to draw.

| # | Section id | Collapse id | Shown when |
|---|---|---|---|
| 0 | `developer` | — | `state.developer` |
| 1 | `initialize` | — | `!state.initialized` |
| 2 | `governance` | `governance` / `base_governance` | in `sections` and `governance.enabled` |
| 3 | `metadata` | `metadata` | in `sections` and a file is open |
| 4 | `seo` | `seo` | in `sections`, SEO on, a file is open |
| 5 | `actions` | `actions` | in `sections` |
| 6 | `recent` | `content` / `base_content` | in `sections` and the list is non-empty |
| 7 | `settings` | `settings` / `base_settings` | in `sections` |
| 8 | `other` | `other_actions` / `base_other_actions` | in `sections` |
| 9 | `empty` | — | none of rows 2 and 5–8 is enabled |

**Section id ≠ collapse id.** The section id is the configuration vocabulary (`recent`, `other`); the collapse key is the fork's (`content`, `other_actions`), kept so an upgrade preserves the sections a user had closed.

**Order comes from configuration, position from the plan.** The seven configurable sections mount in the plan's order and are re-ordered to match `state.sections` whenever that list itself changes — moving the existing hosts, not rebuilding them, and only when the joined id list differs.

## Collapse memory

`collapseKey(id, hasFile)` is the whole rule: `hasFile` gives `<id>`, otherwise `base_<id>`. Two views of the panel, two memories — "I always keep Metadata closed while editing" and "I always keep Other actions open on the General view" are different preferences and the fork treated them as such.

State lives in `Messenger.isCollapsed`/`setCollapsed`, which write `collapse_<key>` into webview state *and* mirror it to the host through `setUiState`. Default is open; only the literal string `'false'` closes a section, so an id nobody has ever toggled starts open.

`closeAllSections()` handles the `collapseAll` host message — the `zer0Cms.collapseSections` title-bar command. Handles are pruned by `isConnected` on every use, because the reconciler rebuilds a stale section by clearing its host and the old handle's element is detached, not disposed.

## The loading overlay

Painted on mount and cleared either by the first snapshot or **after five seconds**, whichever comes first. A dropped `ready` — the host was mid-refresh, the view was hidden while the message was in flight — then costs an empty panel that the next state fills in, instead of a loading bar with no way out. The force-clear logs why.

## The governance section

New in zer0-CMS; it replaces the fork's Git actions block.

- Guard findings are listed at `error` and `warning` only. **`info` is filtered
out and drawn as the fold instead** — `guardText()` always emits exactly one `info`, the fold marker, so listing it would put a permanent "finding" under every clean draft.
- The fold rule is drawn at **140 characters** (`FOLD`, mirrored from
`src/core/governance/guard.ts`, which cannot be imported into a browser bundle because it reads the filesystem). Below the fold the commentary is muted, not hidden: the author still has to read it, they just need to know which half a reader sees first. The rule is only drawn when there *is* a second half.
- The blocker note is `blockerSummary()` verbatim in a UI frame:
`Publish disabled: a; b.` The gate orders its blockers most-fundamental-first, so the sentence already leads with what to fix first. Re-sorting it here would make the panel and the modal disagree about the same draft.
- Approve is disabled unless the status is `pending`; Publish is disabled when
  there are blockers.
- **The three buttons post an intent and a target and nothing else** —
`{type:'command', id:'draft.publish', args:{draftPath}}`. There is no payload that could carry `force`, no flag that could skip the guard, and no way to name a draft that is not on disk. Decision D5: a button that renders enabled when it should not is a cosmetic bug, not an escalation.

## The SEO section

Everything numeric is computed by `core/content/seo.ts` and arrives already decided. This module draws it and re-derives nothing — the same numbers appear in the dashboard and in the MCP `zer0_status` tool, and three implementations of "is this title too long" is three chances to disagree.

- A threshold of `<= 0` suppresses its row, host-side. An absent row is a
  deliberate "do not tell me about this", not a missing measurement.
- **Article length is never validated**: it has a recommendation and no
  `isValid`, so it renders the em-dash spacer rather than a tick or a warning.
- The insights table is two-state, never red. Advice you cannot ignore is a
  gate, and gates live in the governance section.
- Keyword density is green in `[0.75, 1.5)` and amber outside it; a keyword with
  no word count to divide by shows nothing rather than `0.00 %`.
- The keyword editor is the fork's best odd idea: the picker's label and pill
list are hidden by CSS so the section shows one bare input, while the pills live in the table above where they can carry their own scores.

## Talking to the host

Six message shapes, no more (`shared/protocol.ts`). What this directory sends:

- `ready` — once, at boot.
- `command` — every button. An id from the closed union, plus a target.
- `updateField` — a field value, whole. The host does the line surgery.
- `setUiState` — the collapse map, mirrored for the host to persist.
- `log` — anything worth a line in the output channel.

What it receives: one full `state` snapshot, plus `collapseAll`, `focus` and `progress`. `focus` and field-scoped `progress` are routed by `metadata.ts`, which keeps the live widgets in a list and disposes them on every rebuild.

## Styling

Every class emitted here is dressed by `media/panel.css` (and `media/base.css` for the kernel widgets). Only `media/tokens.css` may name a VS Code theme variable. No `innerHTML` — eslint fails the build on it.
