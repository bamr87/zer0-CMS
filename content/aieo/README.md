# `aieo/` — AIEO in the platform

AI Engine Optimization: scoring content for how likely AI engines are to cite it, auditing pages, URLs and whole sites, rewriting to raise the score, tracking whether the engines do cite a site, and the data and agents that decide what to improve next — all of `apps/aieo/` rebuilt on the platform ([ADR 0006](../../docs/adr/0006-one-python-platform.md), [TARGET.md](../../docs/plan/TARGET.md) § AIEO in the platform, PLAN G7). Every model call is a run of the AI layer's `assistant` agent ([`ai/README.md`](../ai/README.md)), every URL goes through the research library's guarded fetcher ([`research/README.md`](../research/README.md)), and every rewrite of a page arrives as suggestions a person accepts.

## The pieces

| File | What |
|---|---|
| `analyzers.py` | The deterministic checks behind four of the five dimensions — seo, readability, humanity, cro — and the extra signals: search intent, keywords, length against competitors, the CRO checklist, engagement, competitor gaps, and the opportunity rule priorities rank by. Ported from `backend/app/analyzers/` as they were |
| `parser.py` | What the scorer reads in Markdown or HTML: text, headers, tables, lists, links (Python-Markdown and BeautifulSoup, as AIEO) |
| `scoring.py` | The scoring engine: the ten patterns' heuristics, anti-pattern penalties, gaps, the grade, the five dimensions; the evaluator's prompt (AIEO's system prompt, rubric and pattern definitions, byte for byte) and the schema its answer is held to |
| `prompts.py` | AIEO's prompt files (`data/prompts/`, byte copies of `backend/prompts/`) as the pattern library and the bundled assistants, seeded after every migrate and re-imported on request |
| `models.py` | `Pattern`, `Audit`, `CitationQuery` and `CitationCheck`, `Connector` and `ConnectorData`, `BrandContext` (a Wagtail site setting), `LandingPage` (a page type) |
| `services.py` | Every command: score, audit (a text, a page, a URL, a site, a batch), benchmark, rewrite (optimize, expand, scrub, rewrite, apply a pattern), the AIEO agents, citations and share of voice, connectors and priorities, the lifecycle |
| `handlers.py` | What the runs do in the worker: `aieo.audit`, `aieo.rewrite`, `aieo.citation`; and the citability review (the `aieo` agent's handler) |
| `crawl.py` | A site's pages, cheap first — robots.txt, sitemaps, the feed, then links — through `research.fetch`; the link map's hubs and orphans |
| `visual.py` | The visual audit: a screenshot in a headless browser whose every request goes through `research.fetch` (off unless `AIEO_VISUAL_AUDIT`; Playwright optional) |
| `connectors.py` | GA4, Search Console and DataForSEO clients over httpx; Google's service-account JWT signed with PyJWT |
| `reports.py` | AIEO's per-site reports and summary (`generate_reports.py`), from audits, in Markdown and HTML |
| `tools.py` | `aieo.*` in the tool registry, and AIEO's 28 MCP tool names — the 24 with a platform counterpart — as aliases |
| `serializers.py`, `views.py`, `urls.py` | `/api/v2/aieo/` |
| `tasks.py` | A connector's sync; the due citation questions, on Celery beat (`aieo-citations`) |
| `management/commands/aieo.py` | `manage.py aieo audit|batch-audit|crawl|report|run|import-reports|import-prompts` — the CLI and the root scripts |

## Scoring

The `aieo` dimension is the citability score: each pattern of the library scores up to its maximum, the scores are weighted (the bundled ten weigh 125 in all) and normalized to 100, and the anti-pattern penalties (at most 50) come off. The other four dimensions are the analyzers' scores. Two ways to score the patterns, as AIEO had:

- **the heuristics** (`scoring.heuristic`) — deterministic, free, used by `POST score/`, the CI runner, a heuristic audit and the citability review; on Markdown they give exactly the score AIEO gave (`tests/aieo/test_analyzers.py` against `tests/aieo/golden/source.json`, recorded by running AIEO's own code on the fixtures before the port);
- **a model's evaluation** — the bundled *AIEO evaluator* assistant, whose instructions are AIEO's system prompt; each request carries the content's summary, the scoring rubric and the definitions of the library's enabled patterns, and the answer is held to the bundled *AIEO evaluation* schema with one required property per enabled pattern. When the provider fails (unreachable, refused, invalid JSON) the heuristic score stands, and the audit says why (`result.fallback`).

A person tunes scoring in the studio, not in code: a pattern's weight, maximum, criteria or `enabled` (`aieo.change_pattern`), the evaluator's provider, model and instructions (AI → Assistants). `manage.py aieo import-prompts --path DIR` brings the library and the assistants to a prompts directory in AIEO's layout, leaving alone a row a person changed since the last import (`--force` overwrites).

## Audits

An audit is of a pasted text, a page (its latest revision, for someone who may edit it), a URL, or a site, crawled up to `max_pages`. Creating one saves it as `pending` and starts its run (`202`; follow `/api/v2/agent-runs/<id>/stream/`); the run fetches what it needs — robots.txt first, every request through the guard — scores every document with the heuristics, evaluates the first with a model when `method` is `ai`, and stores the score, the grade, the whole result (patterns with evidence, gaps, penalties, the dimensions and their analyses; with a model, the assessment, executive summary, priority actions and sample improvements) and, for a site, every page's score and the link map. Its benchmark is its percentile among the platform's audits of its kind, per engine how often the engines asked about its domain cited it, and the audits nearest it in meaning that its owner sees — what it read (for a site, its first page read) is stored as a vector (`graph.Embedding`, kind `audit`; pgvector on Postgres), in place of AIEO's configured, never-used Qdrant. A site's score is the mean of its pages'. Audits are history: list them by page, URL or batch; share one with a site's editors; download its report (AIEO's Markdown, or HTML) or a batch's summary.

## Rewrites, patterns and agents

`rewrites/` (and a pattern's `apply/`) optimizes (AIEO's optimize prompt with the gaps an audit found), expands (AIEO's expand instructions), scrubs (AIEO's scrub prompt), rewrites, or applies one pattern. On a page the rewrite is aligned with the page's blocks and only what changed is proposed — a block replaced, new blocks inserted after the one they follow, a block deleted — through `content.propose_edit` as the `assistant` agent acting for the person who asked, all of it or none; on a pasted text it is the run's output, a draft to read. Only a person asks for suggestions on a page: an agent rewrites a text.

The ten AIEO agents (SEO optimizer, meta creator, keyword mapper, human editor, headline generator, internal linker, content analyzer, CRO analyst, landing page optimizer, performance analyst) are bundled assistants made from AIEO's agent prompts, each with an output schema for the JSON its prompt asks for, propose-only like every assistant. `agents/run/` runs one on a text or a page with the site's brand context; they also appear in the editor's AI panel, where an answer lands on the page as suggestions.

## Citations, connectors, priorities, context

A **citation query** is a question people ask AI engines and the domain to look for; checking it asks each of its engines — providers of the AI layer — through the bundled citation probe, one run each, and records whether the answer cites the domain (a source on it, ranked, or the domain named), at what position, and when. Celery beat asks due questions again every `interval_days`. `citations/share/` is share of voice per engine and by week.

A **connector** connects a site to GA4 (top pages), Search Console (queries) or DataForSEO (organic results for its keywords); its credential is encrypted with the AI layer's keys and write-only, and a sync runs in a worker and keeps its rows. **Priorities** are AIEO's opportunity rule over the last Search Console rows: position, impressions, the CTR gap, the trend in impressions since the sync before, and a business priority from the site's target keywords; the quick wins score 60 or more. The **brand context** — brand voice, style guide, writing examples, target keywords, internal-links map, competitor analysis, SEO guidelines, CRO best practices, features, and the competitors, keywords and topics AIEO kept in `config/competitors.json` — is a site setting its editors change, which the agents read and the scorer takes keywords and competitor topics from.

## The content lifecycle

AIEO's file workspace maps onto the platform: topics are **Ideas** (with AIEO's topic template), research briefs are **Research**'s bundled writer, drafts are **briefs** written by the bundled *Article writer (AIEO)* and applied as draft pages, rewrites are **suggestions**, review-required is the **Review** inbox, published are published pages, and landing pages are the **`LandingPage`** type, drafted by the *Landing page writer*, researched by the *Landing page researcher*, CRO-audited by the cro dimension, and a competitor's analysed by auditing its URL. `lifecycle/?site=` counts each stage.

## The API (`/api/v2/aieo/`)

`score/`, `audits/` (with `batch/`, `summary/`, and per audit `report/`, `screenshot/`), `patterns/` (and `<name>/apply/`), `rewrites/`, `agents/` (and `run/`), `citations/queries/` (and `<id>/check/`), `citations/checks/`, `citations/share/`, `connectors/` (and `<id>/sync/`, `<id>/data/`), `priorities/`, `context/<site>/`, `lifecycle/`. People only; an agent works through the tools. What reaches the network or a model answers `202` and honours an `Idempotency-Key`; audits that reach the web are throttled like the research library's fetches.

## Tools and MCP

`aieo.score_text`, `aieo.readability`, `aieo.keyword_analysis`, `aieo.search_intent`, `aieo.landing_audit`, `aieo.list_patterns`, `aieo.get_pattern`, `aieo.get_audit`, `aieo.priorities` (read); `aieo.audit_url`, `aieo.audit_site`, `aieo.audit_page`, `aieo.optimize`, `aieo.scrub`, `aieo.apply_pattern`, `aieo.run_agent`, `aieo.research_brief` (propose). AIEO's MCP names are aliases (`aieo/tools.py` `ALIASES`), and `aieo_editor_review` and `aieo_headline_generate` run their agent. The `aieo` agent definition lists them all, so `manage.py agent_token aieo --name …` gives an MCP client AIEO's tools; it is a review agent with no page rights of its own — grant `agent:aieo` page permissions for the page tools. Not carried: `aieo_publish_wordpress` (distribution, PLAN G5) and the three PRD-lineage tools.

The same definition is the **citability review**: as a workflow task (`AgentReviewTask`, agent `aieo`) it passes a page whose heuristic score reaches `AIEO_REVIEW_MIN_SCORE` and fails it otherwise, its worst gaps as the comments — a review step, never the last before publishing.

## Commands

`manage.py aieo audit FILE|URL` (`--json`, `--ai`), `batch-audit --sites FILE --output DIR` (AIEO's per-site JSON, `summary.json` and reports), `crawl URL --output DIR` (an offline snapshot), `report` (from audits, or `--input` AIEO's JSON results), `run` (the headless CI runner: Markdown by `--glob` or `--git-diff-base`, scored with no database, or optimized into `proposed/` with `--write-proposed` — never in place), `import-reports` (AIEO's `reports/` as audit history), `import-prompts`. A run a command starts executes in the command's process.

## Settings

`AIEO_VISUAL_AUDIT`, `AIEO_CONNECTOR_TIMEOUT`, `AIEO_REVIEW_MIN_SCORE` (`content/.env.example`); the beat entry `aieo-citations`; the research fetcher's `RESEARCH_*` limits and the AI layer's provider settings apply.

## Tests

`tests/aieo/`: the analyzers, the parser, the scorer and the evaluator's prompt against AIEO's recorded outputs (`test_analyzers.py`), audits of every kind with the fake provider and recorded HTTP, the visual audit faked, the reports byte for byte against AIEO's (`test_audits.py`), rewrites as suggestions (`test_rewrites.py`), citations (`test_citations.py`), connectors on respx (`test_connectors.py`), the API's permissions (`test_api.py`), the tools, MCP and the review (`test_tools.py`), the commands (`test_commands.py`). Nothing reaches a network or a model.

## Not here

WordPress publishing (a distribution channel, PLAN G5); the PRD-lineage inventory (`aieo.prd-lineage`); a reusable CI workflow that commits optimized Markdown (`aieo.ci-workflows`, an automation, PLAN G16); a site snapshot's ETag cache between crawls and AIEO's PDF, HTML and bundle exports; a crawl bounded by depth rather than pages; image input for the `claude_code` and `litellm` providers (the visual audit's screenshot reaches `anthropic` and `openai`).
