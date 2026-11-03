# `outbox/` — events between the planes

> The transactional outbox: events committed with the change they announce, relayed in order to Redis Streams, and handled once per consumer.

The transactional outbox (M8). A change and the event announcing it commit together, or neither does; then a relay moves events onto Redis Streams, at least once, in order.

- **`emit(type, data, subject)`** validates `data` against `schemas/events/<type>.v<N>.json` and inserts an `OutboxEvent` — and refuses to run outside a transaction, because an event that could commit without its change (or the reverse) defeats the outbox. Every HTTP request is atomic (`ATOMIC_REQUESTS`), so an admin publish and the event its signal emits share one transaction; commands and tasks that write wrap their work in `transaction.atomic()`.
- **The relay** (`relay_pending`, the `relay_outbox` command, the beat task) publishes undelivered rows oldest first and marks them. A transport failure stops the batch at that event, records the attempt, and retries next pass, so order holds. On Postgres rows are claimed with `SKIP LOCKED`.
- **Consumers** (`consumers.py`, the `consume_events` command, which loads every app's `consumers` module) read a stream through a consumer group. `handle_envelope` validates the envelope and its data, then records `(event id, consumer)` in `ProcessedEvent` in the same transaction as the handler's writes — a redelivered event is handled once.
- **Nothing in flight is lost, and nothing poisons the stream.** An entry is acked only once it is handled, so each pass first claims the group's entries pending longer than `RECLAIM_IDLE_MS` (60 s, XAUTOCLAIM) — their reader died, or their handler raised — and handles them again before reading new ones. Each entry is handled on its own, so one that fails never stops its batch; after `MAX_DELIVERIES` (5) it moves to `<stream>:dead` with its group, its delivery count and the error, and is acked, for a person to read and replay. A database or Redis error is not the event's fault: the entry stays pending and the pass ends.
- **The loops outlive a blip** (`loop.py`). `relay_outbox` and `consume_events` catch Postgres's and Redis's connection errors, drop the broken connections and back off 1, 2, 4 … 30 s instead of exiting; any other error still ends the process. Each pass that finishes touches a heartbeat (`relay`, `consumer-<name>`; `ops/heartbeat.py`) that the compose healthcheck reads, and `/readyz` reports the outbox's oldest undispatched event and each group's lag (`ops/readiness.py`).

| Stream | Written by | Read by |
|---|---|---|
| `zer0:content` | this plane | this plane's outbox desk (`outboxdesk.consumers`, group `outboxdesk`) and its own consumers (`distribution.consumers`; `automations.consumers`, the automations an event fires), through `consume_events --own --group platform` (the compose `events` service) |
| `zer0:app` | nothing since the Rails app was deleted (ADR 0008); the site renderer is its next publisher | this plane (`graph.consumers`) |

Event types and their schemas: [`schemas/events/README.md`](../../schemas/events/README.md). A CloudEvents envelope carries the run's trace id as `traceparent`, so a trace started in either plane can be followed into the other.
