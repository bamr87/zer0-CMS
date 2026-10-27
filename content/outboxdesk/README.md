# `outboxdesk/` — the outbox desk

> The outbox harness (bamr87/outbox) operated from the platform: its belt of handoffs read, sent on and delivered, its arena trials and claim desk run in the worker, and a `published` handoff for every page that goes live — from the studio's Outbox workspace.

The [outbox harness](https://github.com/bamr87/outbox) is a stdlib-only library for asynchronous messaging between agents through immutable outbox records: a sender writes a file into its own outbox, and a single relay copies it into the recipients' inboxes and a ledger, in one total order. Its **belt** carries a piece of work between pipeline stations (scout → planner → drafter → verifier → editor → publisher → learner); its **arena** races a scout and two claimants on a task card and scores the winner; its **claim desk** races two verifiers on each of a draft's factual claims and, once the truth is known, scores them (Brier). This app runs all of it on the platform, and the studio's Outbox workspace is its screen ([ADR 0007](../../docs/adr/0007-outbox-desk.md)). It is named so as not to be [`outbox/`](../outbox/README.md), the platform's own transactional outbox — whose event stream it reads.

## The pieces

| File | What |
|---|---|
| `harness.py` | Loads the library under the name `outbox_harness`: its import package is `outbox`, which this platform's own app already is, so it is found through its distribution's files (`importlib.metadata`). A harness that cannot load is a 503 `outbox.unavailable`, never a platform that will not start |
| `models.py` | `SentHandoff` (who sent what as the editor station, and the desk's permissions), `Trial` and `ClaimCheck` — the platform's own requests and what the library returned for them |
| `services.py` | The belt read and written through the library, trials and checks started and run, resolution, calibration, the page-published handoff |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/outbox/` |
| `tasks.py` | Celery: the relay (on beat every minute, and on request), trials, checks and resolutions — each under a time limit |
| `consumers.py` | The handler on `content.page.published` that announces a page on the belt |

## The belt's files are the record

The belt lives under `OUTBOX_BELT_ROOT` (default `content/var/outbox/belt/`; compose keeps it on the `outbox-data` volume): `stations/<station>/{outbox,inbox}/`, `ledger.jsonl` and `dead_letter.jsonl`. Nothing mirrors them into tables. Every read — the summary (`write_belt_summary`, plus the records still waiting), the messages, a trace's journey (`Belt.journey`), the dead letters, a message's CloudEvents form (`to_cloudevent`) — goes through the library to the files. The stations are `OUTBOX_BELT_STATIONS` (the e2e's by default); each has a directory, so the relay knows every recipient. Only two things here write belt files: a sender's own outbox record (`Station.send`, which validates and never overwrites), and the relay (`Belt.deliver`, in the worker, the ledger's single writer).

## What a person does

| | How |
|---|---|
| View | `belt/` (the numbers, the stations, what waits), `belt/messages/` (newest first; `kind`, `station` — from or to — `trace`, `ordering=seq`; paged), `belt/messages/<id>/` (with its CloudEvent), `belt/traces/<trace>/`, `belt/dead-letters/` |
| Send | `belt/send/` as the editor station (`OUTBOX_BELT_EDITOR`): an `idea`, an `approval` of a delivered message (`parent_id`; it keeps the parent's trace and subject), or a `signal` (optionally on an existing `trace`). The library validates it; the platform adds `payload.by` (the person) and keeps a `SentHandoff` row. A `page` names what it is about (`ref.page_id`, `ref.url`) |
| Deliver | `belt/deliver/` queues a relay pass (202, with how many records wait); the studio reads the summary again until nothing waits. Beat runs one every minute (`CELERY_BEAT_SCHEDULE["outbox-belt"]`) |
| Run a trial | `trials/` with a task card (as the harness's `tasks/*.json`, validated field by field) and an optional `lag_b`: 202, then the worker runs the arena under `OUTBOX_OUT_DIR/runs/trial-<id>/` and keeps `score_trial`'s result; `trials/<id>/` adds the arena's ledger |
| Check claims | `claim-checks/` with `claims` (`id`, `question`, `answer`, `confidence`, `sources`), a source `timeline` (`tick`, `source`, `says`, `fact`, `note`), `closes_at_tick` and `lag_b`, optionally a `title`, an `author` and the draft `page`: 202, then the worker runs `check_claims` under `runs/claims-<id>/` and keeps a verdict per claim — `pass`, or `block` with the reason |
| Resolve | `claim-checks/<id>/resolve/` with the truth for every claim (202): the worker re-scores each claim's arena from its own ledger (`resolve`) — whether the winner and the draft were right, and Brier scores |
| Calibration | `claim-checks/calibration/`: the library's `calibration` over every resolved check — mean Brier per verifier and per draft author |

Every request that starts a run honours an `Idempotency-Key`. Every endpoint is for people (`IsPerson`) holding the Django permission it names: `outboxdesk.view_belt`, `send_handoff` and `deliver_belt` for the belt; the model permissions `view_`, `add_` and (to resolve) `change_` of `trial` and `claimcheck`. Superusers hold them all; anyone else is granted them in Wagtail's groups. Every failure is the error envelope.

## The claim desk only advises

A check reads claims and sources and writes its own arenas; it never edits, saves or publishes a page, and a `block` is advice to the editor who decides. The `page` a check names is a link for the editor, and only a page they can find.

## A page that goes live

The publish and its `content.page.published` event commit together (`cms/signals.py`); the relay puts the event on `zer0:content`; and `manage.py consume_events --stream zer0:content --group outboxdesk` (the compose `belt-publisher` service) runs `consumers.page_published` once per event. It sends a `published` handoff from `OUTBOX_BELT_PUBLISHER` to `OUTBOX_BELT_PUBLISHED_TO`: its `ref` names the page (`page_id`, `url`, `url_path`), its trace is the event's `traceparent`'s when it has one, its parent is the latest delivered message about the page (an editor's approval naming it), else the event itself — the belt parents every `published` — and its id is derived from the event's, so a redelivery after a lost commit sends nothing twice. Nothing writes a belt file from the request or the signal that published the page.

## Tests

`tests/outboxdesk/`: the belt over the API (`test_belt.py`), trials, checks, resolution and calibration (`test_runs.py`, the harness's own offline policy agents racing in a temporary directory), and the page-published handoff through `handle_envelope` (`test_publish.py`). The studio's side is `web/packages/ui/test/outbox.test.tsx`.
