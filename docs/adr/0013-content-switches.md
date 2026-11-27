# ADR 0013 — Content switches: the platform holds a credential that writes the outlets' Actions variables, and records every flip as an event

> The studio flips the content outlets' GitHub Actions switches (repository variables) with a credential a person stores in the platform — encrypted, write-only, used through a declared call plan that never reaches a secret — and records each flip as a `content.switches.flipped` event; the hub's switch map stays the record, which the platform reads and never writes.

- **Status:** proposed 2026-11-25.
- **Inputs:** the maintainer's direction of 2026-11-25 ("switch them all on. make sure this option/switch is also built into … the CMS frontend settings/configuration"); the hub's constitution § 17 (the switch map is the source of truth and repository variables its projections; a switch tool shows the diff first, writes only on explicit apply and confirmation, records who, what, scope, reason, old and new, and never reads, prints or changes a secret); the hub's `_data/fleet.yml` `switches:` (schema `switches/v1`) and `tools/weekly/prepare.py` `switch_state`; the extension's Fleet console (`src/core/fleet/`), which flips a lane's switch with the person's own GitHub session.
- **Where:** `content/switches/` (README), `schemas/events/content.switches.flipped.v1.json`, the studio's Content switches section (`web/packages/ui/src/sites/ContentSwitches.tsx`, `/studio/sites/switches`), the extension bridge's `LIVE_CHANGES` (`src/core/studio/bridge.ts`).

## Context

The outlets — bash-365.com, lifehacker.dev and it-journey — publish content through GitHub Actions loops, each gated by a repository variable. Until now they were flipped with `gh variable set` or the extension's Fleet console, both with a person's own GitHub session, and recorded by hand in the hub. The studio has no GitHub session of a person: the platform only reaches GitHub with credentials it holds (a distribution channel's token, kept per channel). A switch is not a channel's: it belongs to an outlet repository, which no platform model names.

## Decision

1. **One credential for the switches, held by the platform.** `switches.SwitchConfig` keeps it, encrypted with the AI layer's keys (`ai/crypto.py`, rotated with them), write-only over the API (only `has_credential` comes back), never logged and scrubbed out of every error. A person who manages sites (`sites.manage_site`) sets it in the studio; it is a fine-grained token whose repository permission "Variables" is read and write, on the outlets. The platform never creates one, and never reads one from the environment.
2. **A declared call plan.** Every GitHub call is an entry of `switches/github.py` `CALLS`, and the client takes a call id, never a URL: the hub's map file, an outlet's variables (list, one), update, create. No path reaches a secret, nothing is deleted, nothing dispatches or merges.
3. **Diff first, write on confirmation, on the worker.** A preview writes nothing; an apply needs `confirm: true`, a reason and the preview's digest (409 when anything changed since), and starts a job that sets each variable, reads it back, and emits `content.switches.flipped` with who, the outlet, the scope, the reason and each old and new value — every write attempted, whether or not it held.
4. **The hub's map stays the record.** The platform reads `_data/fleet.yml` (or a local hub checkout) and never writes it; a flip shows as drift until the hub records it, through the hub's console.
5. **Merge authority is a brake.** A switch that decides what merges without a person (`AUTO_MERGE_ENABLED`, `AUTO_UPDATE_ENABLED`, `AUTO_FIX_ENABLED`, `*AUTOMERGE*`) may be switched off here, never on — the line the extension's `policy.ts` already draws.

## Consequences

- The platform can change how the fleet's content loops run. That is the point, and the reason the credential is narrow (Variables only, on the outlets), the permission is `sites.manage_site`, and every flip is confirmed, reasoned and recorded. Revoking the token in GitHub, or removing it in the studio, takes the ability away at once.
- A flip and the hub's record can disagree until someone records it; the studio says so on every such row ("drift: record it in the hub map").
- `content.switches.flipped` has no consumer yet; it is the platform's record. A consumer that records the flip in the hub (a pull request to `_data/fleet.yml`) would be a later decision.
- Reversing this means deleting `content/switches/` and its migration, and keeping the event schema for envelopes already in a stream.

## Enforced by

`content/tests/switches/test_github.py` (the plan's three guards — repository-scoped with "own" returns, never a secret, no deletes — and a client that refuses an undeclared call or a name that is not one segment, and never lets the credential into a message), `content/tests/switches/test_api.py` (only `sites.manage_site`; the credential written encrypted and never returned; a preview that writes nothing; an apply refused without confirmation, a reason, a credential or an unchanged digest; the job's writes, read-back and event; merge authority refused on), `content/tests/outbox/test_contracts.py` (the event's schema and example), `src/test/webview.test.ts` (the extension asks before an apply).
