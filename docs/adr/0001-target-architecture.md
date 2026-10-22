# ADR 0001 — Target architecture: a content plane, an experience plane, and clients

- **Status:** accepted 2026-10-19; partially implemented (see [Progress](#progress))
- **Supersedes:** nothing. **Amends:** D15 and D16 in [`../ARCHITECTURE.md`](../ARCHITECTURE.md) only where the boundary below says so, and only once the milestone named there lands.
- **Inputs:** [`../plan/agent-native-design.md`](../plan/agent-native-design.md) ("the note") and [`../plan/PLAN.md`](../plan/PLAN.md) (milestones M0–M20). Decisions the plan leaves open are cited as **PLAN-D1 … PLAN-D6**, to keep them apart from the extension's D1–D17.

## Context

The monorepo merge (#29) put ten repositories and three products of this repository's own into one tree, and the review in PLAN §0 found what that left behind: five LLM clients, two ledgers, two content models shadowing the same Markdown files, two MCP surfaces in waiting, the image engine three times, and per-project infrastructure copied from every import. Each product answers "where does content live, who may change it, and how does an agent act on it" differently. A common framework has to answer those three questions once.

## Decision

zer0-CMS becomes one agent-native, headless CMS with two planes and a set of clients:

| Part | Path | Owns | Talks to the rest through |
|---|---|---|---|
| **Content plane** | `content/` — Django 5.2 + Wagtail | pages, revisions, workflow, the content graph, embeddings, the agent harness (definitions, runs, steps, memory, evals), the tool registry, suggestions, the outbox | GraphQL (`/graphql/`), REST (`/api/v2/`), MCP (`/mcp/`), events (`schemas/events/`) |
| **Experience plane** | `rails/` — Rails 8.1 | users, sessions, personalization, app data, distribution channels (LinkedIn), agents that act on app state | the content plane's APIs and MCP tools; its own outbox |
| **Clients** | `src/` — the VS Code extension | editor UX: panel, dashboard, SEO insights | the content plane's APIs and MCP server (from M18); the files on disk until then |
| **Frontends** | `sites/*` — Jekyll, built with the `jekyll-theme-zer0` theme from `bamr87/zer0-mistakes` (ADR 0005) | static rendering | exported files (M7) |
| **Shared** | `schemas/`, `tools/`, `bin/zer0`, `workspace.yml` | contracts and the workspace | — |

The rules that follow from it are in [`../../AGENTS.md`](../../AGENTS.md) § The planes and their boundary and § Agent safety rules in code. In one sentence each: an agent lives next to the data it writes; every tool declares its effect and runs as a named agent user; every agent starts at `suggest`; one revision per accepted outcome; cross-plane side effects travel as versioned events through a transactional outbox.

**One definition, three surfaces.** A tool is declared once in the content plane's registry (`content/agents/registry.py`) with its JSON Schema, effect, permissions and rate. The harness runner, the MCP server and the GraphQL/REST mutations all dispatch through that one registry, so a permission or policy check written once applies to all three.

## The open decisions, and the interim calls this ADR makes

| # | Question | Status | Interim call (reversible) |
|---|---|---|---|
| PLAN-D1 | Does content become DB-first in Wagtail, with the Jekyll repositories as exported artifacts — or do the Markdown files stay canonical, with Wagtail as an index and editor? | **Decided by [ADR 0002](0002-one-home-cutover.md)** | **DB-first, one site at a time.** A site cuts over once its round trip has been green for two releases (PLAN §4.8); until then D16 stays in force *for that site* — git is its source of truth, the content plane imports from its files (`import_jekyll`) and exports back to them (`export_jekyll`). Nothing in M16, M18, M19 or M20 that deletes a file writer, a model or a site's Markdown runs for a site before that site has cut over. |
| PLAN-D2 | Grapple or Strawberry-Django for GraphQL? | Decided here | **Grapple.** It derives types from the Wagtail models and their StreamField blocks, so a page type gains its GraphQL shape by declaring `graphql_fields`, and the plan's drift check (`manage.py graphql_schema`) is graphene's command. Nothing outside `content/api/` imports it, so a switch stays local. |
| PLAN-D3 | LangGraph with a Postgres checkpointer, or a hand-rolled state machine? | Decided here (as M9 already assumed) | **Hand-rolled.** The runner is an explicit loop over `AgentStep` rows, so the run table *is* the checkpoint, a human step is a row in state `waiting`, and replay reads the same rows. Tools stay framework-agnostic, so LangGraph can drive them later without a rewrite. |
| PLAN-D4 | Deployment target, and whether barodybroject survives as a product | **Open** | Nothing here deploys. The root `docker-compose.yml` runs the stack locally; barodybroject keeps its Azure files until D4 is decided. |
| PLAN-D5 | The hub path for `standard-ci@v2`; whether the extension stays in this monorepo | Half decided | The hub path is `bamr87/bamr87/.github/workflows/standard-ci.yml@v2` (the root `ci.yml` already calls it). Whether the extension moves to `clients/vscode/` or splits out is open, which is why M2's moves have not run. |
| PLAN-D6 | Event bus: Redis Streams or NATS? | Decided here (the plan's default) | **Redis Streams**, behind a relay with one `publish(stream, event)` method, so NATS is a second relay class rather than a change to every producer. |

Three further calls, made while implementing:

- **The LLM layer is provider-neutral, and tests never reach a provider.** `content/agents/llm.py` defines one `complete()` interface with three backends: `recorded` (fixtures, the default under test), `fake` (scripted) and `litellm` (provider routing, imported lazily and not a pinned dependency, so its large transitive tree is opt-in). The other four LLM clients in the tree (the extension agent, `rails/lib`'s Anthropic provider, barodybroject's provider layer, the books studio) are retired by M12 and M20, not by this ADR.
- **The MCP server is a Django view, not a mounted FastMCP app.** `/mcp/` speaks MCP's Streamable HTTP transport (JSON-RPC 2.0 over POST, JSON responses) and `manage.py mcp_stdio` speaks stdio, both over the same registry. Mounting an ASGI app beside Django would add a second server process and a second auth path for the same three methods (`initialize`, `tools/list`, `tools/call`).
- **Embeddings use one portable column.** `EmbeddingField` is pgvector's `vector(n)` on Postgres (the compose and CI database is `pgvector/pgvector:pg16`) and JSON text on SQLite, so development, tests and production share one migration; on SQLite the kNN is computed in Python. Every vector is stored with its `embedding_model` and the `content_hash` it was computed from, so re-embedding is skipped when nothing changed.

## Where today's code still crosses the boundary

| Crossing | Why it is still there | Removed by |
|---|---|---|
| Rails writes Jekyll files (`PageEditor`, `Zer0Cms::Cms::Writer`) | D16: the files are canonical for every site that has not cut over (ADR 0002) | M16, per site as each cuts over |
| The extension keeps its own governance queue, ledger and harness (`src/core/governance`, `src/core/harness`) | It works without a server, and the content plane's `Suggestion` and `AgentRun` are not yet reachable from the editor | M18 |
| `rails/app/services/image_engine.rb` and the Ruby port of the image engine | The content plane's media pipeline does not exist yet | M19 |
| Four other LLM clients | Their callers have not moved to the content plane's agents | M12 (ABC, story profiles), M20 |
| barodybroject's `Post`/`PostVersion`/`Assistant` models | Their data is not imported yet | M6 import, then M20 |

## Consequences

- The repository gains a fourth runtime (Python/Django) at its centre, which is ops load for a single maintainer (PLAN §7). The root compose file and `bin/zer0` keep it to one command each.
- The content plane is additive until the first site cuts over (ADR 0002): until then, removing it would leave every other product working.
- A Rails change never needs Python, an extension change never needs Python, and a content-plane change never downloads VS Code: `content.yml` is path-filtered like every other project workflow.

## Progress

Ticked milestones live in [`../plan/PLAN.md`](../plan/PLAN.md); this ADR is updated when a decision above changes, not when a box is ticked.
