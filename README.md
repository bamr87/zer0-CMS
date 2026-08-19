<h1 align="center">zer0-CMS</h1>

<p align="center">
  <img src="media/zer0-cms-128.png" width="96" alt="">
</p>

<p align="center">
A lightweight CMS for your markdown repo, inside VS Code.<br> Edit front matter as real controls, browse your content in a dashboard, and publish through a gate a human has to walk through.
</p>

<p align="center">
  <em>Zero runtime dependencies. One esbuild bundle. No framework.</em>
</p>

---

## What it is

zer0-CMS turns a repository of markdown into something you can actually operate:

- a **metadata panel** that renders the active file's front matter as typed controls instead of raw YAML,
- a **dashboard** that lists every piece of content with search, filters and sorting,
- **SEO insights** measured against thresholds you set,
- and a **governed publishing path** — draft → brand guard → human approval → publish → ledger — where nothing goes out because a script decided it should.

It began as a fork of [Front Matter CMS](https://github.com/estruyf/vscode-front-matter) and deliberately keeps its interaction design, because that design is good and people already know it. The code underneath is new. See [ATTRIBUTION.md](ATTRIBUTION.md).

## The two halves of this repo

| Path | What it is |
|---|---|
| `src/` | The **VS Code extension** — this README. |
| `rails/` | The **ABC content engine** — a stdlib-only Ruby library + optional Rails wizard that writes children's alphabet books and exports them as a Jekyll board book. Separate product, separate README: [`rails/README.md`](rails/README.md). |

## How publishing works

```
Content ──▶ Draft ──────▶ Guard ──────▶ Approve ──────▶ Publish ──▶ Ledger
   ▲        status:        length,       status:          the        keyed by
   │        pending        bans,         approved         target     canonical
   │                       filler        a person,                   URL
   │                                     in the file                    │
   │                                                                    ▼
 .cms/ ◀──── Worklist ◀──── Catering ◀──── Performance ◀──── Statistics
             what to        four lanes     aggregate,        the author's
             write next                    per page          own posts
```

The loop closes on the bottom row. The ledger says which post came from which page, so statistics keyed by a post id become statistics keyed by *content* — and the catering lanes can rank subjects rather than guess at them. Everything on that row is aggregate: counts attached to content the author published, never anything about who engaged.

Five rules hold this together:

1. **Approval is a human decision recorded in the file.** A draft's `status:` line is the record. There is no unattended path to published.
2. **The webview is UI, never the gate.** Buttons post an intent and a target — never a payload, never an override. Every gate is re-checked host-side, in the same function the command palette calls.
3. **The ledger is keyed by canonical URL**, so this extension and a CI lane can share one queue without double-publishing. It is byte-compatible with the Python lane's `json.dump` output, so the file never churns in git.
4. **What comes back is aggregate, and only about your own content.** The read surface is declared as data in `core/analytics`, and a test fails the build if a call in it would return another person's data. Nothing is derived about a reader anywhere in the loop.
5. **Publishing is off by default.** Until you enable `zer0Cms.governance.publishAllow`, every path — commands, panel, dashboard, MCP — is preview and draft only.

## Getting started

1. Install the extension and open your content repo.
2. Run **zer0-CMS: Initialize project** to write a `zer0.json`.
3. Register a content folder (right-click a folder → *Register content folder*, or add it to `zer0.json`).
4. Open a markdown file — the panel fills in.
5. Press <kbd>Alt</kbd>+<kbd>D</kbd> for the dashboard.

Everything about the *project* — content folders, content types and their fields, taxonomy, SEO thresholds, the slug template — lives in `zer0.json`, validated as you type. Everything about *your machine* lives in VS Code settings under `zer0Cms.*`. That split is why there are 35 settings here instead of 89.

## Configuration

`zer0.json`:

```jsonc
{
  "contentFolders": [
    { "title": "Posts", "path": "[[workspace]]/pages/_posts", "contentTypes": ["post"] }
  ],
  "contentTypes": [
    {
      "name": "post",
      "fields": [
        { "name": "title",       "type": "string",   "required": true },
        { "name": "description", "type": "string",   "required": true },
        { "name": "date",        "type": "datetime", "default": "{{now}}" },
        { "name": "tags",        "type": "tags" },
        { "name": "categories",  "type": "categories" },
        { "name": "preview",     "type": "image" }
      ]
    }
  ],
  "taxonomy": { "tags": [], "categories": [] },
  "seo": { "titleLength": 60, "descriptionLength": 160, "slugLength": 75, "contentLength": 1760 },
  "slug": { "template": "{{title}}" }
}
```

The settings that matter most:

| Setting | Default | Purpose |
|---|---|---|
| `zer0Cms.governance.publishAllow` | `false` | The master gate |
| `zer0Cms.governance.acceptStatuses` | `pending, approved` | Set to `approved` only to force the approval step |
| `zer0Cms.governance.draftsFolder` | `.zer0/drafts` | The queue |
| `zer0Cms.governance.ledgerPath` | `.zer0/ledger.json` | The shared ledger |
| `zer0Cms.governance.bannedPatternsFile` | — | Extra brand-guard patterns |
| `zer0Cms.cms.root` | `.cms` | Where the content engine's contract lives |
| `zer0Cms.agent.enabled` | `false` | The optional AI layer |

Full reference: [`docs/CONFIG.md`](docs/CONFIG.md).

## The `.cms/` contract

If your repo runs a content engine that emits `.cms/index/content-index.json`, zer0-CMS reads it: per-file **health**, **freshness**, and the **mechanical / substantive** issue lanes, plus the distribution worklists it writes back to `.cms/distribution/`.

If your repo has no `.cms/`, that is a normal state, not an error — the extension falls back to an honest filesystem scan and simply reports less.

## MCP server

The extension registers a bundled MCP server with VS Code 1.101+, so Copilot agent mode (or any MCP client pointed at `dist/mcp-server.js`) gets eight tools:

| Tool | Safe? |
|---|---|
| `zer0_status` · `zer0_list_content` · `zer0_get_content` · `zer0_preview` · `zer0_contract` | read-only |
| `zer0_draft` · `zer0_worklist` | writes a draft or a worklist for a human |
| `zer0_publish` | **off by default** — needs `ZER0_CMS_MCP_ALLOW_PUBLISH=1` in the server env *and* `confirm: true` per call |

The preferred path is `zer0_draft`: the model writes, the person approves.

## The optional AI agent

Off unless you turn it on. With `zer0Cms.agent.enabled` and the `@anthropic-ai/claude-agent-sdk` optional dependency installed, zer0-CMS can run a content-curation agent whose every mutating tool call goes through an approve/deny card showing the diff. Read-only tools run without asking; nothing else does.

## Architecture

```
src/core/      pure Node. No `vscode` import — enforced by eslint and by the build.
src/mcp/       the standalone MCP server. Bundles with nothing external.
src/webview/   vanilla TS + CSS. No React, no Tailwind, no innerHTML.
src/           the thin vscode shell: extension.ts, commands, views, providers.
```

The `src/core` boundary is load-bearing, not stylistic: it is why the same publish gate runs identically from a command, a webview and an MCP client, and why the core is testable without an extension host.

More: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Development

```bash
npm install
npm run compile          # type-check + lint + all five bundles
npm run watch            # esbuild + tsc in watch mode, then F5
npm test                 # unit + golden + MCP stdio + integration
npx @vscode/vsce package # build the .vsix
```

`npm run compile` failing with `Could not resolve "vscode"` means something in `src/core` or `src/mcp` imported the VS Code API. That is the layering gate doing its job.

## License

[MIT](LICENSE). Portions © 2019 Elio Struyf (Front Matter CMS) — see [ATTRIBUTION.md](ATTRIBUTION.md).
