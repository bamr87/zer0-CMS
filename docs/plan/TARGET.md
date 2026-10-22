# TARGET — what zer0-CMS is being rebuilt into

> The destination of [ADR 0006](../adr/0006-one-python-platform.md), described once: one Python platform, one React frontend, the VS Code extension as a client with the same capabilities, an AI content layer, the manage → monitor → improve loop for sites, and every merged repository absorbed. The build order is [`PLAN.md`](PLAN.md) § 3; the per-capability status is [`capabilities.yml`](capabilities.yml).

When this file and today's code disagree, today's code is what runs and this file is where it is going. When this file and a newer ADR disagree, the ADR wins and this file is updated in the same pull request.

## The shape

| Part | Path | What it is | Language |
|---|---|---|---|
| The platform | `content/` | Django + Wagtail (headless) + Celery + Postgres/pgvector + Redis. The system of record, the agent runtime, every API (REST, GraphQL, MCP, server-sent events), every background job. | Python |
| The studio | `web/studio/` | The React app where people manage, review and create content and operate their sites. | TypeScript |
| The site renderer | `web/site/` | Pre-renders each site from its exported source tree into the static public site, with the zer0 design as React components. | TypeScript |
| Shared web code | `web/packages/` | The API client generated from `schemas/`, the design tokens, and the UI components the studio and the extension's webviews share. | TypeScript |
| The extension | `src/` | The VS Code client: the studio's editor-shaped capabilities over the same API, plus file mode for sites still on files. | TypeScript |
| Contracts | `schemas/` | The committed OpenAPI document, GraphQL schema, agent block schema and event schemas. Clients are generated from them; CI fails when they drift. | JSON |
| Tooling | `tools/`, `bin/zer0` | The workspace tool and the repository's gates. | Python |

Nothing else remains at the end: `rails/`, `apps/`, `packages/` and the Jekyll parts of `sites/` are sources being absorbed. A site's *content* stays in git as its exported source tree (`sites/<name>/`), which is what the renderer builds in CI.

## Capabilities

The full list, with each capability's surfaces and status, is the `platform:` section of [`capabilities.yml`](capabilities.yml). By domain, with the library each is built on:

| Domain | Capabilities | Built on |
|---|---|---|
| Content model | page types and fields, StreamField blocks, reusable snippets, navigation menus, taxonomy (tags, categories, series, authors, entities), the exported agent block schema | Wagtail pages, StreamField, snippets, taggit |
| Authoring | block editor with Markdown round trip, front matter and SEO fields, autosave, live preview in the site's design, bulk actions | TipTap (ProseMirror) in `web/`, Wagtail headless preview |
| Versions and review | revisions with diff, compare and revert, editorial workflows with assignments and moderation states, comments and mentions, page locking, scheduled publish and unpublish | Wagtail revisions, workflows, comments, locking; Celery beat |
| Localization | locales, translation workflow, per-locale trees | Wagtail i18n, wagtail-localize |
| Search | full-text, faceted filters, semantic search, search promotions | Wagtail search (Postgres), pgvector |
| Media | image and document library with collections, focal points, renditions, AI alt text, AI preview/social images, compositions, SVG studio, FreeSVG sourcing | Wagtail images and documents; the image engine absorbed from `zer0-image-generator` |
| Delivery | REST + OpenAPI, GraphQL, MCP, server-sent events, webhooks, outbox events, redirects, forms and submissions | DRF, drf-spectacular, django-filter, the existing GraphQL schema, Wagtail redirects and forms |
| AI content layer | provider adapters, model catalog, assistants, pipelines, output schemas, briefs, conversations, tool-using agents, suggestions, evals, usage and budgets | `anthropic`, `openai`, `claude-agent-sdk`, `litellm`, `jsonschema`; the existing agent runtime |
| Sites | registry and settings, design and skins, sync, render, deploy, doctor | Celery jobs; the renderer; GitHub Actions/Pages |
| Monitoring | uptime, broken links, performance and Core Web Vitals, accessibility, SEO checks, analytics ingest, AIEO scores, alerts | `httpx`; PageSpeed Insights/CrUX APIs; axe-core under Playwright in a browser worker; GA4 Data API, Search Console API, DataForSEO |
| Improvement | the evolution loop, editorial plan and pillar coverage, measured outcomes | the agent runtime, Suggestions |
| AIEO | the analyzers and five-dimension scoring, patterns, audits of pages, URLs and crawled sites, citation tracking, the ten AIEO agents, connectors, reports, the `aieo_*` MCP tools | absorbed from `apps/aieo/`; Qdrant replaced by pgvector |
| Distribution | channels (LinkedIn, WordPress, GitHub pull request), a queue with approval, the ledger keyed by canonical URL, statistics | `httpx`, PyGithub |
| Books | books and chapters, continuity, manuscripts, the ABC wizard | absorbed from `packages/books/` and `rails/lib` |
| Accounts and access | email sign-up and login by code, OIDC SSO, GitHub login, MFA (TOTP, passkeys), sessions, personal API tokens, agent tokens, roles and per-site permissions, ownership and sharing | django-allauth (account, socialaccount, mfa, usersessions, headless), Wagtail groups and permissions |
| Operations | install wizard and bootstrap, jobs with live logs, audit log, notifications and email, error reporting (Sentry, GitHub issues), probes, logs, metrics, traces, backups, deploy | Celery, Wagtail log entries, django-anymail, sentry-sdk, OpenTelemetry, compose and Helm |

The frontend's own libraries: React 19, TypeScript, Vite; React Router 7 and TanStack Query; Mantine (the fleet console's precedent) for components and charts; TipTap for the editor; `openapi-typescript` + `openapi-fetch` for the generated client; jsdiff for diffs; Vitest, Testing Library and Playwright for tests. The renderer's: unified (remark/rehype) with kramdown-compatible plugins, `liquidjs` for Liquid in content, React server rendering under a Vite build, `feed`, `sitemap`, Pagefind for search, and Obsidian plugins (wikilinks, embeds, callouts) with a TypeScript port of zer0-pages's Dataview subset. A milestone may choose differently; it records the choice and the reason here.

## The AI content layer (`content/ai/`)

Rebuilt from barodybroject's model (`apps/parodynews/src/parodynews/models/ai.py`, `conversation.py`, `content.py`) onto the platform's agent runtime, so everything it does is costed, traced, budgeted and reviewable.

| Entity | Replaces (barodybroject) | Shape |
|---|---|---|
| `ProviderConfig` | `AIProviderConfig`, the `AI_PROVIDERS` setting | One row per provider: enabled, default (one only, by constraint), base URL, organization, project, default model, extra; the credential encrypted at rest and write-only over the API, falling back to the environment |
| `ModelEntry` | `AIModel` | Provider + model id (unique together), display name, capabilities (structured output, tools, vision, context), prices, active; synced from the provider by a job |
| `OutputSchema` | `JSONSchema`, the bundled schemas | A JSON Schema (validated as a schema on save), version, a render template that maps a result to Markdown and blocks, bundled flag; the parody-article, news-article and content-detail schemas are seeded |
| `Assistant` | `Assistant` | Persona: instructions, prompt template, model, parameters (temperature, top_p, max tokens), output schema; owner, site and visibility. **Effect `propose` only** — an assistant never writes or publishes |
| `Pipeline`, `PipelineStep` | `AssistantGroup`, `AssistantGroupMembership` | Ordered steps, each an assistant and what it reads (previous output, the conversation, the brief, a page field) |
| `Brief` | `ContentDetail`, `ContentItem` | A request to create: prompt, site and target (page type, parent), assistant or pipeline, schema; status; the structured result; the draft it produced |
| `Conversation`, `Message` | `Thread`, `Message` | Owned threads; messages with role, text, structured result, assistant, the run that produced it, status, usage and error; full history replayed to any provider; a message can become a brief or a draft |
| runs | in-request generation | Every generation is an `AgentRun` (the built-in assistant runner, whose tools are propose-only) executed by Celery; the client gets `202` and a run id and follows `/api/v2/runs/<id>/events` |
| posts | `Post`, `PostFrontMatter`, `PostVersion` | Wagtail article pages and their revisions; publishing to GitHub as a pull request is a distribution channel |

Providers are adapters behind one registry, `content/ai/providers/`: each implements `complete`, `stream`, `structured` (a JSON Schema in, a validated object out), `list_models` and `health`, and declares its capabilities. `claude_code`, `anthropic`, `openai`, `litellm` (any other vendor), `recorded` and `fake` are the first six; `agents/llm.py` becomes a thin front over the registry. Adding a provider is one module and one registry entry. No other module imports a provider SDK.

Tool-using agents (`AgentDefinition`, GitOps, eval-gated, policies) are unchanged. Assistants are the layer people edit; agents are the layer that may call tools. Both produce suggestions, never silent writes.

## Sites: manage, monitor, improve

- **Manage** (`sites`, `jobs`): `ManagedSite` (the Wagtail site, its checkout, `content_source` files or platform, domains, deploy target), per-site settings (SEO defaults, analytics, navigation, brand voice, design and skin, budgets), and jobs — sync, render, deploy, preview, doctor — with live logs, artifacts and cancel.
- **Monitor** (`monitor`): per-site checks on a schedule — uptime, broken links, performance and Core Web Vitals, accessibility, SEO, the doctor, analytics ingest, AIEO audits — each run storing findings (rule, severity, page, evidence, first seen, last seen, resolved) with history, trends and alerts (email, webhook, GitHub issue).
- **Improve** (`evolve`): an editorial plan per site (narrative, pillars with target shares, directives) and agents that read findings, analytics, AIEO scores and the plan, then propose refreshes, fixes, internal links, new topics and citability rewrites — as suggestions and briefs, at policy `suggest`, within the site's budget. Accepted proposals are measured against the same signals afterwards, so the loop learns which proposals pay off.

## AIEO in the platform (`aieo`)

All of `apps/aieo/`: the analyzers and the five-dimension scoring engine as modules; patterns as snippets; audits of a page, a URL or a crawled site, with evidence; citation tracking (asking AI engines, through the adapters, whether they cite the site) on a schedule; GA4, Search Console and DataForSEO connectors as site settings; the ten AIEO agents as agent definitions at `suggest`; the content lifecycle (topics → research → drafts → rewrites → published → landing pages) as briefs, suggestions and page types; reports as job artifacts; the CLI as `manage.py` commands; the MCP tools under the platform's server with their `aieo_*` names kept as aliases; WordPress publishing as a distribution channel. AIEO scores are a monitor signal and an input to the improvement loop.

## The studio

| Area | What a person does there |
|---|---|
| Home | what needs attention: review queue, failing checks, recent runs, scheduled publishes, site health |
| Content | sites → page tree and filtered lists; the editor (blocks, Markdown, fields, SEO, preview, revisions, comments, locking, schedule) |
| Review | one inbox: suggestions with diffs (accept, reject with reason, accept all of a run), workflow tasks, comments and mentions |
| Create | new page from a type, a brief, a conversation; assistants and pipelines one click away |
| AI | assistants, pipelines, output schemas, providers and models, agents (definitions, runs with step timelines, evals, tokens), usage and budgets |
| Sites | registry and settings, design and skins, deploys and previews, monitor (checks, findings, trends), analytics, AIEO (audits, scores, citations), the editorial plan and improvement proposals |
| Media | library, generation runs, compositions, SVG studio, sourced library |
| Distribution | channels, queue, ledger, statistics |
| Books | books, chapters, continuity, manuscripts, the ABC wizard |
| Admin | people, groups and permissions, tokens, audit log, jobs, install and settings |

## The extension

Every capability in the content, review, create, AI and AIEO areas that makes sense next to a file is in the extension too, over the same API and the same generated client: open, create and edit pages; preview; revisions; the review inbox; briefs, assistants, pipelines and conversations; AIEO scores and monitor findings for the open page; distribution. File mode keeps working for sites still on files. Parity is tracked per capability in `capabilities.yml` (`surfaces:`), and the gate's report lists every gap. How the extension's webviews share UI with the studio is PLAN §7 P-D3.

## Rules that keep models and views manageable

- Business logic lives in services (`<app>/services.py`): views validate, call a service and serialize. A service is testable without HTTP.
- Nothing calls a model provider or the network inside a request. It enqueues a job and returns `202` with the run or job id; the client follows the event stream.
- One place scopes rows: each owned model has a `visible_to(user, site=None)` queryset method, and every view and GraphQL resolver uses it.
- Public ids are UUIDs; integer keys stay internal. No prefixed string keys.
- Settings are per site (Wagtail site settings) or per provider row, never a singleton table.
- Credentials are encrypted at rest (`cryptography` Fernet, rotatable), write-only in the API, and never logged.
- Lists are paginated (cursor pagination for messages, runs and findings), filtered with django-filter, ordered from an allow-list, and indexed for the filters they offer.
- Run-creating requests accept an `Idempotency-Key`. Throttles and budgets apply per person, per site and per provider.
- Assistants, pipelines and schemas export and import as YAML, so a site's AI setup can live in git like agent definitions do.
- Tests never reach a live model or service: `fake` and `recorded` adapters, recorded HTTP for connectors.
