# TARGET — what zer0-CMS is being rebuilt into

> A comprehensive application for writing articles, creating content, brainstorming ideas, gathering information, operating a news site and writing books — a robust React frontend over a Python and Postgres backend, with AI integrations and pipelines and workflows throughout. The decision is [ADR 0006](../adr/0006-one-python-platform.md); the build order is [`PLAN.md`](PLAN.md) § 3; the per-capability status is [`capabilities.yml`](capabilities.yml).

When this file and today's code disagree, today's code is what runs and this file is where it is going. When this file and a newer ADR disagree, the ADR wins and this file is updated in the same pull request.

## What it is for

People use zer0-CMS to do content work end to end, with AI helping at every step and every AI result arriving as something a person reviews.

| Workspace | What a person does | How AI helps | Pipelines and workflows |
|---|---|---|---|
| **Write** | Write and edit articles and pages in a block editor, with fields, SEO, media and a live preview; review and publish | Draft from a brief, continue, rewrite, expand, shorten, change the voice; headlines, summaries, SEO and social metadata; fact-check against the research attached | Brief → draft → edit → review → publish; agent review (brand, accessibility, citability) before a human approves |
| **Create** | Create any content type — articles, posts, landing pages, newsletters, social posts, images — for any site, from templates or structured schemas | Generate structured content against an output schema; turn one piece into others (a post into a newsletter item, a thread, a summary) | Content pipelines that chain assistants and actions |
| **Ideas** | Capture ideas, tag and sort them on boards, vote, and promote one to a brief, an article or a book | Brainstorm angles, headlines and outlines; cluster and de-duplicate ideas by meaning; suggest ideas from research, analytics and the editorial plan | Idea → brief → assignment |
| **Research** | Gather information: save web pages, feeds, documents and notes as sources; keep quotes and citations; ask questions across them | Search the web through the providers' tools, extract and summarize pages and documents, pull out facts, quotes and entities, answer questions over the sources with citations | Feeds and searches that refresh on a schedule; sources attached to briefs and drafts |
| **Newsroom** | Operate a news site: desks and sections, the story budget, the editorial calendar, assignments and deadlines, embargoes, breaking news, home and section fronts, bylines, corrections, newsletters | Pitch stories from the wires and the research, draft and update stories, write headlines and summaries, check claims against sources | The newsroom workflow: pitch → assigned → drafting → editing → copy → scheduled → published → updated or corrected |
| **Books** | Create, structure and write books: outline, parts and chapters, characters and continuity, style guide, manuscripts | Premise → outline → chapter plan; draft, continue, rewrite or expand a chapter in the book's voice; continuity and consistency checks | Chapter pipelines; manuscript builds |
| **Sites** | Manage every site, see how each is doing, and improve it | Propose refreshes, fixes, internal links, new topics and citability rewrites from the signals | Manage → monitor → improve, with AIEO's scores among the signals |

The platform also keeps everything the merged repositories did ([`capabilities.yml`](capabilities.yml) `sources:`): parodynews's AI news workflow is the Newsroom running a parody desk, AIEO is part of Sites and Research, the books package is Books, the image generator is Media, the Rails fleet CMS is Sites.

## The shape

| Part | Path | What it is | Language |
|---|---|---|---|
| The platform | `content/` | Django, with Wagtail as a headless content library, Celery, Postgres + pgvector, Redis. The system of record, the AI runtime, every API (REST, GraphQL, MCP, server-sent events), every job and workflow. | Python |
| The studio | `web/studio/` | The React app with the workspaces above: where people write, create, brainstorm, research, run the newsroom, write books and operate sites. | TypeScript |
| The site renderer | `web/site/` | Pre-renders each site from its generated file tree into the static public site, in the platform's own design system. | TypeScript |
| Shared web code | `web/packages/` | The API client generated from `schemas/`, the design tokens, and the workspaces and components that the studio and the extension's webviews both render. | TypeScript |
| The extension | `src/` | The VS Code client, built from the studio's code: webviews render the studio's workspaces from `web/packages/`; its own code is a thin VS Code host plus file mode for sites still on files. | TypeScript |
| Contracts | `schemas/` | The committed OpenAPI document, GraphQL schema, agent block schema and event schemas. Clients are generated from them; CI fails when they drift. | JSON |
| Tooling | `tools/`, `bin/zer0` | The workspace tool and the repository's gates. | Python |

Nothing else remains at the end: `apps/`, `packages/` and the Jekyll parts of `sites/` are sources being absorbed (`rails/` is already gone: what it did that the platform does not yet do is in [`rails-cms-spec.md`](rails-cms-spec.md)).

## Content in the database, files generated

Every article, page, site and book lives in the platform's database. Each site and each book also exists as a **statically generated set of files** — a site's source tree under `sites/<name>/`, a book's `library/<slug>/` — exported from the database byte-stably by a job that commits it, so git keeps the history and the static builds have something to read. Every exporter has an importer, and the round trip is a test. People and agents edit in the platform; a direct edit to a generated file is imported as a suggestion, never lost and never silently overwritten.

## Capabilities

The full list, with each capability's surfaces and status, is the `platform:` section of [`capabilities.yml`](capabilities.yml). By domain, with the library each is built on:

| Domain | Capabilities | Built on |
|---|---|---|
| Content model | content types (articles, pages, posts, landing pages, newsletters, social posts, books, chapters), fields, StreamField blocks, reusable snippets, navigation, taxonomy (tags, categories, series, authors, entities), the exported agent block schema | Wagtail pages, StreamField, snippets, taggit |
| Authoring | block editor with a Markdown round trip, fields and SEO, autosave, live preview, bulk actions | TipTap (ProseMirror) in `web/`, Wagtail headless preview |
| Versions and review | revisions with diff, compare and revert, editorial workflows with assignments and moderation states, comments and mentions, locking, scheduled publish and unpublish | Wagtail revisions, workflows, comments, locking; Celery beat |
| Ideas | boards, capture, voting, status, clustering, promotion to briefs | pgvector, the AI content layer |
| Research | sources (pages, feeds, documents, notes), capture, extraction, summaries, quotes and citations, question answering over sources, fact-checking | `httpx`, `trafilatura`, `feedparser`, `pypdf`, pgvector; web search through the providers' tools |
| Newsroom | desks and sections, story budget, editorial calendar, assignments and deadlines, embargoes, breaking news, fronts and curation, bylines and author pages, corrections and updates, newsletters | Wagtail workflows and scheduling; django-anymail for newsletters |
| Localization | locales, translation workflow, per-locale trees | Wagtail i18n, wagtail-localize |
| Search | full-text, faceted filters, semantic search, search promotions | Wagtail search (Postgres), pgvector |
| Media | image and document library, focal points, renditions, AI alt text; preview and social image generation, compositions, the SVG studio, sourced images — the image generator rewritten | Wagtail images and documents; the engine in Python (`content/media/`), its studio views in TypeScript |
| Delivery | REST + OpenAPI, GraphQL, MCP, server-sent events, webhooks, outbox events, redirects, forms and submissions | DRF, drf-spectacular, django-filter, the existing GraphQL schema, Wagtail redirects and forms |
| AI content layer | provider adapters, model catalog, assistants, pipelines, output schemas, briefs, conversations, tool-using agents, suggestions, evals, usage and budgets | `anthropic`, `openai`, `claude-agent-sdk`, `litellm`, `jsonschema`; the existing agent runtime |
| Pipelines and workflows | AI pipelines, editorial and newsroom workflows, automations (trigger → condition → action) with run history | Celery and Celery beat, the outbox, Wagtail workflows |
| Sites | registry and settings, generated file trees, render (React by default, or the Jekyll-theme option), deploy, doctor | Celery jobs; the renderer; a Jekyll server for the option (GitHub Pages' builder or a pinned container) |
| Monitoring | uptime, broken links, performance and Core Web Vitals, accessibility, SEO, analytics, AIEO scores, alerts | `httpx`; PageSpeed Insights/CrUX; axe-core under Playwright in a browser worker; GA4 Data API, Search Console API, DataForSEO |
| Improvement | the editorial plan, improvement proposals, measured outcomes | the agent runtime, Suggestions |
| AIEO | the analyzers and five-dimension scoring, patterns, audits of pages, URLs and crawled sites, citation tracking, the AIEO agents, connectors, reports, the `aieo_*` MCP tools | absorbed from `apps/aieo/`; Qdrant replaced by pgvector |
| Distribution | channels (LinkedIn, WordPress, GitHub pull request, email), a queue with approval, the ledger keyed by canonical URL, statistics | `httpx`, PyGithub, django-anymail |
| Books | books, parts and chapters, outline, characters, continuity, style guide, manuscripts, the ABC wizard, story generators | absorbed from `packages/books/`, the Rails ABC generator ([`rails-cms-spec.md`](rails-cms-spec.md)) and drsai's engine |
| Accounts and access | email sign-up and login by code, OIDC SSO, GitHub login, MFA (TOTP, passkeys), sessions, personal and agent tokens, roles and per-site permissions, ownership and sharing | django-allauth (account, socialaccount, mfa, usersessions, headless), Wagtail groups and permissions |
| Operations | install and bootstrap, jobs with live logs, audit log, notifications and email, error reporting (Sentry, GitHub issues), probes, logs, metrics, traces, backups, deploy | Celery, Wagtail log entries, django-anymail, sentry-sdk, OpenTelemetry, compose and Helm |

The frontend's own libraries: React 19, TypeScript, Vite; React Router 7 and TanStack Query; Mantine (the fleet console's precedent) for components and charts; TipTap for the editor; `openapi-typescript` + `openapi-fetch` for the generated client; jsdiff for diffs; `@hello-pangea/dnd` for drag and drop (the newsroom's budget board, PLAN G15: accessible keyboard dragging, and a CSP nonce for the styles it writes); Vitest, Testing Library and Playwright for tests. The renderer's: unified (remark/rehype) with kramdown-compatible plugins, `liquidjs` for Liquid in content, React server rendering under a Vite build, `feed`, `sitemap`, Pagefind for search, and Obsidian plugins (wikilinks, embeds, callouts) with a TypeScript port of zer0-pages's Dataview subset. A milestone may choose differently; it records the choice and the reason here.

## The AI content layer (`content/ai/`)

Rebuilt from barodybroject's model (`apps/parodynews/src/parodynews/models/ai.py`, `conversation.py`, `content.py`) onto the platform's agent runtime, so everything it does is costed, traced, budgeted and reviewable.

| Entity | Replaces (barodybroject) | Shape |
|---|---|---|
| `ProviderConfig` | `AIProviderConfig`, the `AI_PROVIDERS` setting | One row per provider: enabled, default (one only, by constraint), base URL, organization, project, default model, extra; the credential encrypted at rest and write-only over the API, falling back to the environment |
| `ModelEntry` | `AIModel` | Provider + model id (unique together), display name, capabilities (structured output, tools, vision, web search, context), prices, active; synced from the provider by a job |
| `OutputSchema` | `JSONSchema`, the bundled schemas | A JSON Schema (validated as a schema on save), version, a render template that maps a result to Markdown and blocks, bundled flag; the parody-article, news-article and content-detail schemas are seeded |
| `Assistant` | `Assistant` | Persona: instructions, prompt template, model, parameters (temperature, top_p, max tokens), output schema, the read-only tools it may use (web search, fetch, the research library); owner, site and visibility. **Effect `propose` only** — an assistant never writes or publishes |
| `Pipeline`, `PipelineStep` | `AssistantGroup`, `AssistantGroupMembership` | Ordered steps, each an assistant or an action, and what it reads (previous output, the conversation, the brief, the sources, a page field) |
| `Brief` | `ContentDetail`, `ContentItem` | A request to create: prompt, site and target (content type, parent), assistant or pipeline, schema, attached sources and ideas; status; the structured result; the draft it produced |
| `Conversation`, `Message` | `Thread`, `Message` | Owned threads, optionally about a page, a book, a brief or a set of sources; messages with role, text, structured result, assistant, the run that produced it, status, usage and error; full history replayed to any provider; a message can become an idea, a brief or a draft |
| runs | in-request generation | Every generation is an `AgentRun` (the built-in assistant runner, whose tools are read-only or propose-only) executed by Celery; the client gets `202` and a run id and follows `/api/v2/runs/<id>/events` |
| posts | `Post`, `PostFrontMatter`, `PostVersion` | Wagtail article pages and their revisions; publishing to GitHub as a pull request is a distribution channel |

Providers are adapters behind one registry, `content/ai/providers/`: each implements `complete`, `stream`, `structured` (a JSON Schema in, a validated object out), `list_models` and `health`, and declares its capabilities. `claude_code`, `anthropic`, `openai`, `litellm` (any other vendor), `recorded` and `fake` are the first six; `agents/llm.py` becomes a thin front over the registry. Adding a provider is one module and one registry entry. No other module imports a provider SDK.

Tool-using agents (`AgentDefinition`, GitOps, eval-gated, policies) are unchanged. Assistants are the layer people edit; agents are the layer that may call write tools. Both produce suggestions, never silent writes.

## Pipelines and workflows

Three kinds, one runtime, one run history:

- **AI pipelines** — ordered assistants and actions (fetch sources, transform, create a draft, notify) run as one `AgentRun` with a child run per step.
- **Editorial workflows** — Wagtail workflows with tasks and assignments: the default editorial review, the newsroom's stages, a book's chapter review. Agents may be a step (a brand or citability review) but never the last one before publishing.
- **Automations** — a trigger (an outbox event such as `content.page.published`, a schedule, a webhook, a new source item, a monitor finding), conditions, and actions (run a pipeline or an agent, create a brief, notify, move a workflow stage). Every automation run is logged with its inputs and outcome; a new automation starts paused.

## Ideas and research (`ideas`, `research`)

- **Ideas**: an `Idea` (title, notes, tags, status, votes, owner, site, links to sources and to what it became) on boards; brainstorm sessions are conversations whose results become ideas; ideas cluster and de-duplicate by embedding; one action promotes an idea to a brief, an article or a book.
- **Research**: a `Source` (URL, feed, document or note; extracted text, metadata, summary, entities; when fetched) with `Quote`s and `Citation`s; collections of sources per project; capture by URL, browser bookmarklet, feed subscription (RSS, Atom, wire feeds), upload, or a web search run through a provider's tool; question answering over a collection with citations; fact-checking a draft's claims against its sources. Research runs are read-only for the agents that do them.

## The newsroom (`newsroom`)

Desks and sections; a story budget (planned stories with slots, owners and deadlines) and an editorial calendar; assignments; the newsroom workflow (pitch → assigned → drafting → editing → copy → scheduled → published → updated or corrected) with embargoes and a breaking-news fast path; home and section fronts curated by hand or by rule; bylines and author pages; a corrections and updates log shown on the story; newsletters assembled from stories and sent; wires and feeds from Research as a pitch source; distribution and analytics from Sites. parodynews (barodybroject) is a newsroom with a parody desk, its assistants and schemas.

## Books (`books`)

Books, parts and chapters as pages; outline, characters, continuity notes and style guide as the book's own records; manuscripts compiled from the chapters. AI assistance to **create** (premise → outline → chapter plan), **manage** (structure, order, status, continuity, validation, statistics) and **write** (draft, continue, rewrite or expand a chapter; continuity and voice checks), through assistants, pipelines and conversations that read the book's context. Each book's `library/<slug>/` is its generated file set. The ABC wizard and drsai's story engine are book types and generators.

## Sites: manage, monitor, improve

- **Manage** (`sites`, `jobs`): `ManagedSite` (the Wagtail site, its generated file tree, domains, render mode, deploy target), per-site settings (SEO defaults, analytics, navigation, brand voice, design and skin, budgets), and jobs — export, render, deploy, preview, doctor — with live logs, artifacts and cancel.
- **Render**: by default the React renderer, in the platform's own design system (tokens and components seeded from the zer0 UI tokens). Per site, the **Jekyll-theme option** instead exports the file tree with `remote_theme: bamr87/zer0-mistakes@<tag>`, resolves at export what a plugin-less Jekyll cannot, and builds and deploys with a Jekyll server (GitHub Pages' builder or a pinned Jekyll container) run as an external tool. That option is the only place the theme is named.
- **Monitor** (`monitor`): per-site checks on a schedule — uptime, broken links, performance and Core Web Vitals, accessibility, SEO, the doctor, analytics ingest, AIEO audits — each run storing findings (rule, severity, page, evidence, first seen, last seen, resolved) with history, trends and alerts (email, webhook, GitHub issue).
- **Improve** (`evolve`): an editorial plan per site (narrative, pillars with target shares, directives) and agents that read findings, analytics, AIEO scores and the plan, then propose refreshes, fixes, internal links, new topics and citability rewrites — as suggestions, briefs and ideas, at policy `suggest`, within the site's budget. Accepted proposals are measured afterwards, so the loop learns which proposals pay off.

## AIEO in the platform (`aieo`)

All of `apps/aieo/`: the analyzers and the five-dimension scoring engine as modules; patterns as snippets; audits of a page, a URL or a crawled site, with evidence; citation tracking (asking AI engines, through the adapters, whether they cite the site) on a schedule; GA4, Search Console and DataForSEO connectors as site settings; the AIEO agents as agent definitions at `suggest`; its content lifecycle (topics → research → drafts → rewrites → published → landing pages) as Ideas, Research, briefs, suggestions and page types; reports as job artifacts; the CLI as `manage.py` commands; the MCP tools under the platform's server with their `aieo_*` names kept as aliases; WordPress publishing as a distribution channel. AIEO scores are a monitor signal and an input to the improvement loop.

## The studio

| Area | What a person does there |
|---|---|
| Home | what needs attention: review queue, assignments due, failing checks, recent runs, scheduled publishes, ideas to triage |
| Write | the editor (blocks, Markdown, fields, SEO, preview, revisions, comments, locking, schedule) with the AI side panel and the research attached |
| Create | new content of any type from a type, a template, a brief or a conversation |
| Ideas | boards, brainstorm sessions, promotion |
| Research | sources and collections, capture, questions over sources, fact-checks |
| Newsroom | desks, story budget, calendar, assignments, fronts, corrections, newsletters |
| Books | books, outline, chapters, characters, continuity, manuscripts, the ABC wizard |
| Review | one inbox: suggestions with diffs (accept, reject with reason, accept all of a run), workflow tasks, comments and mentions |
| AI | assistants, pipelines, output schemas, automations, providers and models, agents (definitions, runs with step timelines, evals, tokens), usage and budgets |
| Sites | registry and settings, render and deploy, monitor, analytics, AIEO, the editorial plan and improvement proposals |
| Media | library, generation runs, compositions, SVG studio, sourced library |
| Distribution | channels, queue, ledger, statistics |
| Admin | people, groups and permissions, tokens, audit log, jobs, install and settings |

## The extension

The extension is built from the studio's code, not beside it: TypeScript, React, the same component library, TanStack Query, TipTap and the same generated client. Its webviews render the studio's workspaces from `web/packages/`, themed to the editor; its own code is a thin VS Code host — commands, tree views, file decorations, editor integration, secret storage, MCP registration — plus file mode for sites still on files. So writing with the AI side panel, preview, revisions, the review inbox, briefs, assistants, pipelines and conversations, capturing an idea, citing a source, fact-checking the open draft, moving a story's stage or adding a correction, AIEO scores and monitor findings for the open page, and distribution all reach the extension the moment they exist in the studio. Libraries are bundled at build time through the esbuild allow-list, and the extension's hand-rolled YAML, glob, date and JSONC helpers give way to the libraries the studio uses. Parity is tracked per capability in `capabilities.yml` (`surfaces:`), and the gate's report lists every gap.

## Rules that keep models and views manageable

- **Less code is better.** Configure an established library before writing code; reuse a shared package before writing a second copy; delete code the platform or a library now covers. A pull request that hand-rolls a library's job says why.
- Business logic lives in services (`<app>/services.py`): views validate, call a service and serialize. A service is testable without HTTP.
- Nothing calls a model provider or the network inside a request. It enqueues a job and returns `202` with the run or job id; the client follows the event stream.
- One place scopes rows: each owned model has a `visible_to(user, site=None)` queryset method, and every view and GraphQL resolver uses it.
- Public ids are UUIDs; integer keys stay internal. No prefixed string keys.
- Settings are per site (Wagtail site settings) or per provider row, never a singleton table.
- Credentials are encrypted at rest (`cryptography` Fernet, rotatable), write-only in the API, and never logged.
- Lists are paginated (cursor pagination for messages, runs, sources and findings), filtered with django-filter, ordered from an allow-list, and indexed for the filters they offer.
- Run-creating requests accept an `Idempotency-Key`. Throttles and budgets apply per person, per site and per provider.
- Assistants, pipelines, automations and schemas export and import as YAML, so a site's AI setup can live in git like agent definitions do.
- Tests never reach a live model or service: `fake` and `recorded` adapters, recorded HTTP for connectors and captures.
