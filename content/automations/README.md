# `automations/` — when something happens, do something

A trigger, a condition and ordered actions, with every run logged ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 15, [TARGET.md](../../docs/plan/TARGET.md) § Pipelines and workflows, PLAN G16). An automation acts as its owner — through the same services and permission checks that person's own requests go through — and only ever proposes: it never publishes. A new automation is paused until its owner enables it. People build them in the studio's AI → Automations (`web/packages/ui/src/automations/`).

## The pieces

| File | What |
|---|---|
| `models.py` | `Automation` (an owned row: name, site, owner, `enabled` — false when made —, trigger, condition, actions, `on_error`, `max_runs_per_hour`, its secret encrypted, its last run) and `AutomationRun` (the trigger's payload, the condition's verdict, each action's outcome, timings, the error) |
| `spec.py` | What an automation may say: one JSON Schema per trigger kind and per action kind — the stored JSON's validation and the OpenAPI document's description of it — the cron line, the condition, the templates, and the rows its owner may use |
| `services.py` | Firing (each trigger), running (each action, as the owner), enabling and pausing, test and dry runs, the secret, YAML export and import |
| `consumers.py` | The outbox consumer `automations`, which hands the platform's own events to `services.on_event` |
| `tasks.py` | Celery: a queued run executed in the worker; the schedules that came due, fired every minute by beat |
| `tools.py` | `automations.fire_hook` in the tool registry |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/automations/` |

## Triggers

| Kind | Fires when | Its payload |
|---|---|---|
| `event` | the platform announces one of its events — `content.page.published`, `content.suggestion.created`, `agent.run.completed` — read from the stream the relay writes (`zer0:content`) by the outbox consumer `automations` (`manage.py consume_events --stream zer0:content --group automations`, the compose `events` service), once per event | the CloudEvents envelope: `type`, `subject`, `data` … |
| `schedule` | a cron line comes due, in UTC (`0 9 * * 1-5`) | `scheduled_at`, `cron` |
| `webhook` | a request to `/api/v2/automations/<id>/webhook/` signed with the automation's secret: `X-Zer0-Signature-256: sha256=<hex HMAC-SHA256 of the body>` (GitHub's `X-Hub-Signature-256` reads the same way); no session or token — the signature is the credential, checked before anything else; a delivery sent again (`X-Zer0-Delivery`, `X-GitHub-Delivery`) gets the run it made | `body` (the JSON), `headers` (the request's `X-…` headers but the signature) |
| `source` | a research source becomes ready — a feed item, a note, a document, a captured page once fetched — in the collection, or from the feed, the trigger names, if any; once per source | `source`: its id, kind, title, URL, author, summary, the first 5,000 characters of its text, its collection, feed and site |
| `hook` | something calls `services.fire_hook(name, data, site=, by=)` — G12's monitor findings will fire `monitor.finding` — or an agent calls the `automations.fire_hook` tool | `hook`, `by` (who fired it: an app, or `agent:<slug>`), `site`, `data` |

An automation hears only what its owner may see (a suggestion, an agent run, a source), and only its own site's when it has one. Its own work never fires another: an agent run an action started carries `automation-run:<id>` in `started_by_event`, and neither its completion, nor a suggestion it made, nor a hook it fires sets automations off.

**Why one dispatcher, not django-celery-beat.** Schedules are one beat entry (`automations-schedule`, every minute) whose task reads every enabled automation's cron line with Celery's own `crontab` — the parser beat itself uses — and claims each due tick before firing it, so two beats never fire it twice. django-celery-beat's database scheduler would have meant a second scheduler to deploy (the beat service's `--scheduler`), its tables and admin, and a `PeriodicTask` row kept in step with every automation as it is made, changed, paused and deleted; the dispatcher is a few lines over rows that already exist. Missed ticks fire once, as beat's own do.

## Conditions

A JMESPath expression (the maintained `jmespath` library) over the payload: empty always runs; JMESPath's own idea of truth decides — `null`, `false` and an empty string, list or object are false, everything else (`0` included) is true. One that does not compile is refused when it is saved (422); one that cannot be evaluated against a payload fails the run with the reason. `POST condition/` tries one against a sample payload; `GET options/` has a sample payload for each trigger kind (an event's is its type's example in `schemas/events/examples/`).

## Actions

Each runs as the automation's owner, through the services and checks that person's own request goes through, in a savepoint of its own; its inputs (its templates rendered) and its outcome — with the agent run, brief, idea or story it made — go on the run. Strings marked templates are Django templates over the payload (`{{ data.page_id }}`, `ai.rendering`: no loaders, no libraries); a webhook's URL and an email's recipients never are, so a payload never chooses where anything goes.

| Kind | Does | Through |
|---|---|---|
| `assistant` | runs an assistant on a prompt (optionally about a page): its answer is the run's output | `ai.services.run_assistant` |
| `pipeline` | runs a pipeline | `ai.services.run_pipeline` |
| `agent` | starts a run of a live agent — one that works from a prompt on a page (no handler of its own, not a review agent) and lists no tool that publishes | `agents.runner.start_run`, after `api.access.may_request_run` |
| `brief` | creates a brief for a person to apply — written now when `generate` is set | `ai.models.Brief`, `ai.services.generate_brief` |
| `idea` | captures an idea, onto a board or into the inbox | `ideas.services.capture` |
| `email` | notifies people by email | Django's mail API (`EMAIL_BACKEND`, django-anymail) |
| `webhook` | notifies a URL: the run and its payload as JSON, signed like an incoming webhook (`X-Zer0-Signature-256`, `X-Zer0-Delivery`) | the research fetcher's SSRF guard (`research.fetch.pinned`): public addresses only, the connection pinned to the address checked, no proxy, no redirect, its time limit; in the worker |
| `story` | moves a newsroom story to a stage that publishes nothing — assigned, drafting, editing, copy | `newsroom.services.move` |

What each one may use is asked when the automation is saved (the rows it names must be its owner's to use) and again when it runs. A failing action is recorded, and the run stops there or goes on (`on_error`). A firing over `max_runs_per_hour` is recorded as `limited` and runs nothing. A run fired while the automation was enabled but executed after it was paused is `skipped`.

## Its secret

Every automation is made with a secret: it signs the webhooks the automation receives and the ones it calls. It is in the answer that made the automation (or re-keyed it, `rotate-secret/`) and never again; at rest it is encrypted under the keys provider credentials use (`ai/crypto.py`), so `manage.py rotate_automation_secrets` runs beside `rotate_ai_credentials` when those keys change — put the new key first, run both, then drop the old one. A secret no current key reads is named by the command, and a webhook signed for it is refused (401) until its owner gives it a new one.

## Who sees and changes an automation

An automation is an owned row with the AI layer's rules (`owner`, `site`, `visibility`, `visible_to`), so whoever its visibility admits sees it and its runs. Because it acts as its owner, only its owner — or a superuser — changes, enables, tests, re-keys or deletes it (403 for anyone else); staff may pause anyone's. The API is for people (`IsPerson`); an agent fires a named hook through the tool registry instead.

## The API (`/api/v2/automations/`)

| Path | |
|---|---|
| `/` | list (filters `enabled`, `visibility`, `kind`; `site`), create — paused; the answer carries its secret, the only time it is shown |
| `<id>/` | retrieve (with its last run), PATCH, DELETE |
| `<id>/enable/`, `<id>/disable/` | start it (checked again first; a schedule counts from now), pause it |
| `<id>/test/` | fire it now with a sample payload, paused or not: a real run (`202`, `Idempotency-Key` honoured) |
| `<id>/dry-run/` | what it would do with a sample payload — the condition's verdict, each action rendered — doing nothing |
| `<id>/export/`, `import/` | the automation as a YAML document (name, description, trigger, condition, actions, `on_error`, `max_runs_per_hour` — never its owner, its secret or whether it runs); a document imported is a new automation of the person's, private, paused and with a secret of its own; the round trip changes nothing |
| `<id>/rotate-secret/` | a new secret, shown once; requests signed with the old one are refused from then on |
| `<id>/webhook/` | a webhook trigger's endpoint (above) |
| `condition/`, `options/` | a condition tried against a sample payload; the events, stages and agents to pick from and a sample payload per trigger |
| `runs/`, `runs/<id>/` | the runs of the automations a person sees, newest first by cursor (filters `automation`, `status`, `trigger`); one with its payload and each action's outcome |

## Tests

`tests/automations/`: each trigger (`test_triggers.py`: an event through the relay and the stream, once; a schedule's ticks; webhooks signed, unsigned and badly signed; new feed items and a captured page; named hooks), conditions (`test_conditions.py`), each action as its owner, nothing published, failures, limits (`test_actions.py`), the API — paused by default, its secret shown once and following the keys when they rotate, visibility, YAML round trip, test and dry runs, runs by cursor (`test_api.py`) — and the tool, in the registry and over MCP (`test_tool.py`). No test reaches a network or a model: the provider is the scripted fake and HTTP is recorded (respx), at an address a table resolves. The studio's view is tested in `web/packages/ui/test/automations.test.tsx`.

## Not here yet

The extension's view of automations (G10, like every workspace). Monitor findings fire `monitor.finding` once G12 exists; the hook is ready for it. Per-automation time zones (a cron line is UTC). An action that runs on a page as suggestions (the editor's AI panel does that today); a pipeline step that is an action (G8's open item).
