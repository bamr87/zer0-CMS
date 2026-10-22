# `agents/` — the harness

Definitions, runs and the one tool registry every surface dispatches through (note §4; ADR 0001).

## The pieces

| File | What |
|---|---|
| `models.py` | `AgentDefinition` (a snippet with revisions and a draft/live state), `AgentRun`, `AgentStep`, `Memory`, `EvalCase`, `EvalResult`, `AgentToken` |
| `principals.py` | `agent:<slug>` users, the `Agents` group and each agent's own group with its Wagtail page and collection permissions |
| `registry.py` | `@tool`, `Registry.call()` and the six checks it runs on every call |
| `llm.py` | the model client the runner uses (`get_llm`, `use_llm`): a thin front over the provider registry in `ai/providers/`, which `LLM_BACKEND` names a slug of (`recorded`, `fake`, `litellm`, `anthropic`, `openai`, `claude_code`); `RecordingLLM` |
| `runner.py` | `start_run` / `execute`: the state machine over runs and steps; `model_loop`, which a handler may call with its own client, persona and history (the AI content layer's assistants do) |
| `schema.py` | the JSON Schema export of every page type and block; `validate_block` |
| `evals.py` | scoring, the publish gate and the promotion rule |
| `sync.py` | `definitions/*.yaml` → definitions and eval cases |
| `handlers/` | deterministic agents: `reviews.brand`, `reviews.a11y`, `abc.draft` |
| `tools.py` | `memory.recall`, `memory.remember`, `brand.rules` |
| `definitions/` | the agents, as reviewable YAML — including `assistant`, which runs the AI content layer's user-managed assistants (`ai/handlers.py`) |
| `recordings/` | recorded model responses for the eval scenarios |
| `data/abc_lexicons/` | the ABC lexicons (a vendored copy of `rails/lib/zer0_cms/abc/lexicons/`) |

## Effects and policies

Every tool declares an effect. The registry compares it with the narrower of the agent's policy and the target page's:

| Effect | Needs | Examples |
|---|---|---|
| `read` | any policy but `off` | `content.get_page`, `content.search`, `graph.related` |
| `propose` | `suggest` | `content.propose_edit`, `graph.upsert_edge`, `review.submit_verdict` |
| `write` | `draft`, and a live definition | `content.draft_revision` |
| `publish` | `auto`, never a review agent | `content.publish` |

Every agent starts at `suggest`. Promotion to `draft` or `auto` is a new definition revision, and publishing that revision needs the agent's suggestions to have been accepted at `AGENT_PROMOTION_ACCEPT_RATE` (0.8) over `AGENT_PROMOTION_MIN_DECISIONS` (10) decisions, on top of a passing eval suite.

## Definitions are code

`definitions/<slug>.yaml` holds a definition and its eval cases. `manage.py sync_agents` creates the definition (not live) or saves a new draft revision when the file changed — the live configuration does not move until a new revision passes its evals. `sync_agents --publish` (or `run_evals --agent <slug> --publish`) runs the suite against the latest revision and publishes it if the gate passes. In the admin, publishing a definition goes through the same gate.

A definition may carry `profile.profiles.<name>`: an alternative handler or system prompt a run selects with `input.profile`, or by its target's own `profile` field — the drafter's `abc` (a deterministic handler, falling back to the model for themes without a lexicon) and `story`.

## Recordings

Tests and CI never call a model. `LLM_BACKEND=recorded` replays `recordings/<agent>/<scenario>/<step>.json`, where the scenario is the run's `input.scenario` (an eval case's name by default) and the step counts model calls within the run. Each file stores the `prompt_digest` of the system prompt and tool list it was recorded with; replaying it against a changed prompt fails with `RecordingStale`, because a changed prompt deserves a new recording. Tool-call arguments use placeholders instead of ids — `{{target.id}}`, `{{results.N.path}}` (the Nth tool result in the run so far) and `{{input.key}}` — so one recording holds on any database.

To record: `LLM_BACKEND=litellm ZER0_LLM_RECORD=1 python manage.py run_evals --agent <slug>` (any provider slug works; with `pip install -r requirements-providers.txt` and the provider's key), then replace the ids in the written files with placeholders and commit them. A call with an output schema digests the schema too, so a changed schema needs a new recording.
