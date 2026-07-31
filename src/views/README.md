# `src/views/` — the four tree views

| File | View id | Shown when | Levels |
|---|---|---|---|
| `draftsTree.ts` | `zer0Cms.drafts` | `zer0Cms:governance:enabled` | one |
| `contentTree.ts` | `zer0Cms.content` | always | one |
| `cateringTree.ts` | `zer0Cms.catering` | `zer0Cms:contract:present` | **two** |
| `publishedTree.ts` | `zer0Cms.published` | `zer0Cms:governance:enabled` | one |

All four live in the `zer0-cms` activity-bar container, below the metadata
panel webview.

---

## The one rule: no tree reads the filesystem

Every provider renders `store.current()` and nothing else. Not `fs`, not
`workspace.findFiles`, not a cache of its own.

That is not a style preference. Four trees, the metadata panel and the
dashboard all need the same answers — what pages exist, what is in the queue,
what the ledger says was published, what the `.cms/` contract holds. Six
independent derivations would mean six scans per keystroke and, worse, six
chances to disagree with each other: a Publish button enabled in the panel and
a row missing from the tree, both "correct" against different reads of the same
directory.

`WorkspaceStore` reads the disk once into a `Snapshot`, coalesces concurrent
refreshes into a single rebuild, and fires `onDidChange`. Each provider forwards
that event to `onDidChangeTreeData`. A tree is a projection; if you need a
number it does not have, add it to the snapshot.

---

## `contextValue` is the entire menu-gating mechanism

VS Code decides which context-menu items a row gets by matching
`when: "viewItem == …"` against the string a `TreeItem` sets. There is no
compiler between the two files, so the formats are pinned here and in
`package.json`, and by a test.

| Tree | `contextValue` | What `package.json` puts on it |
|---|---|---|
| Drafts | `` `draft-${status}` `` | `/^draft-/` → Review (inline), Guard, Preview |
| | `draft-pending` | + Approve (inline) |
| | `` /^draft-(pending\|approved)$/ `` | + Publish (inline) |
| Content | `content-article` | `/^content-article/` → New draft from content |
| | `content-article-posted` | same — see below |
| Distribution | `catering-lane` | nothing (it is a header) |
| | `catering-item` | New draft from content |
| | `catering-signal` | nothing (there is no file behind it) |
| Published | `published-entry` | nothing |

`draft.status` is already normalised — `readDraft` lowercases and trims it and
defaults it to `pending` — so `draft-Pending` cannot happen. An unrecognised
status still produces a well-formed `draft-<status>`, which matches the
`/^draft-/` menus and none of the action ones. That is the right failure: you
can inspect a draft in a state nobody planned for, and you cannot approve it.

**A visible button is not permission.** `viewItem == draft-pending` says the row
is the right *shape* for Approve. Whether this draft may be approved is decided
by `commands/governance.ts`, which re-reads the file from disk and re-runs
`evaluateGates()` before it writes (decision D5). The menus are an affordance.

### Why `content-article-posted` exists but is not gated against

The Content view distinguishes content the ledger has already seen (via
`snapshot.publishedSourceFiles`, built from `shareEntries()` — the only correct
way to enumerate a ledger) from content it has not. The distinction is
informational: the list tells you at a glance what has never left the
repository. Drafting a second update about a piece you already published is a
normal thing to want, which is why the menu matches `/^content-article/` and
covers both.

---

## Per-tree notes

### Drafts — sorted for a reviewer, not for a filesystem

`pending` → `approved` → everything else, then by path. What is waiting on a
human comes first; what is waiting on a machine comes second; what is done
sinks. Ranks are coarse on purpose — an unrecognised status sorts last rather
than throwing the list into a shape nobody predicted.

### Content — health-ranked, and `-1` is not zero

Rows come from `snapshot.distributable`, which is already best-health-first.
This file does not re-sort: a second opinion here would put the tree out of step
with the dashboard and the worklist.

A health of `-1` means *the engine never scored this* — the workspace has no
`.cms/`, and the page index is standing in for it with the honestly degraded
distributable rule "not a draft and has a title" (decision D9). It renders as
`health —`, never as `health 0`.

### Distribution — the only two-level tree

Four lanes, matching `renderWorklist`'s headings verbatim. A lane with rows is
`Expanded` with the count as its description; an empty one is `None` with the
description `nothing yet` — collapsed to a leaf so the chevron does not invite a
click that reveals nothing. The lane's tooltip carries the worklist's own prose,
including the two different reasons Lane B can be empty (no audience data at
all, versus not enough observations per topic).

Signal rows call `formatThousands`, `formatPercent` and `rateOf` from
`core/catering/worklist.ts` — the same functions that render
`.cms/distribution/worklists/<date>-catering.md`. If the tree computed its own
percentages the screen and the exported file would drift apart at the second
decimal and nobody would notice for a month. Those formatters are also
locale-free by construction, so the numbers do not change when the machine's
language does.

Lane truncation (`LANE_LIMITS`) already happened inside `buildCatering`, so the
tree slices nothing: it shows exactly the rows that would be exported.

### Published — string-compared timestamps

`posted_at` descending, by `localeCompare`. That works because the stamps are
`utcStamp()` — fixed-width, UTC, second precision — so lexical order *is*
chronological order. Parsing them into `Date`s would buy nothing and would turn
a malformed stamp into a `NaN` that sorts unpredictably instead of simply
sorting last.

Only rows that name a `source_file` get a command. A ledger written by the
Python lane may not carry one, and a row that silently opened the wrong file
would be worse than a row that opens nothing.

---

## Conventions every item follows

- **Label** is the human name (title), falling back to the path. **Description**
  is the metadata strip, `·`-separated. **Tooltip** is a `MarkdownString` with
  the detail.
- **`resourceUri`** is set whenever a real file backs the row, so file
  decorations (git status, problems) show up for free.
- **`command`** is `zer0Cms.openFile` with an absolute path — not
  `vscode.open` — so every "open this" in the extension goes through one
  handler, the one that also copes with a workspace-relative path arriving from
  a webview.
- **`id`** is stable across refreshes (the path, or `lane-<id>-<path>`), so the
  tree keeps its expansion and selection when the store rebuilds.
- In a folderless window `workspaceRoot` is `''`. Rows render, but nothing is
  resolved against the process's cwd and nothing is clickable.
