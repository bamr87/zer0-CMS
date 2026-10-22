# `content/` — the platform

> The Django 5.2 + Wagtail 7.4 platform — pages and revisions, the agent harness and tool registry, suggestions, the graph, the outbox, the operational baseline, and its GraphQL, REST and MCP surfaces — and how to run it.

The Django 5.2 + Wagtail 7.4 project that is zer0-CMS ([ADR 0001](../docs/adr/0001-target-architecture.md), [ADR 0004](../docs/adr/0004-one-platform.md)): pages and their revisions, the agent harness and its one tool registry, suggestions, the content graph, the transactional outbox, the GraphQL, REST and MCP surfaces over all of it, and the operational baseline every one of them answers through. The Jekyll files stay the source of truth for a site until it cuts over (ADR 0002), and the importer and exporter keep both directions exact.

```bash
cd content
pip install -r requirements-dev.txt
python manage.py migrate && python manage.py sync_agents --publish   # agent users, definitions, evals → live
python manage.py import_jekyll --site drsai --path ../sites/drsai     # a site → pages
python manage.py createsuperuser && python manage.py runserver        # http://localhost:8000/admin/

python -m pytest -q -m "not slow"                  # the fast tier (SQLite, ~40 s)
python -m pytest -q                                # + round trips of the two big in-repo sites
DATABASE_URL=postgres://… python -m pytest -q      # the same suite on Postgres + pgvector
python manage.py makemigrations --check --dry-run
python manage.py run_evals --all --recorded        # every agent's eval suite, no network
python manage.py graphql_schema --out ../schemas/graphql/schema.graphql
python manage.py wagtail_ai_schema --out ../schemas/content/ai-schema.json
ruff check . && ruff format --check .
```

With Docker, from the repository root: `docker compose --profile content up -d --wait` starts Postgres (pgvector), Redis, this app on <http://localhost:8000>, a Celery worker and beat, and the outbox relay.

## Apps

| App | What it owns | Read first |
|---|---|---|
| `config/` | settings (base / development / production / testing, all from the environment), URLs, Celery | `config/settings/base.py` |
| `cms/` | page types (`SiteRootPage`, `CollectionPage`, `ArticlePage`, `StandardPage`, `BookPage`, `ChapterPage`), the `AgentManagedMixin`, StreamField blocks, the image model, `Category` and `BrandRules` snippets, the `content.*` and `media.*` tools, the publish signal | `cms/models.py`, `cms/blocks.py` |
| `agents/` | definitions, runs, steps, memory, evals, tokens; the registry, the LLM layer, the runner, the schema export, agent principals; the YAML definitions and their recordings | [`agents/README.md`](agents/README.md) |
| `suggestions/` | `Suggestion`, `BlockProvenance`, the accept/reject flow, the brand guard (ported from the extension), the editor panel and views | `suggestions/services.py` |
| `graph/` | `Entity`, `Edge`, `Embedding`, behavioural counts; structural edges, kNN, related, semantic search, GraphRAG | [`graph/README.md`](graph/README.md) |
| `workflow/` | `AgentReviewTask`, a Wagtail workflow task a review agent decides | `workflow/models.py` |
| `outbox/` | `OutboxEvent`, `ProcessedEvent`, `emit()`, the relay to Redis Streams, deduplicating consumers | [`outbox/README.md`](outbox/README.md) |
| `api/` | GraphQL additions (Grapple), REST endpoints, the CSRF-aware GraphQL view | `api/views.py` |
| `mcp_server/` | MCP over Streamable HTTP (`/mcp/`) and stdio, over the one registry | [`mcp_server/README.md`](mcp_server/README.md) |
| `importers/` | Jekyll sites and parodynews's dump → pages; `ImportedSource` | `importers/jekyll.py` |
| `exporters/` | pages → Jekyll files | `exporters/jekyll.py` |
| `ops/` | the probes, the request id, JSON logging and redaction, the error envelope, throttling, CORS, security headers, the OpenAPI document, error reporting | [`ops/README.md`](ops/README.md) |

## How a change travels

```text
editor or agent ──► tool (registry: schema, effect, policy, permission, rate) ──► Suggestion
                                                                                   │ editor accepts (one revision, agent-authored, with provenance)
                                                                                   ▼
                                     page revision ──► publish ──► graph index + outbox event (one transaction)
                                                                         │
                                       relay ──► Redis Stream zer0:content ──► Rails (cache purge, LinkedIn), …
```

## Surfaces

| Path | What |
|---|---|
| `/admin/` | Wagtail: pages, the suggestions panel and view, snippets (agents, memory, entities, brand rules, categories), Reports → Agent runs |
| `/graphql/` | Grapple's schema for every page type, plus `semanticSearch`, `graphSearch`, `related`, `entities`, `suggestions`, `agentRun`, `aiSchema`; mutations `requestAgentRun`, `acceptSuggestion`, `rejectSuggestion`. The committed SDL is [`schemas/graphql/schema.graphql`](../schemas/graphql/schema.graphql). |
| `/api/v2/` | Wagtail API v2 (`pages`, `images`, `documents`), `agent-runs/` (create, list, read, `stream/` as SSE), `agents/<slug>/runs`, `graph/{neighbors,path,related,search}/`, `suggestions/`, `tools/` |
| `/mcp/` | MCP, bearer-token authenticated (`manage.py agent_token <slug> --name …`) |
| `/healthz`, `/readyz`, `/version` | liveness (touches nothing), readiness (database, cache, Redis — 503 with `checks` when one is down), the build (`name`, `version`, `commit`, `built_at`) |
| `/api/v2/openapi.json`, `/api/v2/docs/` | the OpenAPI document (committed at [`schemas/openapi/openapi.json`](../schemas/openapi/openapi.json), drift-checked) and its UI where `API_DOCS_ENABLED` |

Every response carries `X-Request-Id` (echoed when a client sent one) and `X-App-Version`; every non-2xx a REST path returns is the envelope in [`ops/README.md`](ops/README.md), and GraphQL and MCP carry the same `code` and `request_id` in their own error shapes.

## Tests

`tests/` mirrors the plan's milestones: `cms/` (M4), `api/` (M5, M12), `importers/` (M6, M7), `outbox/` (M8, both planes' contracts), `agents/` (M9, M12), `suggestions/` (M10), `schema/` (M11), `graph/` (M13, M17), `workflow/` (M14), `mcp/` (M15), `ops/` (G1). The session database runs `sync_agents --publish` once, so every test starts from live, eval-passed agents; no test reaches a network or a model provider.
