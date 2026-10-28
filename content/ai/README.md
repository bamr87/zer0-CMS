# `ai/` — the AI content layer

Provider adapters behind one registry, the model catalog, output schemas, assistants, pipelines, briefs and conversations — barodybroject's AI model rebuilt to the platform's rules ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 7, [TARGET.md](../../docs/plan/TARGET.md) § The AI content layer, PLAN G8). Every generation is an `AgentRun` of the `assistant` agent, so it is costed, traced, budgeted and followed like any other run, and every result is something a person reviews: an assistant only proposes.

## The pieces

| File | What |
|---|---|
| `providers/` | The registry (`get`, `available`, `default_slug`, `override`) and the six adapters: `claude_code`, `anthropic`, `openai`, `litellm`, `recorded`, `fake`. The only place a vendor SDK is imported. |
| `models.py` | `ProviderConfig`, `ModelEntry`, `OutputSchema`, `Assistant`, `Pipeline` + `PipelineStep`, `Brief`, `Conversation` + `Message`, `IdempotencyKey`; `visible_to(user, site)` |
| `services.py` | Every command: run an assistant or a pipeline, generate and apply a brief, post, re-run and promote a message, sync models, check health, set the default provider, import the bundled set |
| `handlers.py` | What a run does in the worker (`agents/definitions/assistant.yaml` points here) |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/ai/` |
| `tools.py` | `ai.run_assistant` and `ai.generate_brief` in the tool registry |
| `crypto.py` | Credentials encrypted at rest (MultiFernet) |
| `rendering.py` | Django templates: a result → Markdown, an assistant's prompt |
| `data/` | barodybroject's bundled schemas and parody prompt (byte copies of `apps/parodynews/src/parodynews/schema/`) and `bundled.yaml`, which names them and holds their render templates |

## Providers

An adapter implements `complete` (a model id, a system prompt, the runner's provider-neutral messages and tool specs in; a `Completion` — text, tool calls, tokens, cost — out) and inherits `stream`, `structured` (a JSON Schema in, a validated object out: the adapter asks for native structured output where the vendor has it, and `jsonschema` validates the result here either way), `list_models` and `health`; it declares what it can do in `capabilities` (`complete`, `stream`, `structured`, `tools`, `models`, `embed`, and `search` for an adapter that can search the web — `search(query, max_results)`). Vendor SDKs are imported inside the adapters' methods and are optional at install time (`requirements-providers.txt`; the image installs them unless built with `AI_PROVIDERS=false`). `tests/ai/test_providers.py` fails if any module outside `ai/providers/` imports `anthropic`, `openai`, `litellm` or `claude_agent_sdk`.

| Slug | Reaches | Credential (row, else environment) |
|---|---|---|
| `claude_code` | Claude through the Claude Agent SDK, one tool-less query per completion; every credential variable set by the adapter, the CLI and its directory the deployment's | `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) or `ANTHROPIC_API_KEY` |
| `anthropic` | the Messages API: `output_config.format`, tool use, server-side refusal fallbacks on the models that need them (an OAuth token's beta sent beside the fallback one); web search through its server-side `web_search` tool (`search`) | `ANTHROPIC_API_KEY` or an OAuth token |
| `openai` | chat completions: function calling, `response_format` | `OPENAI_API_KEY` |
| `litellm` | any other vendor, and embeddings for the graph (`EMBEDDING_BACKEND=litellm`) | the vendor's own variables |
| `recorded` | replays `agents/recordings/<agent>/<scenario>/<step>.json` (CI, evals) | none |
| `fake` | a scripted list (unit tests) | none |

Each slug has a `ProviderConfig` row (created after every migrate): enabled, the default (one at most, by a database constraint), base URL, organization, project, default model, `extra` options — only the ones its adapter declares in `options` (`max_retries`, `timeout`, `max_tokens`, `effort`, `server_side_fallbacks`, `max_turns`, LiteLLM's `models`), validated on save, so nothing a row holds chooses what the worker runs — a monthly budget, the last health check, and the credential — encrypted at rest, write-only over the API, never logged, and dropped when the base URL changes without a new one. An environment credential is the deployment's and never goes to a base URL a row chose: such a row needs its own. Without a row flagged default, `AI_DEFAULT_PROVIDER` is the default. `settings.AI_PROVIDERS` (slug → dotted path) adds an adapter or, mapped to `""`, removes one. `agents/llm.py`, the tool-using agents' client, is a thin front over the same registry (`LLM_BACKEND` names a slug; a definition's `anthropic/…` or `openai/…` model id reaches that vendor's adapter bare, and `claude_code`, without tool calls, refuses a definition that uses tools).

Credentials are encrypted with the first of `AI_CREDENTIAL_KEYS`, else a key derived from `SECRET_KEY`; every key decrypts, and the keys derived from `SECRET_KEY` and `SECRET_KEY_FALLBACKS` always stay among them, so setting `AI_CREDENTIAL_KEYS` (or rotating `SECRET_KEY` with the old one as a fallback) loses nothing. `manage.py rotate_ai_credentials` moves every credential to the first key — the providers' and, through `crypto.credentials_rotated`, any other app's under these keys (distribution's channels) — in one transaction; one no current key can read is named (`NotConfigured`), never silently lost.

## Rows and who sees them

Every row has a UUID `public_id`; the integer key never leaves the platform. Assistants, pipelines, output schemas, briefs and conversations carry `owner`, `site` and `visibility`: `private` (the owner), `site` (everyone with page rights in that site) or `shared` (everyone signed in); staff see everything. A row belongs only to a site its owner edits (staff: any), so nobody plants a persona in another site's shared space. `visible_to(user, site=None)` is the one place rows are scoped — every view, tool, service and handler uses it, and `usable(row, user)` asks it again — and with a site it returns that site's rows and the rows that belong to no site. Changing a row is its owner's or staff's (`can_edit`); running a visible assistant or pipeline is anyone's who can see it; a brief an agent asked for (`ai.generate_brief`) is applied by the people it is shown to. Configuring providers needs the `ai.change_providerconfig` permission, and only those who have it see a provider's configuration (the others see whether its last check was ok).

## Runs

| `input.kind` | Started by | What the run does |
|---|---|---|
| `assistant` | `run_assistant`, `ai.run_assistant`, each pipeline step | one answer from the assistant's provider: its instructions as the system prompt, the request through its prompt template, its tools |
| `pipeline` | `run_pipeline` | one child run per step, in order, each fed what its step reads: the previous output, the run so far (or the conversation), the brief, or a page field |
| `page` | `suggest_on_page` (the studio editor's AI panel: `run/` with `suggest`) | an assistant or a pipeline on a page — the whole page, one block, or text selected in it — whose answer the run proposes there as suggestions (`propose_answer`): new blocks at the end, or the block replaced. A selection is placed when the run is asked for (`place`): its field (`text` of a heading, `code` of a code block; a choice, an image or a page is never text) and the character it starts at in the text a person sees — a paragraph's counted in its HTML's text nodes, entities read — given by the client or, without one, the one place it appears; text that appears more than once, or not at all, is refused with the reason (422). Only that text is swapped (`swap`): never a tag or an attribute, never another field or occurrence; a selection no longer there when the answer arrives gets the answer as a new block beside it. Only a person asks (an agent principal is refused: it proposes with `content.propose_edit` itself); they must edit the page, and the registry's own checks for that tool — the `assistant` agent's policy narrowed by the page's, its group's page permissions — are asked when the run is requested and again in the worker; all of the suggestions are proposed or none |
| `brief` | `generate_brief` | the structured result (or the pipeline's, or the brief's own text), validated against the schema and rendered to Markdown, then a second call extracting title, slug, description, keywords and tags through the bundled content-detail schema |
| `message` | `post_message`, `rerun`, a pipeline on a conversation | the conversation replayed whole (system messages folded into the instructions; it always opens and ends with a person's turn), the answer written to the placeholder message |
| `sync_models`, `health` | staff, from the provider endpoints | the catalog upserted from `list_models`; a one-word completion stored as the provider's last health |

The handler runs every model call through the runner's own loop (`agents.runner.model_loop`), so each call is a step with tokens and cost, under the definition's step limit and budget (a pipeline's total included); a provider row's monthly budget — this month's model calls through it, each counted once on the run that made it — refuses new runs once spent (`429 budget.exceeded`). An assistant may use only the read-only tools it lists, narrowed again to the read tools of the `assistant` definition's allowlist (whose one propose tool, `content.propose_edit`, is the handler's), and none on a provider without the runner's tool protocol (`claude_code`); its tools act for the person who started the run, so they read only pages that person may edit. A run can be started from more than one surface (the generic `/api/v2/agent-runs/` too), so the worker asks again when it executes: the row the run is about must be its starter's to use, every row it uses — the assistant, the pipeline and each step's assistant, the output schema — must still be visible to them, and the provider must be enabled and inside its budget. A brief left generating or a reply left queued by a run that ended without succeeding — even one refused before the handler ran — takes the run's error (`settle`, on `agents.runner.run_finished`), and can be asked for again. A pipeline run on a conversation posts its prompt there first, for every step to read. The definition's evals replay recordings (`run_evals --all --recorded`).

## Briefs become drafts, never pages; answers on a page become suggestions

Applying a ready brief (`apply_brief`) creates the page as a draft under the chosen parent — the person who applies it authors that revision (title and slug) — and everything the model wrote arrives as `Suggestion`s from the `assistant` agent on the brief's run: one `insert` per block of the Markdown, the description and the keywords as `meta`. The editor accepts them like any other agent's (all of a run at once is one revision, with provenance); the brand guard runs on each. An assistant or a pipeline run on an existing page from the editor (`page` runs, above) lands its answer the same way, as suggestions on that run. Either way each suggestion is a call of the registry's `content.propose_edit` (`_propose`), as the `assistant` agent acting for the person who asked (`ToolContext.on_behalf_of`) — a step of the run, under that agent's tools, policy and page permissions (narrow the `agent:assistant` group's page permissions to confine it, as for any agent), the page's policy, the person's edit right and the tool's rate — so this layer has no proposing path of its own. The model never gets that tool: it is offered only the read tools an assistant lists. Only a person applies a brief or asks for suggestions on a page. A replacement that reads the same but stores something different (a link's target, the markup) is shown in the review by its stored values, labelled "markup only" (`suggestions.services.describe`). Nothing in this app publishes.

## The API (`/api/v2/ai/`)

| Path | |
|---|---|
| `providers/` | list, retrieve; with `ai.change_providerconfig`: update (the credential write-only), `test/`, `sync-models/`, `set-default/` |
| `models/` | the catalog; filter `provider`, `active` |
| `output-schemas/` | CRUD (the schema validated — referring only to itself — and a changed schema a new version), `export/`; importing a schema is posting the document `export/` returned; staff: `import-bundled/` |
| `assistants/`, `pipelines/` | CRUD (pipelines with their steps, replaced as a whole), `run/` (on a prompt; with `suggest`, `page_id` and optionally `block_id` and a `selection` — with its `field` and `selection_start` — on a page, its answer proposed there as suggestions); an assistant's `export/` as a portable document and `import/` of one; `assistants/tools/`, the read-only tools an assistant may list that its runs use |
| `briefs/` | CRUD, `generate/`, `apply/` (201: the draft's id and the suggestions to accept; a person's — the owner, staff, or for a brief an agent asked for anyone who sees it) |
| `conversations/` | CRUD (`from_brief` on create: the brief's text is the first turn), `messages/` (GET by cursor, oldest first or newest first with `ordering=-seq`, filtered by `role` and `status`; POST a message), `run-pipeline/` |
| `messages/<id>/` | retrieve, PATCH the assistant, DELETE, `rerun/`, `promote/` (to a brief or a draft) |

Lists are paginated (`page`, `page_size`), filtered with django-filter, ordered from an allow-list, and take `site`; every owned row says whether the requester may change it (`can_edit`). Anything that reaches a model answers `202` with `{"run": {"id", "status", "links": {"self", "stream"}}}` — follow it on `/api/v2/agent-runs/<id>/stream/` — and accepts an `Idempotency-Key`: the same key and request from the same person within a day replays the first answer (`Idempotent-Replayed: true`), the same key with a different request is a `409`. The studio sends one, made when the person acts, with every such request. The OpenAPI document (`schemas/openapi/openapi.json`) describes all of it.

## Bundled data and barodybroject's data

After every migrate the three bundled schemas (parody news article, news article, content detail — a local `$ref` inlined) and the parody news writer assistant are created if they do not exist, with the models as migrated (and not at all while the AI tables are unapplied, `migrate ai zero`); one a person has edited is left alone. Other apps bundle their own rows the same way, keyed by `stable_id` — the newsroom's assistants, schemas and pipeline are in `newsroom/data/bundled.yaml`. `manage.py import_parodynews --dump FILE [--force]` maps barodybroject's own dump onto this app (`importers/parodynews_ai.py`): providers without their credentials, models, schemas, assistants, groups as pipelines, content details as briefs, threads as conversations — owned as barodybroject owned them. barodybroject keeps running until its gate is green, so the import is re-run: it changes nothing that did not change in the dump, and a row a person changed or deleted here since is reported as a conflict and left alone (`--force` overwrites it; an applied brief keeps its draft even then); a message new in the dump goes after the conversation's last one.

## Settings

`AI_DEFAULT_PROVIDER`, `AI_PROVIDERS`, `AI_CREDENTIAL_KEYS` (rotate with `manage.py rotate_ai_credentials`), and each adapter's environment variables — all in `content/.env.example`. `manage.py sync_ai_models [SLUG …]` syncs the catalog from the command line. Who configures providers is a Django permission (`ai.change_providerconfig`), granted like any other.

## Tests

`tests/ai/`: the adapters against stand-in SDK modules and the import scan (`test_providers.py`), the tables (`test_models.py`), every service through the runner with the fake provider (`test_services.py`), the API (`test_api.py`), runs on a page and what the studio reads (`test_on_page.py`), the tools (`test_tools.py`); the import in `tests/importers/test_parodynews.py`. None reaches a model. The studio's screens over this API are `web/packages/ui/src/ai/`, tested in `web/packages/ui/test/ai/`.

## Not here yet

The studio's AI and Create areas are built (`web/packages/ui/src/ai/`, PLAN G8); their extension counterparts arrive with G10. Still to come in this app: pipeline steps that are actions rather than assistants, YAML (rather than JSON) documents and pipelines among them, per-person and per-site budgets (H2), and token-by-token streaming to the client (the run's stream is step by step).

## The apps built on it

Ideas and research (G14, [`ideas/README.md`](../ideas/README.md), [`research/README.md`](../research/README.md)) use this layer rather than a client of their own, through four seams: `handlers.register(kind)` adds a run kind of the `assistant` agent (research's `research.summarize`, `research.answer`, `research.fact_check`, `research.search`), which generates through `generate` and re-checks its rows with `owned` and `used`; `handlers.brief_context` is a signal whose receivers add what a brief's writer reads after its prompt — research hands it the sources the brief cites, so attaching a source (or an idea's sources, on promotion) to a brief is a `research.Citation`; `import_bundled(state, path)` seeds an app's own bundle of schemas and assistants; and the provider capability `search` (`Provider.search`, a `Completion` whose `data` is a list of `SearchResult`), which the `anthropic` adapter declares through Anthropic's server-side web search tool. A brainstorm is a `Conversation` with the bundled Brainstormer, and its reply's structured result is what a person keeps as ideas.
