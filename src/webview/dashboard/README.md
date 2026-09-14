# `src/webview/dashboard` — the editor-tab surface

Eleven routes in one esbuild bundle (`dist/dashboard.js`), no framework, no runtime dependencies. `main.ts` boots, holds the view-local UI state and owns the route table; every other file here renders one part of the page.

Eleven routes are *declared* — `DASHBOARD_ROUTES` in `shared/protocol.ts`, in final display order — and a route is served once something can render it. Until then `main.ts`'s renderer table holds a `notAvailable` placeholder: compile-complete and unreachable, because a route absent from `state.tabs` degrades to Contents. `src/test/routes.test.ts` pins the invariant that keeps the two lists from drifting — **the tab ids are a subset of the routes, in the same relative order**. Subset without order gives you a tab bar whose sequence depends on merge order; order without subset gives you a tab that routes nowhere.

```
main.ts        boot, gate order, route table, the section reconciler
header.ts      tab bar, the site switcher, toolbars, filters, sorting, grouping, pagination
sites.ts       the Sites route — one row per open folder, and which one is active
contents.ts    grid / list cards, the item menu, bulk selection
structure.ts   the folder-tree browser
governance.ts  the Drafts route — queue + review pane
audit.ts       the Audit route — findings list + detail pane, and the fix-it
catering.ts    the Catering route — four distribution lanes
fleet.ts       the Fleet route — one repository's AI lanes, five gated buttons
harness.ts     the Harness route — agents, skills, workflows, the join, the disagreements
workflows.ts   the Workflows route — lane passports, the lane form, the write preview
monitor.ts     the Monitor route — the whole roster as a matrix, read-only
settings.ts    the Settings route — General + Content folders
welcome.ts     the Welcome route — four onboarding steps
```

The last ten export `render(host, state)`: clear `host`, build the route into it from the `DashboardState` snapshot, return. They hold no snapshot of their own beyond the staged-edit map described below. `header.ts`, `contents.ts` and `structure.ts` instead take the `DashboardContext` `main.ts` owns, because they need the view-local state as well as the snapshot.

**Gate order on boot** (PLAN §3.2): `settings === null` → spinner;
`showWelcome || !initialized || contentFolders.length === 0` → Welcome; else
the persisted route. `showWelcome` is derived as `!initialized`, not remembered as a first-run flag — a remembered flag would deadlock against Welcome's "Open the dashboard" step, which clears only its own state.

## Boot and state (`main.ts`)

Two kinds of state, kept apart deliberately. Everything about *the workspace* — pages, drafts, lanes, settings, folders — arrives as one full `DashboardState` snapshot (decision D4) and is never mutated here. Everything about *this view of it* — route, layout, sort order, page number, ticked rows — lives in `DashboardUi`, the only mutable state in the bundle.

`patch()` is the single writer: it merges, mirrors the four durable preferences into workspace state via `setUiState`, bumps a revision counter and re-renders. That revision is what keeps each section's `stale()` down to two identity comparisons — a snapshot changes `state`, a click changes `revision`, and nothing else can change either. The mount spinner has the same five-second escape hatch the panel has: a dropped `ready` must cost an empty page you can refresh, never a loading bar with no way out.

**Search is a request, not a filter.** The box debounces at 500 ms and asks the host to run `searchPages` over the page index; filtering the posted array here would search whatever slice happened to arrive. Replies carry a sequence number, so a slow answer to an abandoned query cannot overwrite a fast answer to the current one. One consequence worth keeping: when a snapshot lands while a query is active the query is re-issued, because search hits are a copy of the index taken at request time and a stale hit can name a file the snapshot just reported deleted.

## Chrome (`header.ts`)

One tab bar for every route, plus — on Contents only — the five-row toolbar stack: create/refresh/search, the draft-state tabs with view switcher, filters and grouping and sorting, pagination, and the selection actions. A sort control above a draft queue is a control that does nothing, so no other route gets Contents' stack.

Every other route may register **one** toolbar row of its own through `setRouteToolbar(route, ctx => node | null)`, called at module scope by the route that owns it. Monitor has filters, and they are not Contents' filters. Audit and Workflows register nothing — Audit because its three filters narrow *the list in its own left pane*, so they live beside that list rather than in the chrome above the tab bar, and its view-local state is module-private rather than shared with `DashboardUi.filters` (a severity filter and a folder filter have no business in the same map); Workflows because a catalogue of seventeen lanes is one table that fits, and a filter bar over it would be chrome with nothing to narrow. `header.ts` never learns what is in a route's toolbar and never imports a route — the alternative is a cycle the moment a route wants a shared control back. A route that registers nothing gets the bare tab bar, exactly as before, and `contents` is not registerable because its five persisted keys (`sorting`, `grouping`, `page`, `view`) are read here.

Three behaviours here are contracts, not preferences: **sorting is disabled while a search query is active** (the host returns hits in relevance order and a sort would discard the ranking, so the control greys rather than silently ignoring you); **pagination is hidden while grouping is active and in Structure view**; and **View and Rename are enabled at exactly one selection** — not zero, not two — while Delete works on any non-empty selection and always confirms first.

The action cluster also carries the **site switcher** in a multi-root window — a `menuButton` of the open folders, with the active one checked. It sits in the chrome rather than inside the Sites tab because "which repository am I about to publish into?" is a question every tab needs answered. Selecting an entry posts `site.setActive {site: '<id>'}`: an id, which the host validates against `SiteRegistry` because a list can go stale between a render and a click. Below two folders the switcher is absent entirely.

There is no separate developer bar. `.developer__bar` is styled only in `panel.css`, which this bundle does not load, and inline `style` attributes are blocked by the CSP. The two `command:` URIs moved into the tab bar's right-hand action cluster, still gated on `state.developer` and still the only two the host's `enableCommandUris` allow-list contains.

## Contents (`contents.ts`, `structure.ts`)

`processPages()` is the whole data path and it is a straight line: pages → draft-state tab → filter dimensions → sort → group → page, with the host's search hits replacing the input wholesale when a query is running. It is memoised per context object in a `WeakMap`, and `header.ts` calls the same function to draw the pagination bar — so the strip that says "page 3 of 7" and the list that shows page 3 cannot disagree about what a page is. Search skips sorting; grouping disables paging.

`draftStateOf(page, now)` exists twice on purpose — here and in `src/dashboard/dashboardPanel.ts`, which computes the tab counts. The webview cannot import host code, so both files carry a comment naming the other; if one changes and the other does not, a tab promises a count it does not deliver.

**Card images are remote-only.** A card renders `<img>` for an `https:` or `data:` reference only. `localResourceRoots` is `media/` + `dist/` (PLAN §4.4), so a workspace image has no loadable URI here, and widening the roots across the repository for a thumbnail is not a trade worth making. Everything else draws the markdown glyph.

The item menu is View / Rename / Reveal in file explorer / Delete. Pin, Move to folder, Smart rename, Open on website and custom actions are all on PLAN §3.2's drop list. Delete confirms once, in the webview, and then goes to the OS trash host-side — it is not a governed action, there is no ledger record, and two modals per click is not a safety feature.

`structure.ts` draws the same pages arranged as they sit on disk, with a Home/Back/breadcrumb toolbar that scopes the tree. **Indentation is content, not style:** under `style-src <cspSource> 'nonce-…'` an inline `style` attribute is blocked — a nonce cannot apply to an attribute — so `style="padding-left:40px"` would silently do nothing. Depth is a `z-tree__indent` span of non-breaking spaces, and a future stylesheet can give that class a width and take over cleanly. **Create content names a folder, not a path to write:** the button posts `createContentInFolder` with a workspace-relative directory and the host resolves it, picks the type, applies the prefix chain and decides the filename.

## Sites (`sites.ts`)

One row per open workspace folder: its platform (with the zer0-mistakes *overlay* beside Jekyll rather than instead of it — decision D12), whether it carries a project config, its registered content roots, its page and draft counts, whether it carries a fleet manifest, and two buttons.

Two things on this screen are load-bearing.

**Counts are honest about not knowing.** Constructing a `WorkspaceStore` per folder must not become a scan per folder at activation, so a site that has never been read renders `—` and a `not scanned` detection source, never `0 pages`. An unexamined site and an empty one are different facts, and rendering both as zero is how a console starts lying quietly.

**Both buttons post an id.** `Make active` and `Preview` send `{site: '<id>'}` and nothing else — not a path, not a config, not "and also trust it". Their disabled states (`already active`; `this workspace is not trusted`; `a vscode-vfs folder has no local process to start`) are the same sentences `src/commands/site.ts` uses when it refuses, and the ones there are the decision (decision D5).

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

## Audit (`audit.ts`)

The Drafts grid again — `.z-audit` is applied *beside* `.z-drafts` rather than instead of it, so the two screens cannot drift apart on breakpoint, gutter or column width. Findings on the left, one finding's detail on the right, and a summary strip above both: three `statusPill` counts, a `keyValueList` of provenance, and the two route-level actions.

**Three claims this screen is allowed to make, and one it is not.** It may say how many files were scanned, how many findings there are by severity, and how many by rule. It may **not** show a health score: the audit does not compute one, `pageToRecord` keeps `health: -1` beside these issues, and a grade derived from a count would be a number nobody measured (decision D9).

**The schema source is load-bearing, not a caption.** `title` is "required" in a very different sense when `frontmatter_schema.yml` said so than when the platform profile's own defaults did, so both the summary strip and the detail pane carry a "Required by" row spelling out which one answered. `SCHEMA_SOURCE_PROSE` is the webview's copy of `describeSchemaSource` in `src/commands/audit.ts` — one sentence written twice, because this bundle cannot import host code. Edit both in one commit. A site with no schema at all still gets an audit; it just gets a different sentence.

**Three states, three screens.** No `audit` slice or `ran: false` is "this site has not been audited yet", with a button that runs it — not a blank pane. `ran: true` with an empty issue list is "this site is clean" — an `emptyState`, not an error. Anything else is the two-pane view. "The audit ran and found nothing" and "the audit never ran" are different facts and they look different.

**Fix posts `{path, kind}` and nothing else.** It is a `gatedButton`; a finding with no mechanical repair renders it disabled with the reason, and the advice itself is already drawn under "What to do". `fixable` here is the host's advisory — `doFixIssue` re-reads the configuration, re-reads the site from disk, re-runs `auditPage` for that file and looks the finding up again before it derives a change set, so a stale `true` in this slice costs a refusal and can never cost a bad write.

**Preview the fix is a request, not a slice.** It asks the host for `auditDryRun` with the same `{path, kind}` and expects back exactly what `dryRunFix` returned: `{before, after}`, or `{refused}`. The hunk drawn from that pair is computed here by trimming the common prefix and suffix — which is the whole diff for line surgery — and rendered through `diffView`. It is a rendering, not a decision: the host still opens the authoritative diff in a real editor before it writes anything, and a reply that arrives after the selection has moved on is dropped rather than painted over the current one.

**Run verify** is a `gatedButton` too, blocked with the sentence that names `zer0Cms.cms.verifyCommand` when the site declares none — a normal state, since most sites have no single verification entry point.

The list caps at 300 rows and says how many it is not drawing. A per-rule tally sits under it, over `dataTable`, counting what the filters currently show rather than the whole site — a tally that ignores the filters above it is a tally of a different question.

## Catering (`catering.ts`)

This screen and `.cms/distribution/worklists/<date>-catering.md` are two renderings of one `CateringPlan`, so they use the same sentences and the same arithmetic. The empty states arrive in `CateringState.emptyStates`, which the host builds by importing `LANE_EMPTY_STATES` from `core/catering/worklist.ts` — the module that also writes them into the generated file, so there is exactly one definition behind both. `EMPTY_STATES` here is the fallback for a host that sent a blank, and it is the only copy of those sentences that is not the export: this bundle cannot reach `worklist.ts`, which imports `contract.ts`, which imports `node:fs`. Lane headings and hints, and `formatThousands` / `formatPercent` / `roundHalfEven` — Python's half-to-even rounding included — are re-derived here for the same reason. Each copy carries a comment naming its twin; edit both in one commit.

A health of `-1` means "the engine never scored this page". It renders as an em dash (`.z-lane__unknown`), exactly as the worklist's `healthCell` writes it, and never as `-1`. **Generate worklist** posts `catering.worklist`; the host rebuilds the plan from disk and writes the file, so this screen's numbers are never the input to it. An absent `.cms/` is a normal state (D9) and renders as an empty state offering **Run CMS engine**.

## Fleet (`fleet.ts`)

One table — lane · kind · harness · triggers and guardrails · switch · last run · audit · cost · five buttons — plus an in-flight strip, the merge-policy block, the drift table and the token list, over `FleetState`, which the host builds from `fleet.manifest.yml` and its last live read of GitHub. The tab is absent from `state.tabs` while `zer0Cms.fleet.enabled` is off, so a persisted `fleet` route degrades to Contents.

**Switch, Dispatch, Re-run failure, Cancel run and Enable/disable workflow** are `gatedButton`s posting `{ type:'command', id, args:{ repo, lane } }` — a repository slug and a lane id, and nothing else. Not the new switch value (the host derives it from the variable it fetches inside the action), not a run id (the host takes that from what the last Refresh read), not a ref, not a `force`. The blockers under a disabled button are the host's advisory `evaluateFleetGates()` in the gate's own order, verbatim, for the reason the Drafts route keeps the publish gate's order: re-sorting here would make this screen and the confirmation modal disagree about the same lane. The three run verbs additionally carry one *courtesy* blocker this view derives from the wire — "nothing has been read from this repository yet" — because a button certain to be refused should look like one. A webview may always disable more than the host would; it may never enable past it.

The switch pill has four honest states — `true`, `false`, `unset` (the repository really does not have the variable) and `unknown` (nobody has asked: no credential, or the tab was opened without one) — and an ungated lane draws a dash. `true` is `warn` amber because an armed lane is one that will spend tokens on its own; `unknown` is the `statusPill` variant that is not an answer, and it renders unfilled and dashed rather than as another grey badge. A workflow GitHub has registered `disabled_manually` gets its own `danger` pill beside the switch, because that is a second, independent control and the two are routinely confused.

**Cost is `null` when nobody measured, and it is never drawn as `$0.00`** — a zero in a cost column reads as "this was free", and the ledger may simply have no row for that lane. `core/fleet/cost.ts` omits a lane rather than handing over zeroes precisely so this cell can tell the two apart. The audit cell is the same shape: `undefined` means no checkout was audited and draws as unknown, while an empty finding list is a real pass and draws as `clean`.

**The merge-policy block is a read, and cannot be anything else.** `AUTO_MERGE_ENABLED`, `AUTO_UPDATE_ENABLED` and `AUTO_FIX_ENABLED` decide whether anything merges the queue above them without a person. None of them is a manifest lane, so the console reports them and offers **no control** — and `fleetPlanHasNoMergeVerbs` in `core/fleet/github.ts` is what makes that a boundary rather than an omission. The pull strip beside it shows `prStage`, derived from the repository's own labels, which is a report of where a pull request sits and never a prediction that it will merge. A pull request no lane claims is drawn as `unattributed` rather than assigned to a plausible lane.

**Manifest drift is shown and never written.** Both sides of a row are quoted verbatim and wrap rather than truncate, because the difference between the two strings is the whole story; deriving a manifest is `wtd`'s job.

**Refresh** posts `fleet.refresh {repo}` — one repository, four calls — and is the only intent on this screen that may prompt to sign in. Token rows show names only: the console never reads a secret.

## Monitor (`monitor.ts`)

The whole roster as a matrix: one section per repository (identity, provenance, grade, all-time spend, its own Refresh) over a lane table of switch · newest run · open PRs · cost · grade, then that repository's merge policy and its open pull requests as chips. Below them, the hub block and its scorecard.

**Honesty is the whole design here, and it is a different problem from every other tab's.** The rest of this dashboard describes one repository a person has open, where "I do not know" is rare. This one describes up to a dozen, most of which nobody has read — so most cells are unknown most of the time, and a matrix whose unknown cells look like "off" is not a monitor, it is a hallucination with a grid around it. Three rules, and every cell obeys them:

1. **A cell nobody has read renders `unknown`**, through `statusPill`'s dashed, unfilled, italic variant — visibly not the filled `neutral` badge that means "the answer is no".
2. **Never a `0` where the truth is "nobody measured".** An open-pull count of `null` is not zero and a cost of `null` is not free; the host sends `null` for both so this file can tell them apart. `no run on record` is deliberately *not* a pill: it is a measurement, so it renders as muted prose, and only an unread row gets the dashed `unknown` in that column.
3. **Two absences are different, and both are named.** A repository with a checkout but no refresh has real lane rows — the manifest is on disk, so the lanes are known and only the answers are missing. A repository with no checkout and no refresh has **no rows at all**, and says so in words rather than drawing an empty table that reads as "no lanes". Refreshed, that same repository gets real rows (its manifest is read with the declared contents call) and keeps `unknown` in the grade, drift and cost columns, because those are functions of files in a checkout.

A fifth switch word appears only here: `ungated`. A lane with no `*_ENABLED` variable is not `unset` — nothing is holding it — and this row has no variable name to draw that distinction with, so the distinction travels on the wire as its own word and renders amber beside `true`.

**Rendering this tab makes no request.** Reading a repository is a button on that repository's own row — four calls for one this window has open, five for one it does not — the hub is read only by the explicit **Import hub roster**, and **Open in GitFactory** assembles the link locally and hands it to the browser. There are no lane verbs on this screen: step 2 of every gate is "re-read the manifest from disk", so the console acts only on a repository it has a checkout of, and this tab exists to show the ones it does not.

## Harness (`harness.ts`)

A summary strip and five tables, all over the promoted `dataTable`: the roles under `.claude/agents/`, the routines under `.claude/skills/`, every workflow with the shape of the runner it reaches a model through, the join (workflow → lane → role → routine → switch → tokens → spend), and the disagreements. It answers one question — **what will run, as whom, spending what** — which no single file in a repository answers on its own.

Three claims this screen is allowed to make, and one it is not.

**Tokens are names.** The manifest declares which credentials a lane spends, the join's token column repeats those names, and no surface in this bundle can reach a value. The column says so in its own header, because a reader who has to guess whether a console holds their secrets will assume the worse answer.

**The resolved profile says which layer answered for the model.** "The model" silently differing between the editor and CI is the confusion the whole harness slice exists to end, so `modelSource` renders as a sentence beside the model — *from your own settings*, *from this repository's zer0.json*, *inherited from the repository's own `_data/ai.yml`*, *the built-in default*. `MODEL_SOURCE_PROSE` here is the twin of `describeSource` in `src/core/harness/profile.ts`; this bundle cannot import core, so the sentence is written twice. Edit both in one commit. The last row of that list is the same `toRunnerInvocation` projection `agent.runAsRole`'s "Copy the CI equivalent" hands you, so the desk and the lane cannot disagree about what a run is.

**An absent number is an em dash.** A repository with no usage ledger is *unmetered*, and unmetered is not free — `.z-harness__unknown` renders that, never a `0`, exactly as the Catering lanes render an unscored page (decision D9). It may **not** show a health grade or a total anybody could mistake for money: `unit` (`api-equivalent-usd`) travels with every figure and is drawn beside it.

Read-only, entirely: the only intents on this route are `revealFile` and, from the empty state, `harness.open`.

## Workflows (`workflows.ts`)

Three parts: the lane catalogue as read-only **passports**, a `stagedForm` for describing a lane that does not exist yet, and a preview of exactly what writing it would do.

**The catalogue offers no buttons, and that is decision D-I.** This console operates lanes inside the editor; it does not rewrite an arbitrary workflow's attributes in place. A passport therefore says everything needed to *understand* a lane — its file, its runner shape, the variable that stops it, whether a manual run bypasses that variable, its schedule, the credentials it spends by name, the file its assertion reads — and the last column answers "could this console have written this again?" For a `bespoke` lane the reasons are drawn as readable prose in the cell rather than hidden in a tooltip, because **refusing well is the feature**: "needs a dynamic matrix" is something a person can act on and a bare "unsupported" is not. lifehacker's content-review lane is the case worth remembering — approximating it would silently drop a loop-breaker guard that repository had to add after a workflow retriggered itself forever.

**The form's values are a draft, not a setting**, so Save posts one `{type:'setUiState', key, value}` per changed row instead of `updateSetting`. The rows come from `WorkflowsState.form`, which the *host* built, so this screen can only ever hand back a key the host itself offered — the Settings route's contract, applied to a different kind of value.

**Preview is computed from what the host has, not from what is on the screen.** An unsaved edit therefore disables Preview and says that in the blocker sentence, rather than planning a lane nobody described; the check runs again at click time, because typing does not repaint and the disabled state can be one keystroke stale. The reply is drawn through `diffView` — the same component and the same `media/base.css` rules the agent's approval card uses, so a generated file and a proposed edit look identical — one file expanded at a time, with the whole of a new file rendered as additions.

**The switch this action does not create is drawn twice, on purpose.** Once in the plan's Kill switch row and once beside the Write button: *writing files a person reviews and arming a loop to run are different powers*. `.z-workflows__notcreated` is the only emphasis on the screen and it is spent there. Write is a `gatedButton` posting `{spec:'<lane id>'}` — a lane id, never the plan — and its blockers are the host's `evaluateFleetGates('scaffold', …)` verbatim and in the gate's own order, plus two this view owns: no plan has been drawn yet, and the plan that was drawn is one this console refuses to generate.

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

Every class emitted here is dressed by `media/dashboard.css` (and `media/base.css` for the kernel widgets — `.z-status`, `.z-table*` and `.z-emptystate` live there now, because the shared components build them and the panel bundle has to be able to render one). The dashboard bundle does **not** load `media/panel.css`, so the panel's `.z-pill--*` status variants are not available.

Status goes through `statusPill` rather than a hand-written class: `ok | warn | danger | neutral | unknown`, where `unknown` renders unfilled, dashed and italic. That is the one variant that carries a rule — a cell nobody has asked about must not look like a cell whose answer happens to be "no". The legacy `--scheduled` / `--draft` selectors are still in `base.css` as aliases of `--warn` / `--danger`, because `contents.ts` and `structure.ts` still emit them.

Only `media/tokens.css` may name a VS Code theme variable, and `src/test/styling.test.ts` greps for violations. It also fails the build if `el()` grows a `style` prop back: the strict CSP drops an inline style attribute silently, so the idiom does nothing and looks like it works.
