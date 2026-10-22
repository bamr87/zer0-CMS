# Agent-Native Headless CMS: Rails + Django/Wagtail

> The design note the plan implements ("the note"): agent runs as content-adjacent data — Wagtail revisions, moderation tasks and graph edges — across a Django/Wagtail content plane and a Rails experience plane.

## 0. Core thesis
Treat an **agent run as content-adjacent data**, not an external script. Every agent action becomes a versioned, attributable, reviewable change in the same place an editor's change would go: a Wagtail revision, a moderation workflow task, or a graph edge. Agents use the same permission system, the same API, and the same audit trail as people.

- **Django/Wagtail is the system of record and the content-agent runtime.** It owns content, the graph, the embeddings, the tool registry, and the agent runs that change content.
- **Rails is the experience and product layer.** It owns users, sessions, personalization at request time, commerce/app logic, and agents that act on *app* state. It asks Django for content; it never writes content tables.
- **The two talk through three channels only:** the content API (GraphQL/REST), an MCP tool surface, and an event bus.

```mermaid
flowchart LR
  subgraph Django/Wagtail (content plane)
    W[Pages / StreamField / Snippets / Images]
    G[(Graph: Postgres edges + pgvector)]
    H[Harness: runs, tools, memory, evals]
    Q[Celery workers]
    API[GraphQL + REST + MCP server]
  end
  subgraph Rails (experience plane)
    R[App + users + sessions]
    P[Personalization / app agents]
    RJ[Solid Queue / Sidekiq]
    RMCP[MCP server: app tools]
  end
  FE1[Next.js / mobile / Rails views] --> API
  FE1 --> R
  R -- GraphQL --> API
  P -- MCP client --> API
  H -- MCP client --> RMCP
  W -- events --> BUS[(Event bus: Redis Streams / NATS / outbox)]
  R -- events --> BUS
  BUS --> Q & RJ
```

## 1. Where agents live
| Agent kind | Home | Why |
|---|---|---|
| Content generation, editing, translation, alt text, SEO, link suggestion, taxonomy, graph enrichment | **Django** | Needs StreamField schema, revisions, workflow, permissions, embeddings, all local. Python has the best AI ecosystem. |
| Review and quality gates (style, facts, brand, accessibility) | **Django** | Plugs into Wagtail workflow as a `Task`. |
| Personalization, recommendations, search answering at request time, support/chat over content | **Rails** (calls Django tools) | Needs user context, session, and latency control near the frontend. Content stays read-only. |
| App-domain agents (onboarding, CRM, commerce) | **Rails** | Owns that data. Exposes it to Django via MCP if content agents need it. |

Rule: **an agent lives next to the data it writes.** It may *read* across the boundary through tools, but cross-plane writes go through the owning plane's API or tools, never its database.

## 2. Agents and content models
### 2.1 A schema the model can read
StreamField is a schema. Export it:
- `wagtail_ai_schema` management command or endpoint: walk each page model's `content_panels` and StreamField blocks, then emit **JSON Schema** per block (with `help_text` as descriptions, plus allowed child blocks).
- Tools take and return **block JSON that matches that schema**. Validate with `StreamBlock.to_python` and `clean()` before saving. The model never writes HTML into a RichText blob that Wagtail doesn't understand.

### 2.2 Agent mixin on pages
```python
class AgentManagedMixin(models.Model):
    agent_policy = models.CharField(choices=[("off","Off"),("suggest","Suggest"),("draft","Draft"),("auto","Auto-publish low risk")], default="suggest")
    ai_summary   = models.TextField(blank=True)          # agent-maintained, editable
    ai_keywords  = ArrayField(models.CharField(max_length=64), default=list, blank=True)
    content_hash = models.CharField(max_length=64, blank=True)  # drives re-embedding
    class Meta: abstract = True
```
- **Writes always create a `Revision`** with `user=<agent service user>`, never `publish()` directly unless policy is `auto` and the eval gate passed.
- One Django user per agent (`agent:seo`, `agent:editor`) in an **Agents** group, with ordinary Wagtail page permissions. Collection permissions cover images. Permission checks come free.
- Per-block provenance: a hidden `meta` StructBlock child or a sidecar table `BlockProvenance(page_revision, block_id, run_id, model, prompt_version, accepted_by)`. StreamField block UUIDs make this stable.

### 2.3 Suggestions, not mutations
Model: `Suggestion(target_ct, target_id, block_id, op[insert|replace|delete|meta], payload JSON, rationale, run, status)`. Show suggestions in the editor as a side panel (a Wagtail `admin` hook plus a Draftail/StreamField sidebar or `wagtail-ai`-style panel). Accepting one applies it to a new revision. This is what makes it feel native: editors work with tracked changes, not a chatbot.

### 2.4 Media
- On `Image` and `Document` save, events trigger: alt text, captions, object tags, focal point (fill `focal_point_*`), OCR or transcription for documents, and an embedding.
- Store these in custom `AbstractImage` fields (`ai_alt`, `ai_tags`, `embedding`) so they appear in the API automatically.

### 2.5 API extensions
- **GraphQL (Grapple or Strawberry):** expose `aiSummary`, `related(first, kind)`, `entities`, `semanticSearch(query, filters)`, and `suggestions(pageId)` (auth required). Mutations: `requestAgentRun(agent, target, input)` returns a `runId`, and `acceptSuggestion(id)`.
- **REST:** `/api/v2/agent-runs/` (create, get, stream with SSE) and `/api/v2/graph/` (neighbors, path).
- **MCP server** (`django-mcp` or a small FastMCP app mounted beside Django). Tools such as `content.search`, `content.get_page`, `content.get_schema`, `content.propose_edit`, `graph.neighbors`, `graph.upsert_edge`, `media.describe`. The same tool registry backs the internal harness, MCP, and GraphQL. **One definition, three surfaces.**

## 3. Agent loops
Every loop has the same shape: **trigger, gather context (graph plus RAG), plan or act with tools, validate (schema, policy, evals), propose (a suggestion or revision), human gate (by policy), then learn (feedback into memory and evals).**

| Loop | Trigger | Output | Gate |
|---|---|---|---|
| Draft from brief | Editor creates page with brief block | Draft revision, body blocks | Editor |
| Edit/rewrite | Editor selects blocks, "improve" | Suggestions | Editor accept |
| Review | Wagtail workflow `AgentReviewTask` | Pass/fail + comments (Wagtail comments API) | Blocks workflow on fail |
| SEO | Revision saved / nightly | `seo_title`, `search_description`, internal link suggestions, schema.org JSON-LD | Suggest, or auto for meta fields |
| Graph enrichment | Publish event | Entities, edges, embeddings | Auto (low risk), confidence threshold |
| Freshness | Cron per content type | Stale flags, update suggestions | Editor |
| Translation | wagtail-localize sync | Translated draft per locale | Locale editor |
| Personalization | Rails request | Variant selection / block ordering | Runtime, guarded by evals offline |

**Review as a native workflow task:**
```python
class AgentReviewTask(Task):
    agent = models.CharField(max_length=64)  # "brand", "factcheck", "a11y"
    def on_action(self, task_state, user, action_name, **kw): ...
    def start(self, workflow_state, user=None):
        ts = super().start(workflow_state, user)
        run_agent.delay("review", target=workflow_state.content_object.pk, task_state=ts.pk)
        return ts
```
The Celery job approves or rejects the `TaskState` and writes Wagtail comments onto blocks. Editors see it in the normal moderation UI.

## 4. Harness (native, not bolted on)
Build a small `agents` Django app. These are plain models, so they appear in Wagtail admin as snippets or reports.

```python
class AgentDefinition(models.Model):      # versioned, editable in admin (snippet + RevisionMixin)
    slug, system_prompt, model, tools = ArrayField(...), policy, max_steps, budget_usd
class AgentRun(models.Model):
    agent, version, trigger, target_ct, target_id, status, input JSON, output JSON,
    cost_usd, tokens, started_by(user|event), parent_run (graphs of runs), trace_id
class AgentStep(models.Model):            # each model call / tool call
    run, idx, kind[llm|tool|human], name, args JSON, result JSON, latency_ms, error
class Memory(models.Model):               # scoped long-term memory
    scope[global|site|section|page|user|agent], scope_id, key, value, embedding, ttl
class EvalCase(models.Model):  agent, input JSON, expected JSON|rubric, tags
class EvalResult(models.Model): case, run, scores JSON, passed
```

- **Orchestration:** run as a Celery task with an explicit state machine (LangGraph works well here, with a Postgres checkpointer keyed by `AgentRun.id`). That gives you resume, human-in-the-loop interrupts (a `human` step waits for suggestion acceptance), and replay.
- **Tools:** register with a decorator that gives a JSON schema, a permission check against the agent's Django user, side-effect class (`read|propose|write|publish`), and a rate limit. The harness refuses `publish` unless the definition's policy allows it.
  ```python
  @tool(effect="propose", perms=["wagtailcore.change_page"])
  def propose_block_edit(page_id: int, block_id: str, new_value: dict, rationale: str) -> SuggestionOut: ...
  ```
- **Memory layers:** (1) run scratchpad in the checkpointer, (2) `Memory` rows scoped to page, section, site or user, (3) the content graph itself as semantic memory, (4) the style guide and brand rules as Wagtail snippets the agent reads. Editors can edit memory, which keeps it trustworthy.
- **Evaluation:** each `AgentDefinition` revision must pass its `EvalCase` suite (in CI and on publish of the definition), using schema validity, rubric LLM-judge, link validity, readability, banned terms, and regression vs. last version. Online, accept/reject rates on suggestions are the main metric. Record them on `Suggestion.status`.
- **Observability:** OpenTelemetry spans per step (`trace_id` on `AgentRun`), exported to Langfuse, Phoenix or your APM. Add a Wagtail admin report page with runs, costs, and failure rates.
- **Rails harness:** a mirror with the same tables in Rails (`agent_runs`, `agent_steps`), using `ruby_llm` or `langchainrb` plus an MCP client, and Solid Queue. Propagate a shared `trace_id` across planes.

## 5. Graphs
Start in **Postgres**: edges table plus pgvector, and optionally Apache AGE for Cypher. Move to Neo4j only if traversal depth or volume demands it.

```python
class Entity(models.Model):        # Wagtail snippet: person, org, product, topic, place
    kind, name, slug, aliases ArrayField, description, same_as ArrayField (Wikidata/URLs), embedding VectorField(1536)
class Edge(models.Model):
    src_ct, src_id, rel, dst_ct, dst_id, weight, confidence,
    source[editor|agent|structural|rails], run FK null, valid_from, valid_to
    class Meta: unique_together = ("src_ct","src_id","rel","dst_ct","dst_id")
```
- **Structural edges come free:** derive them from Wagtail on publish: page tree (`child_of`), `PageChooserBlock`/`SnippetChooserBlock` references (Wagtail's `ReferenceIndex` already tracks these, so reuse it), tags, categories, locale `translation_of`.
- **Semantic edges come from agents:** `mentions`, `about`, `similar_to` (vector kNN), `contradicts`, `supersedes`. Each carries `confidence` plus `run`. Below the threshold it becomes a Suggestion; above it, it's written directly.
- **Behavioral edges come from Rails:** `viewed_together`, `converted_after`, and user to topic affinity. Rails emits events, and Django aggregates them nightly into weighted edges. Raw user data stays in Rails, and only aggregates cross the boundary.
- **Agent tools:** `graph.neighbors(node, rel?, depth≤2)`, `graph.path(a,b)`, `graph.search(text) → nodes`, `graph.upsert_edge(...)` (propose effect). **GraphRAG retrieval** goes semantic search, then a 1–2 hop expansion, then rerank, then context. This beats flat RAG for internal linking and "related" features.
- **API:** `related` and `entities` fields on every page type in GraphQL, so frontends get graph features with no extra calls.

## 6. Recommended stack
- Django side: Wagtail 6+, Grapple or Strawberry-Django, `wagtail-localize`, Celery + Redis, Postgres + `pgvector` (+ optional AGE), LangGraph *or* a hand-rolled state machine (keep tools framework-agnostic), LiteLLM for provider routing, FastMCP / `django-mcp-server`, Langfuse/OTel, `wagtail-ai` as a reference for editor UX.
- Rails side: Rails 8, Solid Queue, `ruby_llm` (or `langchainrb`), `ruby-mcp` client/server, GraphQL client (`graphql-client`) with persisted queries, edge caching.
- Shared: an event bus via **transactional outbox** on both sides (to Redis Streams or NATS), event schemas in a shared repo (JSON Schema/CloudEvents), shared `trace_id`.

### Event contracts (examples)
`content.page.published {page_id, revision_id, locale, content_hash}` · `content.suggestion.created` · `agent.run.completed {run_id, agent, status}` · `app.user.interaction {anon_id, page_id, kind}` (Rails, aggregated).

## 7. Headless, multi-frontend
- Frontends consume **outputs, not agents**: summaries, related links, JSON-LD, and variants are stored fields or computed resolvers, cacheable and identical for Next.js, mobile, and Rails views.
- Interactive AI (chat over content, live search answers) is a **versioned API endpoint** (`POST /api/v2/agents/{slug}/runs`, SSE stream) that any frontend can call, or it goes through Rails when user context is needed.
- Personalization returns **block IDs or variant keys**, not generated HTML, so each frontend renders natively and the CDN can cache base content.
- The MCP surface also serves external AI clients (IDE assistants, partner agents) under the same permissions.

## 8. Example flows
**A. Editor drafts an article**
1. Editor creates an `ArticlePage` with a Brief block, then clicks "Draft with agent". GraphQL `requestAgentRun("drafter", page)`.
2. A Celery job runs LangGraph: `get_schema`, `graph.search(brief)`, `content.search` (similar articles), plan outline, generate blocks, validate with StreamBlock, then `create_revision`.
3. The editor sees a draft revision with provenance badges, plus link and entity suggestions in the sidebar.
4. Submit to workflow: `AgentReviewTask(brand, factcheck)`, then the human approver, then publish.
5. Publish event triggers graph enrichment, embeddings, SEO meta, and cache purge. Rails' related-content reflects it instantly.

**B. Personalized homepage (Rails)**
1. A request hits Rails, which loads user affinity (Rails DB) and calls GraphQL `semanticSearch` and `related` with topic filters.
2. The Rails `HomepageAgent` (cheap model or no LLM, just a ranker) picks block order and variant keys, and logs `AgentRun` with trace_id.
3. Interactions are emitted as events. Nightly, Django updates behavioral edges, and evals check for drift and diversity.

## 9. Gotchas
- **StreamField JSON drift:** schema changes break stored agent outputs and evals. Version the exported schema and include it in `AgentRun`.
- **Revision bloat:** agents saving every step floods revisions. Keep intermediate work in the checkpointer and save one revision per accepted outcome.
- **Permission leaks via tools:** every tool must resolve to the agent's Django user. Never use a superuser service account. MCP calls from Rails carry a scoped token mapping to a specific agent user.
- **Prompt injection from content:** page content and user input are data. Tools with `write` or `publish` effects require policy plus an eval gate, and review agents should not have publish tools.
- **Cost and latency:** cache embeddings by `content_hash`. Batch enrichment. Use small models for classification and ranking, and large ones only for drafting.
- **Embedding/model upgrades:** store `embedding_model` alongside vectors and re-embed in the background, with dual-read during migration.
- **Two runtimes, one truth:** don't duplicate content state in Rails beyond caches. Invalidate via events, never by polling.
- **Localization:** run agents per locale. Graph edges are locale-aware (`translation_of` links them).
- **Evals before autonomy:** start every agent at `suggest`, and promote to `draft` or `auto` only when its accept rate and eval scores clear the threshold you set.

## 10. Build order
1. Agent users + permissions, `AgentRun/Step`, tool registry, Suggestion model + editor sidebar.
2. Schema export + validated block tools, then the Drafter and SEO agents.
3. pgvector embeddings + structural edges from ReferenceIndex, then the `related` and `semanticSearch` API.
4. `AgentReviewTask` in workflows + eval suites in CI.
5. MCP server; Rails MCP client + personalization agent; event bus with outbox.
6. Entity extraction + GraphRAG, then behavioral edges from Rails.
