<h1 align="center">zer0-CMS</h1>

<p align="center">
  <img src="media/zer0-cms-128.png" width="96" alt="">
</p>

<p align="center">
An agent-native CMS for markdown sites: one Python platform (Django, with Wagtail as a headless library), a React studio and site renderer, and a VS Code extension with the studio's capabilities.<br> Edit front matter as real controls, let agents propose changes you accept as revisions, browse every site in one admin, and publish through a gate a human has to walk through.
</p>

<p align="center">
  <em>The platform on 127.0.0.1:8000. Extension: zero runtime dependencies. The Rails fleet CMS (127.0.0.1:3001) is being absorbed into the platform.</em>
</p>

---

## Where this is going

zer0-CMS is becoming a comprehensive application for content work — writing articles, creating content, brainstorming ideas, gathering information, operating a news site and writing books — with AI integrations and pipelines and workflows throughout ([ADR 0006](docs/adr/0006-one-python-platform.md)). It is being rebuilt into one Python platform with a React frontend: a complete, modern CMS on established libraries; an AI content layer (provider adapters, assistants, pipelines, output schemas, briefs, conversations) that helps create and develop content; a loop that manages, monitors and improves the sites it serves, with AIEO's citability scoring in it; the VS Code extension at parity with the studio; and every repository merged here — parodynews (barodybroject), aieo, books, the image generator, the Rails fleet CMS and the nine sites — absorbed with its content and capabilities, with content in the database and generated static files, zer0-mistakes kept only as an option to render and deploy a site with that theme through Jekyll, and no Ruby left. The target is [`docs/plan/TARGET.md`](docs/plan/TARGET.md), the order of work [`docs/plan/PLAN.md`](docs/plan/PLAN.md) § 3, and the per-capability progress [`docs/plan/capabilities.yml`](docs/plan/capabilities.yml) (`python3 tools/check_absorption.py --report`). What follows describes the code as it runs today.

## One platform

`content/` is zer0-CMS ([ADR 0004](docs/adr/0004-one-platform.md), [the plan](docs/plan/PLAN.md)): a Django + Wagtail headless CMS whose agents are first-class — each one a Django user with Wagtail permissions, proposing changes as suggestions an editor accepts, every run and tool call recorded, every tool behind one registry that GraphQL, REST and MCP all share — built to the fleet's operational rows: liveness, readiness and version probes, a request id on every response and log line, one error envelope, JSON logs that never hold a token, throttling, a committed OpenAPI document. It imports the Jekyll sites and exports them back byte for byte, so the files stay the source of truth for a site until it cuts over. The Rails fleet CMS, the image generator's panel, aieo, parodynews and the books studio are absorbed into it function by function, each behind a parity gate. [`content/README.md`](content/README.md)

```bash
docker compose --profile content up -d --wait db redis content worker research-worker beat relay events   # → http://localhost:8000/admin/
curl -fsS localhost:8000/healthz && curl -fsS localhost:8000/readyz && curl -fsS localhost:8000/version
```

## What the extension does

zer0-CMS's VS Code extension turns a repository of markdown into something you can actually operate:

- a **metadata panel** that renders the active file's front matter as typed controls instead of raw YAML,
- a **dashboard** that lists every piece of content with search, filters and sorting,
- **SEO insights** measured against thresholds you set,
- a **governed publishing path** — draft → brand guard → human approval → publish → ledger — where nothing goes out because a script decided it should,
- a **front-matter audit** of every page against the site's own schema, whose fixes you see as a diff before any of them lands,
- **platform profiles** — Jekyll (with the zer0-mistakes theme as an overlay), MkDocs, Wiki.js, Hugo, Docusaurus, Astro and a generic fallback — so a site is read the way its own generator reads it,
- **many sites in one window**, each with its own configuration, draft queue and MCP server,
- and a **fleet console** — the Harness, Fleet, Monitor and Workflows tabs — for the AI lanes a repository runs.

It began as a fork of [Front Matter CMS](https://github.com/estruyf/vscode-front-matter) and deliberately keeps its interaction design, because that design is good and people already know it. The code underneath is new. See [ATTRIBUTION.md](ATTRIBUTION.md).

## The products in this repo

| Path | What it is |
|---|---|
| `content/` | The **platform** — the Django + Wagtail CMS above, the system of record for every site, the agent runtime and every API. [`content/README.md`](content/README.md) · [`content/ops/README.md`](content/ops/README.md) |
| `web/` | The **studio** — the React frontend where people write, create and review content and follow agent runs, served by the platform at `/studio/`; its workspaces live in shared packages the extension's webviews will render too (ADR 0006). [`web/README.md`](web/README.md) |
| `src/` | The **VS Code extension** — edit front matter, dashboard, and governed publish *inside the editor*; the platform's client once a platform URL is configured (PLAN G10). This README. |
| `rails/` | The **fleet CMS** — a Rails 8.1 app on Administrate that indexes every registered zer0-themed Jekyll site, edits front matter and bodies back into the files (git stays the source of truth), lists and draws missing previews through zer0-image-generator, checks a site against the zer0 stack (`zer0 doctor`), carries a site's content to LinkedIn under a human gate (`zer0-cms linkedin`, the `zer0-linkedin.yml` workflow, `/admin/distribution`), and hosts the ABC book wizard. Being absorbed by the platform (PLAN Phase G). [`rails/README.md`](rails/README.md) · [`docs/PLATFORM.md`](docs/PLATFORM.md) · [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) |

```bash
SITES_DIR=~/github docker compose up --build                      # → http://localhost:3001/admin
SITES_DIR=~/github docker compose --profile imagegen up --build   # + zer0-image-generator → http://localhost:3000
```

Every port is published on 127.0.0.1 only; set `ZER0_CMS_PASSWORD` before exposing the Rails CMS anywhere else. How this repository, the zer0-mistakes theme and zer0-image-generator fit together: [`docs/ZER0-STACK.md`](docs/ZER0-STACK.md).

### The rest of the stack, in the same repository

The image generator, the books app, the zer0 sites and the parodynews and aieo apps live here too, imported with their full history. The zer0-mistakes theme the sites build with is developed in its own repository, [bamr87/zer0-mistakes](https://github.com/bamr87/zer0-mistakes), with its Rails theme studio, and consumed here as the gem or `remote_theme` each site declares ([ADR 0005](docs/adr/0005-theme-goes-home.md)). One registry, [`workspace.yml`](workspace.yml), describes every project, and one command, `bin/zer0`, lists, checks, tests and builds them all (`bin/zer0 list`, `bin/zer0 run check --affected`, `bin/zer0 doctor`). [`docs/MONOREPO.md`](docs/MONOREPO.md) explains the design and what still runs from the original repositories.

| Path | What it is |
|---|---|
| `packages/zer0-image-generator/` | The preview-image engine (`zer0-image-generator` gem) and its web panel. |
| `packages/books/` | The book projects and the `bookshelf` app that validates, compiles and edits them, being absorbed: the platform holds the books now (`content/books/`, PLAN G9) and `library/<slug>/` is the file set it generates. |
| `sites/drsai/` | The children's picture-book site and its story engine; the ABC wizard exports here. |
| `apps/parodynews/` | The Django + React parody-news app (imported as barodybroject, de-branded in ADR 0003); its models are absorbed by the content plane under PLAN M20. |
| `apps/aieo/` | AI Engine Optimization — the FastAPI + React app that scores content for AI-engine citation. |
| `sites/zer0-pages/` | The Obsidian vault + Jekyll site. |
| `sites/zer0-pages-remote/` | The minimal `remote_theme` consumer demo. |
| `sites/irony-works/` | The perpetual encyclopedia of irony — an AI-tended Obsidian vault published as a site. |
| `sites/wargames/` | OverTheWire security wargames as a Jekyll study site. |
| `sites/zer0-demo-cookbook/`, `sites/zer0-demo-garden/` | Demo sites generated by the theme's installer. |
| `sites/1987/`, `sites/2005/` | The year knowledge bases — 1987 (plain markdown, from bamr87/1987) and 2005 (a `remote_theme` site from the year-of-ai lineage). |

## How publishing works

```text
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

Everything about the *project* — content folders, content types and their fields, taxonomy, SEO thresholds, the slug template — lives in `zer0.json`, validated as you type. Everything about *your machine* lives in VS Code settings under `zer0Cms.*`. That split is why there are 44 settings here instead of 89, and why most of them are folder-scoped so one window can hold several sites.

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
| `zer0Cms.cms.aiConfigPath` | `_data/ai.yml` | The site's own AI configuration, so the editor agent and the repository's CI resolve the same model |
| `zer0Cms.cms.verifyCommand` | — | The repository's own verification command; empty means there is none, and nothing is guessed |
| `zer0Cms.agent.enabled` | `false` | The optional AI layer |
| `zer0Cms.fleet.enabled` | `false` | The Fleet, Workflows and Monitor tabs and the twelve `fleet.*`/`workflows.open`/`lane.scaffold`/`monitor.open` palette entries — read-only until `dispatchAllow` or `scaffoldAllow` |
| `zer0Cms.fleet.dispatchAllow` | `false` | Lets the console flip a lane's switch, dispatch it, re-run its last failure, cancel a run, or enable/disable its workflow file — your settings only |
| `zer0Cms.fleet.scaffoldAllow` | `false` | Lets the console write a new lane's files for you to review and commit — your settings only; it never creates the variable that arms the lane |
| `zer0Cms.fleet.roster` | `[]` | Other repositories to show beside this one, as `owner/name` |
| `zer0Cms.fleet.hub` | `bamr87/bamr87` | The fleet's hub, read only when you ask for it |
| `zer0Cms.fleet.gitfactoryUrl` | `https://bamr87.github.io/gitorio/` | Where "Open in GitFactory" points |

Full reference: [`docs/CONFIG.md`](docs/CONFIG.md).

## The `.cms/` contract

If your repo runs a content engine that emits `.cms/index/content-index.json`, zer0-CMS reads it: per-file **health**, **freshness**, and the **mechanical / substantive** issue lanes, plus the distribution worklists it writes back to `.cms/distribution/`.

If your repo has no `.cms/`, that is a normal state, not an error — the extension falls back to an honest filesystem scan and simply reports less.

## Fleet

If a repository carries a `fleet.manifest.yml` (spec `fleet/v1`, written by `wtd fleet adopt`), turning on `zer0Cms.fleet.enabled` adds three dashboard tabs. **Fleet** draws that repository's AI lanes — harness, workflow, triggers, guardrails, `*_ENABLED` switch — and, after a GitHub sign-in you answer, each switch's value, each lane's newest run, the open pull requests attributed to it, its cost from the repository's own usage ledger and the audit grade of its workflow. **Monitor** draws the same columns for a roster: the folders open in this window that carry a manifest, the repositories in `zer0Cms.fleet.roster`, and — only when you run `fleet.importHubRoster` — the hub's registry. **Workflows** catalogues every lane read-only and, behind `zer0Cms.fleet.scaffoldAllow`, writes a new lane's files (`lane.scaffold`) for you to commit, never creating the variable that arms it. The **Harness** tab needs no setting: it inventories a repository's agents, skills, workflows, lanes, switches and usage ledger, and reports where they disagree.

Five verbs act on a lane: flip its switch, dispatch it once, re-run its last failure, cancel what is in flight, and enable or disable its workflow file. All five are off until `zer0Cms.fleet.dispatchAllow` is set in *your* settings; each re-reads the manifest and re-runs the gate host-side, and asks first. The webview sends `{repo, lane}` and nothing else. A refresh costs four calls per repository whatever its lane count, and a list GitHub refuses to show renders as unknown rather than as empty. Nothing about the fleet runs at activation; the extension stores no token.

## MCP server

The extension registers a bundled MCP server with VS Code 1.101+, so Copilot agent mode (or any MCP client pointed at `dist/mcp-server.js`) gets sixteen tools:

| Tool | Safe? |
|---|---|
| `zer0_status` · `zer0_list_content` · `zer0_get_content` · `zer0_preview` · `zer0_portfolio` · `zer0_media` · `zer0_fleet_status` · `zer0_audit` · `zer0_harness_inventory` · `zer0_lane_preview` | read-only — the last four read local files only, and never open a socket |
| `zer0_contract` | runs the repository's own content engine — refuses unless `ZER0_CMS_MCP_ALLOW_EXEC=1`, which the editor sets only in a trusted workspace; `normalize-apply` writes front matter |
| `zer0_draft` · `zer0_worklist` · `zer0_ingest` | writes a draft, a worklist, or aggregate statistics under `.cms/` for a human |
| `zer0_publish` | **off by default** — needs `ZER0_CMS_MCP_ALLOW_PUBLISH=1` in the server env *and* `confirm: true` per call |
| `zer0_lane_scaffold` | **off by default** — needs `ZER0_CMS_MCP_ALLOW_SCAFFOLD=1` *and* `confirm: true`. Writes a lane's files; never creates the variable that arms it |

The preferred path is `zer0_draft`: the model writes, the person approves.

## The optional AI agent

Off unless you turn it on. With `zer0Cms.agent.enabled` and the `@anthropic-ai/claude-agent-sdk` optional dependency installed, zer0-CMS can run a content-curation agent whose every mutating tool call goes through an approve/deny card showing the diff. Read-only tools run without asking; nothing else does.

## Architecture

```text
src/core/      pure Node. No `vscode` import — enforced by eslint and by the build.
               content, governance, catering, contract, analytics, portfolio, media,
               platform (site profiles), fleet (the console's pure half), harness.
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
