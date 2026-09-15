# `Zer0Cms::LinkedIn` — the API client

A LinkedIn client in stdlib Ruby, and nothing that decides what to publish. The lane that does is `../distribution/`; the design of record is [`docs/DISTRIBUTION.md`](../../../../docs/DISTRIBUTION.md).

| File | What it holds |
|---|---|
| `plan.rb` | Every call the client can make, as data: verb, host, path, scopes, and a sentence saying what comes back. The tests fail if a `returns` sentence lacks the word "own" or a path reaches a member graph, messaging, per-member engagement or search |
| `client.rb` | `Client#request(call_id, …)`: refuses an undeclared call or a scope the token is known not to hold, builds the URL and the versioned headers, retries reads on 429/5xx and writes on 429 only, maps errors without ever carrying a credential |
| `transport.rb` | `NetHttpTransport` (https only) and `ScriptedTransport`, which answers from a script, records every request and raises on an unscripted one — every test and every rehearsal uses it |
| `restli.rb` | Rest.li 2.0 encoding: percent-encoded URNs, `List(...)`, `(key:value)` records |
| `little_text.rb` | Escaping `commentary` to LinkedIn's little text format, keeping hashtags and person/organization mentions |
| `oauth.rb` | The consent URL, code exchange, refresh, introspection, and the member behind a token |
| `posts.rb` | Text and article payloads (pure), create, get, find by author, delete |
| `images.rb` | A link card's thumbnail: reserve, upload, wait |
| `organizations.rb` | The pages the member holds a posting role on; `nil`, not `[]`, when the token may not read roles |
| `statistics.rb` | Aggregate counts for the author's own posts: page posts in batches of twenty, a member's post one metric per call |

Rules for a change here: a new call is a new `Plan::Call` with an honest `returns` sentence, never a URL built elsewhere; nothing here may require a gem (`bin/test-stdlib` runs with no bundle); and every behaviour gets a `ScriptedTransport` test in `test/zer0_cms/test_linkedin.rb`.
