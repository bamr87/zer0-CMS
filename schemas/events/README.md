# `schemas/events/` — the event contracts between the planes

Every event the content plane (`content/`) or the experience plane (`rails/`) publishes is a [CloudEvents 1.0](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md) envelope in structured JSON mode, validated against [`cloudevent.v1.json`](cloudevent.v1.json), whose `data` is validated against the schema its `dataschema` names. Events travel through each plane's transactional outbox to Redis Streams (`zer0:content`, `zer0:app`); delivery is at least once, so every consumer dedupes on the envelope's `id`. ADR 0001 and [`../../content/outbox/README.md`](../../content/outbox/README.md) explain the mechanism.

| Type | Published by | Data schema | Consumed by |
|---|---|---|---|
| `content.page.published` | content | [`content.page.published.v1.json`](content.page.published.v1.json) | Rails: cache purge, LinkedIn distribution |
| `content.suggestion.created` | content | [`content.suggestion.created.v1.json`](content.suggestion.created.v1.json) | editor notifications |
| `agent.run.completed` | both | [`agent.run.completed.v1.json`](agent.run.completed.v1.json) | run dashboards; the other plane's trace view |
| `app.user.interaction` | Rails | [`app.user.interaction.v1.json`](app.user.interaction.v1.json) | content: nightly behavioural edges (aggregates only — `anon_id` is never stored) |

`examples/` holds one valid envelope per type. Both planes' contract tests validate their own events against these schemas and parse every example: `content/tests/outbox/test_contracts.py` and `rails/test/zer0_cms/test_event_contracts.rb`.

## Changing a contract

A change that a consumer could notice — a new required field, a removed field, a narrowed type — is a new version: copy `<type>.v1.json` to `<type>.v2.json`, change it, publish the new version, and keep accepting v1 until every consumer has moved. Adding an optional property is not a new version. Either way, update the example and both planes' contract tests in the same pull request (AGENTS.md § The planes and their boundary).
