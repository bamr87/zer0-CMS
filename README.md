# zer0-CMS

> An agent-native CMS for markdown sites: one Python platform (Django, with Wagtail as a headless library), a React studio and site renderer, and a VS Code extension with the studio's capabilities — publishing only through a gate a human has to walk through.

[![CI](https://img.shields.io/github/actions/workflow/status/bamr87/zer0-CMS/ci.yml?branch=main&label=CI)](https://github.com/bamr87/zer0-CMS/actions/workflows/ci.yml) [![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)

<p align="center">
  <img src="media/zer0-cms-128.png" width="96" alt="">
</p>

## Overview

zer0-CMS is becoming a comprehensive application for content work — writing articles, creating content, brainstorming ideas, gathering information, operating a news site and writing books — with AI integrations and pipelines and workflows throughout ([ADR 0006](docs/adr/0006-one-python-platform.md)). It is being rebuilt into one Python platform with a React frontend: a complete, modern CMS on established libraries; an AI content layer (provider adapters, assistants, pipelines, output schemas, briefs, conversations) that helps create and develop content; a loop that manages, monitors and improves the sites it serves, with AIEO's citability scoring in it; the VS Code extension at parity with the studio; and every repository merged here — parodynews (barodybroject), aieo, books, the image generator, the Rails fleet CMS and the nine sites — absorbed with its content and capabilities, with content in the database and generated static files, zer0-mistakes kept only as an option to render and deploy a site with that theme through Jekyll, and no Ruby left. The target is [`docs/plan/TARGET.md`](docs/plan/TARGET.md), the order of work [`docs/plan/PLAN.md`](docs/plan/PLAN.md) § 3, and the per-capability progress [`docs/plan/capabilities.yml`](docs/plan/capabilities.yml) (`python3 tools/check_absorption.py --report`). What follows describes the code as it runs today.

zer0-CMS turns a repository of markdown into something you can actually operate. Edit front matter as real controls, let agents propose changes you accept as revisions, browse every site in one admin, and publish through a gate a human has to walk through. The platform runs on 127.0.0.1:8000, the Rails fleet CMS on 127.0.0.1:3001, and the extension has zero runtime dependencies.

It began as a fork of [Front Matter CMS](https://github.com/estruyf/vscode-front-matter) and deliberately keeps its interaction design, because that design is good and people already know it. The code underneath is new. See [ATTRIBUTION.md](ATTRIBUTION.md).

The repository holds three products of its own and the rest of the zer0 stack:

| Path | What it is |
|---|---|
| `content/` | The **platform** — zer0-CMS itself ([ADR 0004](docs/adr/0004-one-platform.md), [the plan](docs/plan/PLAN.md)): a Django + Wagtail headless CMS whose agents are first-class — each one a Django user with Wagtail permissions, proposing changes as suggestions an editor accepts, every run and tool call recorded, every tool behind one registry that GraphQL, REST and MCP all share — and the system of record for every site and every API, with its operational baseline (probes, request ids, one error envelope, JSON logs, throttling, OpenAPI) in `content/ops/`. It imports the Jekyll sites and exports them back byte for byte, so a site's files stay its source of truth until it cuts over. [`content/README.md`](content/README.md) · [`content/ops/README.md`](content/ops/README.md) |
| `src/` | The **VS Code extension** — edit front matter, dashboard, and governed publish *inside the editor*; the platform's client once a platform URL is configured (PLAN G10). This README. |
| `rails/` | The **fleet CMS** — a Rails 8.1 app on Administrate that indexes every registered Jekyll site and writes edits back into its files (git stays the source of truth), draws missing previews, runs `zer0 doctor`, carries content to LinkedIn under a human gate, and hosts the ABC book wizard. Being absorbed by the platform (PLAN Phase G), then deleted. [`rails/README.md`](rails/README.md) · [`docs/PLATFORM.md`](docs/PLATFORM.md) · [`docs/DISTRIBUTION.md`](docs/DISTRIBUTION.md) |
| `packages/`, `sites/`, `apps/` | The image generator, the books app, the zer0 sites and the parodynews and aieo apps, imported with their full history: sources being absorbed into the platform (ADR 0006). The zer0-mistakes theme the sites build with is developed in [bamr87/zer0-mistakes](https://github.com/bamr87/zer0-mistakes), with its Rails theme studio, and consumed as the gem or `remote_theme` each site declares ([ADR 0005](docs/adr/0005-theme-goes-home.md)). One registry, [`workspace.yml`](workspace.yml), describes every project, and `bin/zer0` lists, checks, tests and builds them all. [`docs/MONOREPO.md`](docs/MONOREPO.md) lists each one and what still runs from the original repositories. |

How this repository, the zer0-mistakes theme and zer0-image-generator fit together: [`docs/ZER0-STACK.md`](docs/ZER0-STACK.md).

## Features

- a **metadata panel** that renders the active file's front matter as typed controls instead of raw YAML,
- a **dashboard** that lists every piece of content with search, filters and sorting,
- **SEO insights** measured against thresholds you set,
- a **governed publishing path** — draft → brand guard → human approval → publish → ledger — where nothing goes out because a script decided it should,
- a **front-matter audit** of every page against the site's own schema, whose fixes you see as a diff before any of them lands,
- **platform profiles** — Jekyll (with the zer0-mistakes theme as an overlay), MkDocs, Wiki.js, Hugo, Docusaurus, Astro and a generic fallback — so a site is read the way its own generator reads it,
- **many sites in one window**, each with its own configuration, draft queue and MCP server,
- and a **fleet console** — the Harness, Fleet, Monitor and Workflows tabs — for the AI lanes a repository runs.

## Quick start

```bash
npm install
npm run compile          # check-types + lint + all five bundles
npm run watch            # rebuild on change, then F5 in VS Code to launch the Extension Host
npm test                 # unit, golden, MCP stdio and integration suites
SITES_DIR=$HOME/github docker compose up --build                                   # fleet CMS → http://localhost:3001/admin
docker compose --profile content up -d --wait db redis content worker beat relay  # the platform → http://localhost:8000/admin/
bin/zer0 run check --affected                                                      # fast checks of every project this branch touched
```

Every port is published on 127.0.0.1 only; set `ZER0_CMS_PASSWORD` before exposing the Rails CMS anywhere else. The platform answers `/healthz`, `/readyz` and `/version`. `SITES_DIR=$HOME/github docker compose --profile imagegen up --build` adds zer0-image-generator on :3000.

## Usage

1. Install the extension and open your content repo.
2. Run **zer0-CMS: Initialize project** to write a `zer0.json`.
3. Register a content folder (right-click a folder → *Register content folder*, or add it to `zer0.json`).
4. Open a markdown file — the panel fills in.
5. Press <kbd>Alt</kbd>+<kbd>D</kbd> for the dashboard.

Everything about the *project* — content folders, content types and their fields, taxonomy, SEO thresholds, the slug template — lives in `zer0.json`, validated as you type. Everything about *your machine* lives in VS Code settings under `zer0Cms.*`. That split is why most settings are folder-scoped, so one window can hold several sites.

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

The settings that matter on day one are the gates, all off by default: `zer0Cms.governance.publishAllow` (the master publish switch), `zer0Cms.agent.enabled` (the optional AI layer), `zer0Cms.fleet.enabled` (the Fleet, Workflows and Monitor tabs, read-only), and — read from your own settings only — `zer0Cms.fleet.dispatchAllow` (the lane run verbs) and `zer0Cms.fleet.scaffoldAllow` (writing a new lane's files). Set `zer0Cms.governance.acceptStatuses` to `approved` only to force the approval step, and `zer0Cms.cms.verifyCommand` to the repository's own verification command. Every setting, its default and its scope: [`docs/CONFIG.md`](docs/CONFIG.md) §5, generated from `package.json`.

## The `.cms/` contract

If your repo runs a content engine that emits `.cms/index/content-index.json`, zer0-CMS reads it: per-file **health**, **freshness**, and the **mechanical / substantive** issue lanes, plus the distribution worklists it writes back to `.cms/distribution/`.

If your repo has no `.cms/`, that is a normal state, not an error — the extension falls back to an honest filesystem scan and simply reports less.

## Fleet

If a repository carries a `fleet.manifest.yml` (spec `fleet/v1`, written by `wtd fleet adopt`), turning on `zer0Cms.fleet.enabled` adds three dashboard tabs: **Fleet** draws that repository's AI lanes and, after a GitHub sign-in you answer, each switch's value, newest run, open pull requests, cost and audit grade; **Monitor** draws the same columns for a roster of repositories; **Workflows** catalogues every lane and, behind `zer0Cms.fleet.scaffoldAllow`, writes a new lane's files for you to commit. The **Harness** tab needs no setting: it inventories a repository's agents, skills, workflows, lanes, switches and usage ledger, and reports where they disagree. The five verbs that act on a lane (switch, dispatch, re-run, cancel, enable or disable) stay off until `zer0Cms.fleet.dispatchAllow` is set in *your* settings. Nothing about the fleet runs at activation, and the extension stores no token. How the console is bounded: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#the-fleet-console).

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

The `src/core` boundary is load-bearing, not stylistic: it is why the same publish gate runs identically from a command, a webview and an MCP client, and why the core is testable without an extension host. More: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

## Documentation

[`docs/README.md`](docs/README.md) indexes every document in the repository, one line each. Start with [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (the extension), [`docs/PLATFORM.md`](docs/PLATFORM.md) (the fleet CMS), [`docs/CONFIG.md`](docs/CONFIG.md) (every configuration key) and [`docs/MONOREPO.md`](docs/MONOREPO.md) (the imported projects).

## Project structure

| Path | Holds |
|---|---|
| `src/`, `media/`, `schemas/` | The VS Code extension, its stylesheets and templates, and the `zer0.json` schema. |
| `rails/` | The fleet CMS and the stdlib-only zer0 library. |
| `content/` | The platform: Django + Wagtail, with its operational baseline in `content/ops/`. |
| `packages/`, `sites/`, `apps/` | The imported sources being absorbed: image generator, books, sites, apps. |
| `bin/`, `tools/`, `workspace.yml` | `bin/zer0`, its registry, and the repository's gates. |
| `docs/` | Architecture, configuration, CI, releasing, ADRs and the plan. |

## Development

The Quick start builds and tests the extension. Two more:

```bash
npm run check-types && npm run lint   # the type and lint gates on their own
npx @vscode/vsce package              # build the .vsix
```

`npm run compile` failing with `Could not resolve "vscode"` means something in `src/core` or `src/mcp` imported the VS Code API. That is the layering gate doing its job. The commands for the platform, the Rails app and every imported project, and the rules every change follows, are in [`AGENTS.md`](AGENTS.md).

## Contributing

See [`CONTRIBUTING.md`](CONTRIBUTING.md) and [`AGENTS.md`](AGENTS.md); everyone taking part follows the [Code of Conduct](CODE_OF_CONDUCT.md).

## Changelog

[`CHANGELOG.md`](CHANGELOG.md), written by release-please; packaged builds are on the [releases page](https://github.com/bamr87/zer0-CMS/releases).

## License

[MIT](LICENSE). Portions © 2019 Elio Struyf (Front Matter CMS) — see [ATTRIBUTION.md](ATTRIBUTION.md).

---

<!-- bamr87-portfolio-footer -->
Part of the [bamr87 portfolio](https://github.com/bamr87) — browse every project on [Amr's GitHub profile](https://github.com/bamr87).
