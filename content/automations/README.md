# `automations/` — when something happens, do something

A trigger, a condition and ordered actions, with every run logged ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 15, [TARGET.md](../../docs/plan/TARGET.md) § Pipelines and workflows, PLAN G16). An automation acts as its owner — through the same services and permission checks that person's own requests go through — and only ever proposes: it never publishes. A new automation is paused until its owner enables it. People build them in the studio's AI → Automations (`web/packages/ui/src/automations/`).

## The pieces

| File | What |
|---|---|
| `models.py` | `Automation` (an owned row: name, site, owner, `enabled` — false when made —, trigger, condition, actions, `on_error`, `max_runs_per_hour`, its secret encrypted, its last run) and `AutomationRun` (the trigger's payload, the condition's verdict, each action's outcome, timings, the error) |
| `spec.py` | What an automation may say: one JSON Schema per trigger kind and per action kind — the stored JSON's validation and the OpenAPI document's description of it — the cron line, the condition, the templates, the rows its owner may use, the addresses it may email and the URLs it may call |
| `services.py` | Firing (each trigger), running (each action, as the owner), enabling and pausing, test and dry runs, the secret, YAML export and import |
| `consumers.py` | The outbox consumer `automations`, which hands the platform's own events to `services.on_event` |
| `tasks.py` | Celery: a queued run executed in the worker; the schedules that came due, fired every minute by beat |
| `tools.py` | `automations.fire_hook` in the tool registry |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/automations/` |

## Triggers

| Kind | Fires when | Its payload |
|---|---|---|
| `event` | the platform announces one of its events — `content.page.published`, `content.suggestion.created`, `agent.run.completed` — read from the stream the relay writes (`EVENTS_STREAM`, `zer0:content`) by the outbox consumer `automations` (`manage.py consume_events --own --group automations`, the compose `events` service, restarted if it stops), once per event | the CloudEvents envelope: `type`, `subject`, `data` … |
| `schedule` | a cron line comes due, in UTC (`0 9 * * 1-5`) | `scheduled_at`, `cron` |
| `webhook` | a request to `/api/v2/automations/<id>/webhook/` signed with the automation's secret: `X-Zer0-Signature-256: sha256=<hex HMAC-SHA256 of the body>` (GitHub's `X-Hub-Signature-256` reads the same way); no session or token — the signature is the credential, checked before anything else; a delivery sent again (`X-Zer0-Delivery`, `X-GitHub-Delivery`) gets the run it made | `body` (the JSON), `headers`: only `content-type`, `user-agent` and the senders' event and delivery headers (`x-github-event`, `x-github-delivery`, `x-github-hook-id`, `x-gitlab-event`, `x-zer0-event`, `x-zer0-delivery`) — never a credential, a cookie, the signature or a proxy's client address |
| `source` | a research source becomes ready — a feed item, a note, a document, a captured page once fetched — in the collection, or from the feed, the trigger names, if any; once per source | `source`: its id, kind, title, URL, author, summary, the first 5,000 characters of its text, its collection, feed and site |
| `hook` | something calls `services.fire_hook(name, data, site=, by=)` — G12's monitor findings will fire `monitor.finding` — or an agent calls the `automations.fire_hook` tool, which fires `agent.<slug>.<name>` | `hook`, `by` (who fired it: an app, or `agent:<slug>`), `site`, `data` |

An automation hears only what its owner may see: a suggestion or an agent run they may read, a source they see, a page that went live — everyone's, unless a view restriction keeps it from some, when only its editors hear it —, a hook fired for a site only if they work on that site (or are staff); a hook fired for no site is anyone's who waits for it. An automation with a site hears only that site's events, sources and hooks — an event's site is its page's, or, for an agent run, the site of the page the run worked on. Its own work never fires another: an agent run an action started carries `automation-run:<id>` in `started_by_event`, and neither its completion, nor a suggestion it made, nor a hook it fires sets automations off; a webhook action never calls an automation's endpoint, and what one sends is signed another way (below), so it is never a request an automation accepts. An agent fires only its own hooks — the name it gives becomes `agent.<slug>.<name>` — so it never poses as the platform's monitor or another agent, and an automation hears an agent only by naming it.

**Why one dispatcher, not django-celery-beat.** Schedules are one beat entry (`automations-schedule`, every minute) whose task reads every enabled automation's cron line with Celery's own `crontab` — the parser beat itself uses — and claims each due tick before firing it, so two beats never fire it twice. django-celery-beat's database scheduler would have meant a second scheduler to deploy (the beat service's `--scheduler`), its tables and admin, and a `PeriodicTask` row kept in step with every automation as it is made, changed, paused and deleted; the dispatcher is a few lines over rows that already exist. Missed ticks fire once, as beat's own do.

## Conditions

A JMESPath expression (the maintained `jmespath` library) over the payload: empty always runs; JMESPath's own idea of truth decides — `null`, `false` and an empty string, list or object are false, everything else (`0` included) is true. One that does not compile is refused when it is saved (422); one that cannot be evaluated against a payload fails the run with the reason. `POST condition/` tries one against a sample payload; `GET options/` has a sample payload for each trigger kind (an event's is its type's example in `schemas/events/examples/`).

## Actions

A run executes in the worker that serves the `research` queue (`CELERY_TASK_ROUTES`), with the other work that waits on someone else's server, so a slow webhook or mail provider never holds the worker that runs agents and publishes pages. Each action runs as the automation's owner, through the services and checks that person's own request goes through, in a savepoint of its own; its inputs (its templates rendered) and its outcome — with the agent run, brief, idea or story it made — go on the run. Strings marked templates are Django templates over the payload (`{{ data.page_id }}`, `ai.rendering`: no loaders, no libraries); a webhook's URL and an email's recipients never are, so a payload never chooses where anything goes.

| Kind | Does | Through |
|---|---|---|
| `assistant` | runs an assistant on a prompt (optionally about a page): its answer is the run's output | `ai.services.run_assistant` |
| `pipeline` | runs a pipeline | `ai.services.run_pipeline` |
| `agent` | starts a run of a live agent — one that works from a prompt on a page (no handler of its own, not a review agent) and lists no tool that publishes | `agents.runner.start_run`, after `api.access.may_request_run` |
| `brief` | creates a brief for its owner to apply — private, whoever the automation is shared with, since it is written from what the automation heard as them — written now when `generate` is set | `ai.models.Brief`, `ai.services.generate_brief` |
| `idea` | captures an idea, onto a board or into the inbox | `ideas.services.capture` |
| `email` | notifies people by email: the platform's people, by the address on their active account — any address only for an owner with the permission `automations.email_anyone` —, asked again when it runs, and at most `AUTOMATIONS_EMAILS_PER_HOUR` recipients an hour across all of one person's automations (the shared cache) | Django's mail API (`EMAIL_BACKEND`, django-anymail): an `AnymailMessage` tagged `automation`, with the automation and the run in its metadata |
| `webhook` | notifies a URL: the run and its payload as JSON, with `X-Zer0-Delivery` and `X-Zer0-Signature: t=<unix time>,v1=<hex HMAC-SHA256 of "<t>.<body>" with the secret>` — so a receiver checks it and refuses an old one; never an automation's own webhook endpoint (refused when it is saved and when it runs) | the research fetcher, `research.fetch.post`: its SSRF guard (public addresses only, the connection pinned to the address checked), no proxy, no redirect, and one deadline over the whole exchange (`RESEARCH_FETCH_TIMEOUT`) |
| `story` | moves a newsroom story to a stage that publishes nothing — assigned, drafting, editing, copy | `newsroom.services.move` |

What each one may use is asked when the automation is saved (the rows it names must be its owner's to use) and again when it runs. A failing action is recorded, and the run stops there or goes on (`on_error`). An action that has not started 90 seconds into its run (`services.RUN_SECONDS`) does not run, and the run says it ran out of time; each action is bounded, so a run ends inside its task's time limit (two minutes, `tasks.py`) rather than being cut off in the middle — and one the limit does stop is recorded as failed, never left running. A firing over `max_runs_per_hour` is recorded as `limited` and runs nothing. A run fired while the automation was enabled but executed after it was paused is `skipped`.

## Its secret

Every automation is made with a secret: it signs the webhooks the automation receives (the body, GitHub's way) and the ones it calls (the time and the body). It is in the answer that made the automation (or re-keyed it, `rotate-secret/`) and never again; at rest it is encrypted under the keys provider credentials use (`ai/crypto.py`), and `manage.py rotate_ai_credentials` re-encrypts it with them, in the same transaction (this app adds itself to `ai.crypto.REENCRYPT`) — put the new key first, run it, then drop the old one. A secret no current key reads stops the rotation, named, with nothing changed, and a webhook signed for it is refused (401) until its owner gives it a new one.

## Who sees and changes an automation

An automation is an owned row with the AI layer's rules (`owner`, `site`, `visibility`, `visible_to`), so whoever its visibility admits sees what it does. Sharing it never shares what it heard: a run's payload and outcomes are what the automation heard and did with its owner's permissions — a private note, a webhook's body —, so its runs, and its last run, are its owner's and staff's (`AutomationRun.objects.visible_to`, `Automation.shows_runs_to`). Because it acts as its owner, only its owner — or a superuser — changes, enables, tests, re-keys or deletes it (403 for anyone else); staff may pause anyone's. The API is for people (`IsPerson`); an agent fires a named hook through the tool registry instead, and since what that sets off runs as other people and may email, call webhooks and move stories, the tool's effect is `write`: only an agent at policy `draft` or above, live and past its evals, that lists it may call it.

## The API (`/api/v2/automations/`)

| Path | |
|---|---|
| `/` | list (filters `enabled`, `visibility`, `kind`; `site`), create — paused; the answer carries its secret, the only time it is shown |
| `<id>/` | retrieve (with its last run, for whoever sees its runs), PATCH, DELETE |
| `<id>/enable/`, `<id>/disable/` | start it (checked again first; a schedule counts from now), pause it |
| `<id>/test/` | fire it now with a sample payload, paused or not: a real run (`202`, `Idempotency-Key` honoured) |
| `<id>/dry-run/` | what it would do with a sample payload — the condition's verdict, each action rendered — doing nothing |
| `<id>/export/`, `import/` | the automation as a YAML document (name, description, trigger, condition, actions, `on_error`, `max_runs_per_hour` — never its owner, its secret or whether it runs); a document imported is a new automation of the person's, private, paused and with a secret of its own; the round trip changes nothing. An imported document is plain YAML: no aliases (`*name`, which could make a kilobyte stand for billions of values) and at most 20 collections deep |
| `<id>/rotate-secret/` | a new secret, shown once; requests signed with the old one are refused from then on |
| `<id>/webhook/` | a webhook trigger's endpoint (above) |
| `condition/`, `options/` | a condition tried against a sample payload; the events, stages and agents to pick from and a sample payload per trigger |
| `runs/`, `runs/<id>/` | the runs of the person's own automations (every one, for staff), newest first by cursor (filters `automation`, `status`, `trigger`); one with its payload and each action's outcome |

## Tests

`tests/automations/`: each trigger (`test_triggers.py`: an event through the relay and the stream, once, and a quiet stream read through a socket that times out; each event type's site, an agent run's and a suggestion's included; a page behind a view restriction; a schedule's ticks; webhooks signed, unsigned and badly signed, their credentials not kept; new feed items and a captured page; named hooks, and a hook fired for a site reaching only its people), conditions (`test_conditions.py`), each action as its owner, nothing published, email to the platform's people within the hourly budget, a webhook signed so it never fires an automation and cut off at the fetcher's deadline, a late action not started, failures, limits (`test_actions.py`), the API — paused by default, its secret shown once and moving with the one rotation, visibility (a shared automation's runs, last run and brief stay its owner's), YAML round trip and a document that would expand or nest without end, test and dry runs, runs by cursor (`test_api.py`) — and the tool, a `write` firing only its agent's own hooks, in the registry and over MCP (`test_tool.py`). No test reaches a network or a model: the provider is the scripted fake and HTTP is recorded (respx), at an address a table resolves. The studio's view is tested in `web/packages/ui/test/automations.test.tsx`.

## Not here yet

The extension's view of automations (G10, like every workspace). Monitor findings fire `monitor.finding` once G12 exists; the hook is ready for it. Per-automation time zones (a cron line is UTC). An action that runs on a page as suggestions (the editor's AI panel does that today); a pipeline step that is an action (G8's open item). A webhook trigger has no replay window: GitHub signs the body alone, with no time, so a captured delivery stays valid — a delivery id sent again gets the run it made, and the hourly limit bounds the rest.
