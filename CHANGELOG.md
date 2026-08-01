# Changelog

All notable changes to zer0-CMS are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

Found by running the core over a real 100-file content repository instead of the seven-file fixture workspace.

### 🐛 Fixes

- **Slugs no longer lose words that carry meaning.** `slugify` inherited Front Matter's SMART stop-word list, which contains `back`, `new`, `value`, `use`, `way`, `thing`, `vs` and `without`. Over a real 72-post site it cost a meaningful word in 31% of titles: `"MCP for the back office"` became `mcp-office`, and `"… without losing data"` became `…-losing-data` — the opposite claim, in a permanent URL. The default list is now `minimal`, the closed class of English function words.
- **An uncounted body reports "unknown", not "0 words".** Without a `.cms/` contract the filesystem scan reads front matter and never bodies, and `pageToRecord` filled `wordCount` and `headingCount` with `0` — a claim, not an absence. The content tree drew "0 words" under every article in a repository with no engine, and the MCP `zer0_get_content` answer told a model that a two-thousand-word page was empty. Both now carry `UNKNOWN_COUNT` (`-1`), the sentinel `health` already used, and render through `countLabel`.

### ✨ New features

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
