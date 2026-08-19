# `core/analytics` — how the author's own content performed

The step that was missing between `governance/` and `catering/`.

`catering/` could already turn engagement into a worklist and `contract/` could already store it, but nothing turned statistics *from a platform* into the `performance.json` those two agree on. So the loop stayed open: a worklist could be rendered, but only from a file somebody had typed by hand, and Lanes B–D were empty in practice.

## Two things, and no third

**`readPlan` declares the read surface** as data rather than prose — every call this lane would make, with what it returns. That makes it printable, testable, and showable to a reviewer *before* a credential exists.

**`ingestPerformance` performs the join.** Statistics arrive keyed by a platform's post id; catering needs them keyed by content path. The ledger is the only thing that knows which post came from which page, so it is the join table.

## The boundary is a test, not a promise

Everything here is the author's own **aggregate** numbers. Nothing identifies who engaged: no per-reader record, no resolving a reaction to a profile, no join against any other dataset about a person.

`readSurfaceIsOwnContentOnly` checks that every call's `returns` describes the author's own content, and `loop.test.ts` asserts it for both shipped plans *and* asserts that a follower-enumeration call fails it. Adding a call that reaches another person is therefore a failing build, not a review comment.

Because `catering/` consumes only what this module produces, that boundary holds for the whole feedback loop by construction.

## There is no `fetch`

Deliberate. Fetching needs a live credential and a platform client, which belong in a publish target, not in the pure layer. A stub returning invented numbers would be worse than nothing — it would poison the worklist that decides what somebody writes next, and do it silently. `ingestPerformance` takes the statistics as an argument and lets the caller say where they came from.

## Shape

| Export | Purpose |
|---|---|
| `readPlan(kind)` / `MEMBER_READS` / `ORGANIZATION_READS` | the complete read surface |
| `readSurfaceIsOwnContentOnly(plan)` | the boundary check the tests pin |
| `describeReadPlan(kind)` | the surface as text |
| `postIdIndex(ledger)` | platform post id → content path |
| `ingestPerformance(ledger, stats, existing?)` | the join; pure, merges over history |
| `unwrapStats(raw)` | accepts a bare map or a `{"posts": …}` export |

`POST_ID_KEYS` covers `urn` plus the names the Python lane writes, because an ingest that only understood `urn` would silently match nothing against a ledger the other lane produced.
