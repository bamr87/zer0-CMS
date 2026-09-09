# Changelog

All notable changes to zer0-CMS are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
