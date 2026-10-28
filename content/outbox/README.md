# `outbox/` — events between the planes

> The transactional outbox: events committed with the change they announce, relayed in order to Redis Streams, and handled once per consumer.

The transactional outbox (M8). A change and the event announcing it commit together, or neither does; then a relay moves events onto Redis Streams, at least once, in order.

- **`emit(type, data, subject)`** validates `data` against `schemas/events/<type>.v<N>.json` and inserts an `OutboxEvent` — and refuses to run outside a transaction, because an event that could commit without its change (or the reverse) defeats the outbox. Every HTTP request is atomic (`ATOMIC_REQUESTS`), so an admin publish and the event its signal emits share one transaction; commands and tasks that write wrap their work in `transaction.atomic()`.
- **The relay** (`relay_pending`, the `relay_outbox` command, the beat task) publishes undelivered rows oldest first and marks them. A transport failure stops the batch at that event, records the attempt, and retries next pass, so order holds. On Postgres rows are claimed with `SKIP LOCKED`.
- **Consumers** (`consumers.py`, the `consume_events` command, which loads every app's `consumers` module) read a stream through a consumer group. `handle_envelope` validates the envelope and its data, then records `(event id, consumer)` in `ProcessedEvent` in the same transaction as the handler's writes — a redelivered event is handled once.

| Stream | Written by | Read by |
|---|---|---|
| `zer0:content` | this plane | Rails; this plane's outbox desk (`outboxdesk.consumers`, group `outboxdesk`) and its own consumers (`distribution.consumers`), through `consume_events --stream zer0:content --group platform` (the compose `events` service) |
| `zer0:app` | Rails | this plane (`graph.consumers`) |

Event types and their schemas: [`schemas/events/README.md`](../../schemas/events/README.md). A CloudEvents envelope carries the run's trace id as `traceparent`, so a trace started in either plane can be followed into the other.
