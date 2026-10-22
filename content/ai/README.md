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

An adapter implements `complete` (a model id, a system prompt, the runner's provider-neutral messages and tool specs in; a `Completion` — text, tool calls, tokens, cost — out) and inherits `stream`, `structured` (a JSON Schema in, a validated object out: the adapter asks for native structured output where the vendor has it, and `jsonschema` validates the result here either way), `list_models` and `health`; it declares what it can do in `capabilities` (`complete`, `stream`, `structured`, `tools`, `models`, `embed`). Vendor SDKs are imported inside the adapters' methods and are optional at install time (`requirements-providers.txt`; the image installs them unless built with `AI_PROVIDERS=false`). `tests/ai/test_providers.py` fails if any module outside `ai/providers/` imports `anthropic`, `openai`, `litellm` or `claude_agent_sdk`.

| Slug | Reaches | Credential (row, else environment) |
|---|---|---|
| `claude_code` | Claude through the Claude Agent SDK, one tool-less query per completion | `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`) or `ANTHROPIC_API_KEY` |
| `anthropic` | the Messages API: `output_config.format`, tool use, server-side refusal fallbacks on the models that need them | `ANTHROPIC_API_KEY` or an OAuth token |
| `openai` | chat completions: function calling, `response_format` | `OPENAI_API_KEY` |
| `litellm` | any other vendor, and embeddings for the graph (`EMBEDDING_BACKEND=litellm`) | the vendor's own variables |
| `recorded` | replays `agents/recordings/<agent>/<scenario>/<step>.json` (CI, evals) | none |
| `fake` | a scripted list (unit tests) | none |

Each slug has a `ProviderConfig` row (created after every migrate): enabled, the default (one at most, by a database constraint), base URL, organization, project, default model, `extra` options (`effort`, `max_turns`, `timeout`, `server_side_fallbacks`, LiteLLM's `models`), a monthly budget, the last health check, and the credential — encrypted with `AI_CREDENTIAL_KEYS` (or a key derived from `SECRET_KEY`), write-only over the API, never logged. Without a row flagged default, `AI_DEFAULT_PROVIDER` is the default. `settings.AI_PROVIDERS` (slug → dotted path) adds an adapter or, mapped to `""`, removes one. `agents/llm.py`, the tool-using agents' client, is a thin front over the same registry (`LLM_BACKEND` names a slug).

## Rows and who sees them

Every row has a UUID `public_id`; the integer key never leaves the platform. Assistants, pipelines, output schemas, briefs and conversations carry `owner`, `site` and `visibility`: `private` (the owner), `site` (everyone with page rights in that site) or `shared` (everyone signed in); staff see everything. `visible_to(user, site=None)` is the one place rows are scoped — every view, tool, service and handler uses it — and with a site it returns that site's rows and the rows that belong to no site. Changing a row is its owner's or staff's (`can_edit`); running a visible assistant or pipeline is anyone's who can see it.

## Runs

| `input.kind` | Started by | What the run does |
|---|---|---|
| `assistant` | `run_assistant`, `ai.run_assistant`, each pipeline step | one answer from the assistant's provider: its instructions as the system prompt, the request through its prompt template, its tools |
| `pipeline` | `run_pipeline` | one child run per step, in order, each fed what its step reads: the previous output, the run so far (or the conversation), the brief, or a page field |
| `brief` | `generate_brief` | the structured result (or the pipeline's, or the brief's own text), validated against the schema and rendered to Markdown, then a second call extracting title, slug, description, keywords and tags through the bundled content-detail schema |
| `message` | `post_message`, `rerun`, a pipeline on a conversation | the conversation replayed whole (system messages folded into the instructions; it always opens and ends with a person's turn), the answer written to the placeholder message |
| `sync_models`, `health` | staff, from the provider endpoints | the catalog upserted from `list_models`; a one-word completion stored as the provider's last health |

The handler runs every model call through the runner's own loop (`agents.runner.model_loop`), so each call is a step with tokens and cost, under the definition's step limit and budget (a pipeline's total included); a provider row's monthly budget refuses new runs once spent (`429 budget.exceeded`). An assistant may use only the read-only tools it lists, narrowed again to the `assistant` definition's allowlist, and none on a provider without the runner's tool protocol (`claude_code`). The rows a run names are re-checked against the person who started it. The definition's evals replay recordings (`run_evals --all --recorded`).

## Briefs become drafts, never pages

Applying a ready brief (`apply_brief`) creates the page as a draft under the chosen parent — the person who applies it authors that revision (title and slug) — and everything the model wrote arrives as `Suggestion`s from the `assistant` agent on the brief's run: one `insert` per block of the Markdown, the description and the keywords as `meta`. The editor accepts them like any other agent's (all of a run at once is one revision, with provenance); the brand guard runs on each. Nothing in this app publishes.

## The API (`/api/v2/ai/`)

| Path | |
|---|---|
| `providers/` | list, retrieve; staff: update (the credential write-only), `test/`, `sync-models/`, `set-default/` |
| `models/` | the catalog; filter `provider`, `active` |
| `output-schemas/` | CRUD (the schema validated, a changed schema a new version), `export/`; staff: `import-bundled/` |
| `assistants/`, `pipelines/` | CRUD (pipelines with their steps, replaced as a whole), `run/`; an assistant's `export/` as a portable document and `import/` of one |
| `briefs/` | CRUD, `generate/`, `apply/` (201: the draft's id and the suggestions to accept) |
| `conversations/` | CRUD (`from_brief` on create: the brief's text is the first turn), `messages/` (GET by cursor, filtered by `role` and `status`; POST a message), `run-pipeline/` |
| `messages/<id>/` | retrieve, PATCH the assistant, DELETE, `rerun/`, `promote/` (to a brief or a draft) |

Lists are paginated (`page`, `page_size`), filtered with django-filter, ordered from an allow-list, and take `site`. Anything that reaches a model answers `202` with `{"run": {"id", "status", "links": {"self", "stream"}}}` — follow it on `/api/v2/agent-runs/<id>/stream/` — and accepts an `Idempotency-Key`: the same key and request from the same person within a day replays the first answer (`Idempotent-Replayed: true`), the same key with a different request is a `409`. The OpenAPI document (`schemas/openapi/openapi.json`) describes all of it.

## Bundled data and barodybroject's data

After every migrate the three bundled schemas (parody news article, news article, content detail — a local `$ref` inlined) and the parody news writer assistant are created if they do not exist; one a person has edited is left alone. `manage.py import_parodynews --dump FILE` maps barodybroject's own dump onto this app (`importers/parodynews_ai.py`): providers without their credentials, models, schemas, assistants, groups as pipelines, content details as briefs, threads as conversations — owned as barodybroject owned them, idempotently.

## Settings

`AI_DEFAULT_PROVIDER`, `AI_PROVIDERS`, `AI_CREDENTIAL_KEYS` (rotate with `manage.py rotate_ai_credentials`), and each adapter's environment variables — all in `content/.env.example`. `manage.py sync_ai_models [SLUG …]` syncs the catalog from the command line.

## Tests

`tests/ai/`: the adapters against stand-in SDK modules and the import scan (`test_providers.py`), the tables (`test_models.py`), every service through the runner with the fake provider (`test_services.py`), the API (`test_api.py`), the tools (`test_tools.py`); the import in `tests/importers/test_parodynews.py`. None reaches a model.

## Not here yet

The studio's AI and Create areas and their extension counterparts arrive with P4 and G10. Still to come in this app: pipeline steps that are actions rather than assistants, attaching sources and ideas to a brief (G14), YAML (rather than JSON) documents and pipelines among them, per-person and per-site budgets (H2), and token-by-token streaming to the client (the run's stream is step by step).
