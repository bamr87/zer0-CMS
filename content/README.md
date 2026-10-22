# `content/` — the platform

The Django 5.2 + Wagtail 7.4 project that is zer0-CMS ([ADR 0001](../docs/adr/0001-target-architecture.md), [ADR 0004](../docs/adr/0004-one-platform.md)): pages and their revisions, the agent harness and its one tool registry, suggestions, the content graph, the transactional outbox, the GraphQL, REST and MCP surfaces over all of it, and the operational baseline every one of them answers through. The Jekyll files stay the source of truth for a site until it cuts over (ADR 0002), and the importer and exporter keep both directions exact.

```bash
cd content
pip install -r requirements-dev.txt
pip install -r requirements-providers.txt                           # optional: the model providers' SDKs (ai/README.md)
python manage.py migrate && python manage.py sync_agents --publish   # agent users, definitions, evals → live
python manage.py import_jekyll --site drsai --path ../sites/drsai     # a site → pages
python manage.py seed_demo                                            # or a demo site, the person `editor` and suggestions to review
python manage.py createsuperuser && python manage.py runserver        # http://localhost:8000/studio/ (built in ../web), /admin/

python -m pytest -q -m "not slow"                  # the fast tier (SQLite, ~40 s)
python -m pytest -q                                # + round trips of the two big in-repo sites
DATABASE_URL=postgres://… python -m pytest -q      # the same suite on Postgres + pgvector
python manage.py makemigrations --check --dry-run
python manage.py run_evals --all --recorded        # every agent's eval suite, no network
python manage.py graphql_schema --out ../schemas/graphql/schema.graphql
python manage.py wagtail_ai_schema --out ../schemas/content/ai-schema.json
ruff check . && ruff format --check .
```

With Docker, from the repository root: `docker compose --profile content up -d --wait` starts Postgres (pgvector), Redis, this app on <http://localhost:8000>, a Celery worker and beat, and the outbox relay. The web role is gunicorn on threaded workers, configured once in [`gunicorn.conf.py`](gunicorn.conf.py) (gunicorn reads it from the working directory): a run's event stream holds a request for up to five minutes, which a sync worker cannot do — gunicorn kills it at its 30 s timeout mid-stream.

## Apps

| App | What it owns | Read first |
|---|---|---|
| `config/` | settings (base / development / production / testing, all from the environment), URLs, Celery | `config/settings/base.py` |
| `cms/` | page types (`SiteRootPage`, `CollectionPage`, `ArticlePage`, `StandardPage`, `BookPage`, `ChapterPage`) and the fields a person edits on each (`editor_fields`), the `AgentManagedMixin`, StreamField blocks, the image model, `Category` and `BrandRules` snippets, the `content.*` and `media.*` tools, the publish signal; the page services — save a draft, create, publish now, schedule a publish and an expiry (both carried out by Celery beat, `cms/tasks.py`, one page per transaction), unpublish, revert — each taking the page row's lock and honouring Wagtail's locks (`writable`); the pages a person finds (`visible_pages`); and `manage.py seed_demo` | `cms/models.py`, `cms/services.py`, `cms/blocks.py` |
| `agents/` | definitions, runs (and `AgentRun.objects.visible_to`, the one scope every surface reads runs through: a person's own runs and the runs behind what they may review), steps, memory, evals, tokens; the registry, the LLM layer, the runner, the schema export, agent principals; the YAML definitions and their recordings | [`agents/README.md`](agents/README.md) |
| `ai/` | the AI content layer: provider adapters behind one registry (the only place a vendor SDK is imported), the model catalog, output schemas, assistants, pipelines, briefs and conversations — every generation an agent run, every result reviewed | [`ai/README.md`](ai/README.md) |
| `suggestions/` | `Suggestion` (and `Suggestion.objects.visible_to`, the one scope every surface reads suggestions through), `BlockProvenance`, the accept/reject flow, the brand guard (ported from the extension), the editor panel and views | `suggestions/services.py` |
| `graph/` | `Entity`, `Edge`, `Embedding`, behavioural counts; structural edges, kNN, related, semantic search, GraphRAG | [`graph/README.md`](graph/README.md) |
| `workflow/` | `AgentReviewTask`, a Wagtail workflow task a review agent decides | `workflow/models.py` |
| `outbox/` | `OutboxEvent`, `ProcessedEvent`, `emit()`, the relay to Redis Streams, deduplicating consumers | [`outbox/README.md`](outbox/README.md) |
| `api/` | GraphQL additions (Grapple), REST endpoints, the CSRF-aware GraphQL view; the studio's endpoints — the session (`session.py`), sites, pages, revisions and publishing (`pages.py`), the review inbox (`review.py`), their shapes (`serializers.py`) — and the built studio at `/studio/` (`studio.py`) | `api/views.py`, `api/pages.py` |
| `mcp_server/` | MCP over Streamable HTTP (`/mcp/`) and stdio, over the one registry | [`mcp_server/README.md`](mcp_server/README.md) |
| `importers/` | Jekyll sites and parodynews's dump → pages and the AI content layer; `ImportedSource` (a page's file) and `ImportedRecord` (an AI row's digest), so a re-import never overwrites what was changed here (`--force` aside) | `importers/jekyll.py` |
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
| `/studio/` | The studio (`../web/`, built into `../web/studio/dist`, assets under `/static/studio/`): Write (with its AI panel), Create (pages, briefs, conversations), Review, and the AI area (agent runs, assistants, pipelines, output schemas, conversations, providers, models); every path under it answers its `index.html` with an enforced, per-request-nonce CSP. 503 with the build command when it has not been built |
| `/admin/` | Wagtail: pages, the suggestions panel and view, snippets (agents, memory, entities, brand rules, categories), Reports → Agent runs — the operator fallback until the studio covers it (ADR 0006) |
| `/graphql/` | Grapple's schema for every page type, plus `semanticSearch`, `graphSearch`, `related`, `entities`, `suggestions`, `agentRun`, `aiSchema`; mutations `requestAgentRun`, `acceptSuggestion`, `rejectSuggestion`. The committed SDL is [`schemas/graphql/schema.graphql`](../schemas/graphql/schema.graphql). |
| `/api/v2/` | Wagtail API v2 (`pages`, `images`, `documents`), `agent-runs/` (create, list, read, `stream/` as SSE — a browser's `EventSource` included), `agents/<slug>/runs`, `graph/{neighbors,path,related,search}/`, `suggestions/`, `tools/`; for people in the studio and the extension: `me`, `session/{login,logout}`, `sites/`, `content/types/`, `content/pages/` (any status, filtered, paginated; create as a draft) and per page `types/`, save a draft (`PATCH`, naming the revision it was edited from), `publish/`, `unpublish/`, `schedule/` (a time to go live, a time to come down, or both), `unschedule/`, `revisions/`, `revisions/compare/`, `revisions/<id>/revert/`; `review/suggestions/` (with diffs) and `review/runs/<id>/accept/` (the `ids` a person saw). A person finds the pages Wagtail's explorer would show them, opens only those they may edit or publish, and cannot write a page a Wagtail lock keeps from them (409 `resource.locked`) |
| `/api/v2/ai/` | the AI content layer: `providers/`, `models/`, `output-schemas/`, `assistants/`, `pipelines/`, `briefs/`, `conversations/`, `messages/` — runs answer `202` and are followed on `agent-runs/<id>/stream/` ([`ai/README.md`](ai/README.md)) |
| `/mcp/` | MCP, bearer-token authenticated (`manage.py agent_token <slug> --name …`) |
| `/healthz`, `/readyz`, `/version` | liveness (touches nothing), readiness (database, cache, Redis — 503 with `checks` when one is down), the build (`name`, `version`, `commit`, `built_at`) |
| `/api/v2/openapi.json`, `/api/v2/docs/` | the OpenAPI document (committed at [`schemas/openapi/openapi.json`](../schemas/openapi/openapi.json), drift-checked) and its UI where `API_DOCS_ENABLED` |

Every response carries `X-Request-Id` (echoed when a client sent one) and `X-App-Version`; every non-2xx a REST path returns is the envelope in [`ops/README.md`](ops/README.md), and GraphQL and MCP carry the same `code` and `request_id` in their own error shapes.

## Tests

`tests/` mirrors the plan's milestones: `cms/` (M4; P4: `test_tasks.py`), `api/` (M5, M12; P4: `test_session.py`, `test_pages.py`, `test_review.py`, `test_studio.py`), `importers/` (M6, M7, G8), `outbox/` (M8, both planes' contracts), `agents/` (M9, M12), `suggestions/` (M10), `schema/` (M11), `graph/` (M13, M17), `workflow/` (M14), `mcp/` (M15), `ops/` (G1; P4: `test_server.py`), `ai/` (G8). The session database runs `sync_agents --publish` once, so every test starts from live, eval-passed agents; no test reaches a network or a model provider.
