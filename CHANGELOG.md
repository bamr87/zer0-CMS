# Changelog

All notable changes to zer0-CMS are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### 🗂 Many sites, one window

A window can hold more than one site. The fleet's own workspace holds twelve folders — seven of them Jekyll sites this extension can detect, audit and publish — and until now eleven of them were invisible, because everything resolved the first folder.

The unit is still one folder: one configuration, one snapshot, one cache key, one MCP server. Multi-root is composition above that rather than a second model threaded through it. A **site registry** holds one store per folder, and a **Sites** tree and dashboard tab show what is in the window: each folder's platform, whether it is configured, its content roots, its counts, whether it carries a fleet manifest.

**Which site a command acts on is decided by the command, not by the window.** A command invoked on a file acts on *that file's* site — registering a folder edits that folder's `zer0.json`, a draft goes into its own site's queue, diagnostics validate against the owning site's content types. Only a command with no argument falls back to the active site, resolved as: an explicit pick that still exists, then the folder owning the active editor, then the first folder. That rule is a pure function with tests, because a rule like this quietly acquires a fourth case.

The panel's persisted state is namespaced per site, so two sites no longer overwrite each other's collapsed sections. The MCP provider offers one server per configured site rather than one per window — on the twelve-folder workspace that is two or three servers, not twelve. `zer0Cms.site.preview` runs the detected platform's own serve command through a VS Code task and offers the preview URL when it is ready.

### 🤝 One harness vocabulary

The agent in this editor and the AI lanes in CI shared nothing. The editor did not read the repository's model configuration, did not know its `.claude/agents` roles, did not attach this extension's own MCP server, and defaulted to a model the fleet does not use — so "run this as the content role" was possible in a workflow and impossible at the desk, and the two disagreed about the model without anyone noticing.

A **harness profile** now resolves a repository's roles, skills and model once, in the CI runner's own precedence — a setting, then `zer0.json`, then the site's `_data/ai.yml`, then a built-in fallback — and projects to either an editor run or the equivalent CI invocation. `zer0Cms.agent.runAsRole` picks a role from the repository's own agents and runs it under the approval card; **Copy the CI equivalent** hands you the `run.sh` line or the workflow `with:` block for that role. On lifehacker.dev the editor now resolves the same model that repository's own lanes use, instead of a different one.

The extension's own MCP server is attached to an agent run, with its eight read-only tools auto-allowed and its five writers on the card. The publish and scaffold flags are explicitly deleted from the child environment: an editor run must not inherit whatever armed something else.

### 🔒 A gate that was not holding

**`permissionMode: 'acceptEdits'` bypassed the approval card entirely, and this extension offered it as a setting.** Measured against the Agent SDK rather than assumed: with that mode a `Write` landed on disk and `canUseTool` — the single gate the whole agent design rests on (decision D10) — was never called at all.

It is gone from the manifest, removed from the type, and clamped at both configuration layers, so a settings file or a `zer0.json` that still names it falls through to `default` rather than disarming the gate. `plan` remains, because planning without acting needs no gate. Two related things were measured and are worth writing down: a repository-committed `permissions.allow` rule does *not* bypass the card, and a repository-committed escalating default mode is dropped by the CLI's own trust filter.

Loading a repository's `.claude/settings.json` into an editor run is off unless the workspace is trusted **and** you opt in for that run — those files can declare hooks, which are command lines running under your credential.

### 🌍 Every site, not just this one

zer0-CMS now knows what kind of site it is looking at. Jekyll, MkDocs, Wiki.js, Hugo, Docusaurus, Astro and a generic fallback are **profiles** — content roots, front-matter dialect and keys, the draft convention, date keys and formats, the slug and permalink rules, the directories a build writes and the command that serves the site locally — resolved once from marker files, with an explicit `platform.id` in `zer0.json` always winning. Everything platform-specific that used to be hard-coded in the core now comes from one of them.

zer0-mistakes is an **overlay on Jekyll**, never a sibling identity: a site using that theme is a Jekyll site with extra conventions, and modelling it as its own platform would have meant restating every Jekyll rule to keep it true.

Three things this immediately fixed, each found by pointing the code at real repositories rather than fixtures:

- **The theme overlay matched one site out of six.** The probe looked for the literal `remote_theme: bamr87/zer0-mistakes`, and five of the six sites in this fleet write it aligned and quoted — `remote_theme             : "bamr87/zer0-mistakes"`. A detector that only recognises tidy files is a detector for fixtures. Probes now read past spacing, quoting and case.
- **A site whose `collections_dir` carries a YAML anchor was invisible.** it-journey.dev writes `collections_dir: &collections_dir pages`, and treating that as unresolvable meant **none** of its 409 content files were seen. An anchor is a *label on* a value — the value is right there, and reading it is not a guess. An alias, which points at a value defined elsewhere, still reports as unknown rather than being invented.
- **Jekyll's loose pages were not content.** Deriving only the declared collections left fourteen of lifehacker.dev's 383 files unseen. Jekyll builds every markdown file under the source directory, and a CMS that cannot see a page cannot report a problem with it. Coverage on the two largest sites in the fleet went from 368/383 and 0/409 to **383/383 and 408/409** — the one remaining file has no front matter and is skipped on purpose.

Publishing follows the platform too. `PublishTarget` was an open interface with exactly one implementation and a registry that **threw** for anything else, so a detected MkDocs site would have crashed the publish preview. One factory now serves every file-writing platform, with the same exclusive-write and adopt-a-retry semantics Jekyll always had. `governance.target` defaults to empty, meaning *follow the platform* — so naming one is a real choice rather than an indistinguishable default, and Jekyll sites publish exactly as they did.

### 🔍 The front-matter audit

Every page checked against its content type, its site's own schema and its platform's conventions — thirteen rules using **lifehacker.dev's own rule id strings**, so a finding raised in the editor and one filed by that site's CI are the same finding rather than two. It reads the schema the site already has (`frontmatter_schema.yml`, a `.cms/` contract, `zer0.json`, or the platform's defaults) instead of asking you to restate it, and every report names which one answered — because "required" means something different in each case.

A finding that a script can honestly fix offers a fix; the rest say why not. `title: ''` is not a repair, and neither is `draft: true`. Applying one re-reads the file, re-runs the rule against what is actually on disk now, shows the real diff in a diff editor and asks — in that order, so a fix for a finding you have since edited away cannot land. The parser also grew a **warnings channel**: a file using YAML anchors, aliases, merge keys or multi-line flow collections is reported as unreadable rather than audited on a misreading, and fix-it refuses it outright.

Available as an Audit tab, three commands, and a read-only `zer0_audit` MCP tool (thirteen now). Over lifehacker.dev's 382 real posts it reports **zero errors and two warnings**, both genuine over-long descriptions — the rules were tuned against a real corpus, and one that fired ten times on correct files was fixed rather than shipped.

### 🧱 Foundations

This release turns zer0-CMS from a CMS for *this* repository into the foundation of one that can operate a fleet of them. Nothing here is a new feature you can point at; it is the floor the next four slices stand on — platform profiles, a site-wide front-matter audit, a multi-root site registry, a harness inventory with lane generation, and the fleet console's second slice. Two long-standing bugs fall out of it, and one promise the documentation had been making for a year becomes true.

- **The AI agent panel was never wired up.** `AgentPanel` installs itself as the agent host in its constructor, and nothing in the extension ever constructed one — so every `zer0Cms.agent.*` command ended at "the AI agent panel is not available in this window", for the whole of 0.1.0, while `src/agent/README.md` described the wiring in the present tense. `activate()` now builds it at step 8. The bundle is asserted to contain that wiring, because the test process and the running extension are different module instances and a runtime check would have passed for the wrong reason.
- **Workspace Trust is now the outer gate on everything that runs (decision D13).** Five paths in this extension can start a process — the content engine, the front-matter normalizer, a `placeholders[].script`, the new verify command, and the agent — and in an untrusted workspace all five refuse, as a result value rather than an exception, and the extension registers no MCP server at all. The manifest declares `untrustedWorkspaces: limited` and names the eighteen settings that decide *what* runs or *whether a gate is armed*, so a cloned repository's own `.vscode/settings.json` cannot aim them. Trust is re-checked inside each function that spawns: the `when` clause is the courtesy, the function is the gate. A script path that resolves outside the workspace root is refused whichever layer supplied it, and every spawn is now logged with its interpreter, its script and which configuration layer supplied them — so the output channel shows what a repository *tried* to run even when nothing ran. The engine also grew a ten-minute timeout, which it had never had.
- **The fleet's shared engines arrive by dependency, not by copy (decisions D3 and D14).** `@bamr87/fleet-engines` is an exact-pinned `devDependency` that the bundler admits into `dist/extension.js` alone; the MCP bundle's allow-list is now **empty**, so the layering gate that has always guarded `vscode` guards every package, and `dist/mcp-server.js` stays standalone by construction rather than by habit. One seam, `src/core/fleet/engines.ts`, is the only importer and is never re-exported through the core barrel. `dependencies` is still `{}` and still will be.
- **Four of the fleet's seven committed `fleet.manifest.yml` files are invalid YAML**, and the upstream parser was hiding it. `wtd fleet adopt` wraps a single-quoted scalar at column 80 and writes the continuation at column 0, outside the block indent; the engines' parser swallows the error and returns an *empty* manifest reporting *zero* skipped lanes, so a console consuming it would show a repository with no AI lanes at all and no indication anything went wrong. This repository's own manifest is one of the four. Keeping our own tolerant reader — which parses all seven — is what caught it, and a parity test now pins both halves: exact agreement where the package can read the file, and the silent-failure disagreement where it cannot.
- **Comparing what a manifest claims against what its workflows do.** `manifestDrift` reports where the two disagree, and on the real fleet it immediately found a lane declaring `opens_pull_requests: false` that demonstrably opens pull requests, a kill switch named in a manifest that no workflow reads, a schedule recorded for a cron that is commented out, and a token claimed but never used.
- **Performance, measured rather than assumed.** Cold indexing of a 382-file site went from 54 ms to 27 ms via a bounded worker pool whose results are folded back by candidate index, so page order and object identity are unchanged. The page-index cache is no longer rewritten when nothing changed — that write was 0.5–1.4 MB per rebuild per root — and its key is now per-root, because entries are keyed by absolute path and one shared key would rewrite every root's entries whenever any one of them refreshed.
- **The design decisions have somewhere to live.** Fifteen source and documentation files cited a plan document by section number; that plan was a conversation, not a file, and had never been in this repository. `docs/ARCHITECTURE.md` now states D1–D14 from the code, each with the mechanism that enforces it, alongside the contract map (what this console consumes, who owns it, where it is pinned) and a plain statement of what it will never do.

### ✨ New features

- **Six new settings, and a manifest that says what may run untrusted.** `fleet.roster`, `fleet.hub` and `fleet.gitfactoryUrl` (the multi-repository roster and the hand-off to GitFactory), `fleet.scaffoldAllow` (settings-only, like `dispatchAllow`, for writing a lane's files), and `cms.aiConfigPath` and `cms.verifyCommand` (the site's own model configuration and its verification command). The 44 settings are grouped into eleven titled sections, and most are now folder-scoped so one window can hold several sites without their settings leaking into each other. `SETTING_IDS` and the manifest are asserted equal, in order, and `tools/check-config-docs.py` fails the build when the documentation and the manifest disagree.
- **A release path.** `release-please` owns the version and the changelog; a repo-owned job packages the `.vsix`, attaches it to the GitHub release so any machine can `code --install-extension` it, and publishes to the Marketplace and Open VSX when those tokens exist — skipping with a notice, not a failure, while they do not. The packaged file list is committed and diffed in CI, so a packaging regression is a reviewed change. `docs/RELEASING.md` writes down what a person still has to do by hand.
- **The route registry.** The eleven dashboard routes and the tabs currently offered are one table, shared by the host and the webview, with a renderer table total over the union — a route can no longer be declared without a renderer. Operator primitives (status pills that distinguish *unknown* from *neutral*, scrolling data tables, empty states, gated buttons, diff views, a keyed staged form) moved into the shared component library where the five coming tabs can use them.

### 🐛 Fixes

- The bundled MCP server reported a hard-coded `0.1.0` that nobody remembered to bump; it now reports the extension's own version, and a test asserts the two cannot drift.
- The ABC generator under `rails/` is no longer called "the content engine" — that name belongs to the `.cms/` contract engine — and it has its own CI workflow, so an extension pull request stops running Ruby and a generator change stops downloading VS Code. Its README documented two commands that never worked: there is no `bin/rails` binstub and no Rakefile.
- Three claims the documentation made that CI had never checked are now tests: that `--vscode-` appears only in the token layer, that field widgets mount and dispose without leaking listeners, and that every route renders its empty state. A fourth was quietly false — `el()`'s `style` prop could never work under the strict Content-Security-Policy — and is gone.

---

Found by running the core over a real 100-file content repository instead of the seven-file fixture workspace.

### 🐛 Fixes

- **Slugs no longer lose words that carry meaning.** `slugify` inherited Front Matter's SMART stop-word list, which contains `back`, `new`, `value`, `use`, `way`, `thing`, `vs` and `without`. Over a real 72-post site it cost a meaningful word in 31% of titles: `"MCP for the back office"` became `mcp-office`, and `"… without losing data"` became `…-losing-data` — the opposite claim, in a permanent URL. The default list is now `minimal`, the closed class of English function words.
- **An uncounted body reports "unknown", not "0 words".** Without a `.cms/` contract the filesystem scan reads front matter and never bodies, and `pageToRecord` filled `wordCount` and `headingCount` with `0` — a claim, not an absence. The content tree drew "0 words" under every article in a repository with no engine, and the MCP `zer0_get_content` answer told a model that a two-thousand-word page was empty. Both now carry `UNKNOWN_COUNT` (`-1`), the sentinel `health` already used, and render through `countLabel`.

### ✨ New features

- **The Fleet console — this repository's AI lanes, and two verbs a human has to answer for.** With `zer0Cms.fleet.enabled` the dashboard grows a Fleet tab that reads `fleet.manifest.yml` (spec `fleet/v1`, the shared vocabulary `wtd fleet adopt` writes) and draws every lane: kind, harness, workflow, triggers, guardrails, the `*_ENABLED` repository variable that gates it, and the tokens it spends. After a GitHub sign-in you answer, two more columns arrive — the switch's current value and the workflow's newest run — and two buttons: flip the switch, or dispatch the lane once. The buttons post `{lane}` and nothing else; `doToggleSwitch` and `doDispatchLane` re-read the manifest from disk, re-run `evaluateFleetGates()` (a fixed, tested blocker order, exactly like the publish gate) and ask modally, naming the repository, the lane, the variable and the value — which for a toggle is derived from the variable as fetched a moment earlier, never from a message. The master gate, `zer0Cms.fleet.dispatchAllow`, is read from your settings alone, so a cloned `zer0.json` or manifest cannot arm it; a lane whose own manifest admits to merging or writing to the default branch is refused outright. Decision D11 states the one relaxation of the activation promise: network only from an explicit user action, through a `fetch` injected into `core/fleet`, whose every call is declared as data and checked against that plan before a socket opens. No token is stored. `zer0_fleet_status`, the twelfth MCP tool, reads the manifest only and says the switch state is unknown from there.
- **The YAML subset folds multi-line plain scalars.** A value continued on more-indented lines was read as its first line and the rest skipped — a documented gap, until the manifest's 80-column-wrapped `summary:` made it a bug. Continuation lines now fold the way YAML folds them (one space per line break, a newline per blank line); a line that reads as a key or a sequence item still ends the value, as before, so nothing that parsed previously parses differently.
- **The feedback loop closes.** `catering/` could already turn engagement into a worklist and `contract/` could already store it, but nothing turned a platform's statistics into the `performance.json` those two agree on — so Lanes B–D were empty unless somebody hand-wrote the file. `core/analytics` adds the join: statistics arrive keyed by a post id, the ledger says which post came from which page, and they leave keyed by content path. `zer0_ingest` runs it from any MCP client and `zer0_worklist` ranks on the result.
- **The read surface is declared as data, and the boundary is a test.** `readPlan()` enumerates every call the analytics lane would make, with what each returns, so it can be printed and reviewed before a credential exists. `readSurfaceIsOwnContentOnly` checks each one describes the author's *own* content; the suite asserts it for both shipped plans and asserts that a follower-enumeration call fails it. Reaching another person's data is a failing build rather than a review comment. There is deliberately no `fetch` here — invented numbers would silently poison the worklist that decides what somebody writes next.
- **`core/portfolio` — the published track record.** Volume, cadence, streak and collections, computed from the ledger, so it is meaningful from the first entry rather than waiting on statistics. The streak is anchored to the newest month *in the data*, not to today: a portfolio that reported a broken run because you opened it in a quiet week would be measuring the calendar, not the work. Exposed as `zer0_portfolio`.
- **`core/media` — reuse the image the site already made.** Resolves a page's preview image from front matter, then from `assets/images/previews/<slug>.*`, and when there is none emits the zer0-image-generator command that would produce it. It generates nothing: rendering stays where the provider matrix and review stage live. Publishing already read the image and silently posted without one, which let a repository drift into publishing untreated links; `zer0_media` makes that askable across the whole content set before anything ships. Shares `THUMBNAIL_KEYS` and `previewImageValue` with `governance/publish` rather than restating them, so the report and the publish path cannot disagree.
- **`slug.stopWords`** in `zer0.json` — `"minimal"` (default), `"smart"` (Front Matter verbatim, for a repository whose permalinks FM already minted), `"none"`, or a literal array. An unrecognised value falls back to the default rather than to "none", so a typo cannot silently re-slug a site. See [`docs/CONFIG.md` §3.11](docs/CONFIG.md).

### 📝 Documentation

- `docs/CONFIG.md` said the bundled MCP server parses `zer0.json` with `JSON.parse` and would choke on a comment. It reads it with `readJsonc`, exactly as the extension does, and always has.

## [0.1.0] - 2026-07-31

The first release of zer0-CMS as its own extension. Everything before this point was a fork of Front Matter CMS; that history stays in git, but none of it ships. See [ATTRIBUTION.md](ATTRIBUTION.md).

### ✨ New features

- **Metadata panel** — the active content file's front matter as real controls: 18 field types, required-field validation, taxonomy pickers with freeform creation, image preview fields, and grouped field collections.
- **Content dashboard** — grid, list and structure views over every registered content folder, with search, filters, sorting, grouping and pagination.
- **SEO insights** — title, description, slug, content-length and keyword checks against the thresholds in `zer0.json`.
- **Governed publishing** — a draft queue where approval is a human decision recorded in the file: draft → brand guard → approve → publish → ledger. Publishing is off until `zer0Cms.governance.publishAllow` is enabled.
- **Brand guard** — length limits, the fold preview, banned phrases, filler detection, and a workspace-supplied pattern file.
- **Idempotency ledger** — keyed by canonical URL, byte-compatible with the Python publishing lane, so a repo and its CI never double-publish.
- **Distribution lanes** — what to write next, derived from the `.cms/` contract and the ledger, exportable as a worklist.
- **`.cms/` contract** — per-file health, freshness and the mechanical/substantive issue lanes when the content engine has run; an honest filesystem scan when it hasn't.
- **Bundled MCP server** — eight tools for Copilot agent mode and any MCP client. Publishing is double-gated: an environment flag *and* an explicit per-call confirmation. The editor sets that flag only when `zer0Cms.governance.publishAllow` is set in your own settings — a `zer0.json` arriving with a cloned repository can enable publishing for the in-editor gates, which sit behind a modal, but never for an agent.
- **Optional AI agent** — the `cms-curator` skill through the Claude Agent SDK, with an approve/deny gate on every mutating tool. Off by default.

### 🎨 Enhancements

- Zero runtime dependencies. The agent SDK is an optional dependency, dynamically imported, and never required to use the CMS.
- `src/core` and `src/mcp` cannot import `vscode` — enforced by eslint and by the MCP bundle's build.
- Front matter is edited by line surgery, so comments and formatting survive an edit.
- Every publish gate is re-checked host-side, in the same function the command palette calls. A webview is UI, never the gate — including for deleting and renaming, where the host re-derives the target against the page index and asks before it acts.
