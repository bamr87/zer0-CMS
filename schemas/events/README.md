# `schemas/events/` — the event contracts between the planes

> The CloudEvents contracts between the planes: every event type, who publishes and consumes it, and the schema its data is validated against.

Every event the content plane (`content/`) or an experience plane publishes is a [CloudEvents 1.0](https://github.com/cloudevents/spec/blob/v1.0.2/cloudevents/spec.md) envelope in structured JSON mode, validated against [`cloudevent.v1.json`](cloudevent.v1.json), whose `data` is validated against the schema its `dataschema` names. Events travel through each plane's transactional outbox to Redis Streams (`zer0:content`, `zer0:app`); delivery is at least once, so every consumer dedupes on the envelope's `id`. ADR 0001 and [`../../content/outbox/README.md`](../../content/outbox/README.md) explain the mechanism.

| Type | Published by | Data schema | Consumed by |
|---|---|---|---|
| `content.page.published` | content | [`content.page.published.v1.json`](content.page.published.v1.json) | the outbox desk's belt publisher; distribution's drafts (`content/distribution/consumers.py`); the automations it fires (`content/automations/consumers.py`) |
| `content.suggestion.created` | content | [`content.suggestion.created.v2.json`](content.suggestion.created.v2.json) (v1: [`content.suggestion.created.v1.json`](content.suggestion.created.v1.json)) | editor notifications; content: the automations it fires |
| `agent.run.completed` | content | [`agent.run.completed.v2.json`](agent.run.completed.v2.json) (v1: [`agent.run.completed.v1.json`](agent.run.completed.v1.json)) | run dashboards; content: the automations its own runs fire |
| `app.user.interaction` | none today (the Rails app until ADR 0008) | [`app.user.interaction.v1.json`](app.user.interaction.v1.json) | content: nightly behavioural edges (aggregates only — `anon_id` is never stored) |

`examples/` holds one valid envelope per type, of the version the platform publishes. The content plane's contract tests validate its events against these schemas and parse every example: `content/tests/outbox/test_contracts.py` (the Rails plane's, `test_event_contracts.rb`, went with it in ADR 0008). The v1 schemas' descriptions still name the Rails app as their publisher or consumer, as they were when cut; a v2 corrects them.

The platform publishes v2 of `agent.run.completed` and `content.suggestion.created` since P-D6 ([ADR 0009](../../docs/adr/0009-public-ids.md)): a run and a suggestion are named by their UUID public ids, the ids every API gives, where v1 named them by their integer keys. Both v1 schemas stay, so an envelope already in a stream still validates; every consumer of either type is in this repository and moved in the same change, so none reads v1 any more — an automation hears a v1 event's run or suggestion as one it cannot see, and does nothing.

## Changing a contract

A change that a consumer could notice — a new required field, a removed field, a narrowed type — is a new version: copy `<type>.v1.json` to `<type>.v2.json`, change it, publish the new version, and keep accepting v1 until every consumer has moved. Adding an optional property is not a new version. Either way, update the example and both planes' contract tests in the same pull request (AGENTS.md § The planes and their boundary).
