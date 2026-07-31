# Changelog

All notable changes to zer0-CMS are documented here.
The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2026-07-31

The first release of zer0-CMS as its own extension.
Everything before this point was a fork of Front Matter CMS; that history stays in git, but none of it ships. See [ATTRIBUTION.md](ATTRIBUTION.md).

### ✨ New features

- **Metadata panel** — the active content file's front matter as real controls: 18 field types, required-field validation, taxonomy pickers with freeform creation, image preview fields, and grouped field collections.
- **Content dashboard** — grid, list and structure views over every registered content folder, with search, filters, sorting, grouping and pagination.
- **SEO insights** — title, description, slug, content-length and keyword checks against the thresholds in `zer0.json`.
- **Governed publishing** — a draft queue where approval is a human decision recorded in the file: draft → brand guard → approve → publish → ledger. Publishing is off until `zer0Cms.governance.publishAllow` is enabled.
- **Brand guard** — length limits, the fold preview, banned phrases, filler detection, and a workspace-supplied pattern file.
- **Idempotency ledger** — keyed by canonical URL, byte-compatible with the Python publishing lane, so a repo and its CI never double-publish.
- **Distribution lanes** — what to write next, derived from the `.cms/` contract and the ledger, exportable as a worklist.
- **`.cms/` contract** — per-file health, freshness and the mechanical/substantive issue lanes when the content engine has run; an honest filesystem scan when it hasn't.
- **Bundled MCP server** — eight tools for Copilot agent mode and any MCP client. Publishing is double-gated: an environment flag *and* an explicit per-call confirmation.
- **Optional AI agent** — the `cms-curator` skill through the Claude Agent SDK, with an approve/deny gate on every mutating tool. Off by default.

### 🎨 Enhancements

- Zero runtime dependencies. The agent SDK is an optional dependency, dynamically imported, and never required to use the CMS.
- `src/core` and `src/mcp` cannot import `vscode` — enforced by eslint and by the MCP bundle's build.
- Front matter is edited by line surgery, so comments and formatting survive an edit.
- Every publish gate is re-checked host-side, in the same function the command palette calls. A webview is UI, never the gate.
