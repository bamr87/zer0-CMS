<!-- kit: governance v0.1.0 -->
# 0002 — Retire the Rails invariants

- **Status:** proposed
- **Date:** 2026-10-27
- **Proposed by:** Claude (AI agent), at the maintainer's request to remove the Rails CMS
- **Ratified by:**
- **Affects:** constitution §2 (its first two invariants); feature ids: none
- **Supersedes:** none
- **Related:** [ADR 0008](../adr/0008-retire-the-rails-cms.md), [docs/plan/rails-cms-spec.md](../plan/rails-cms-spec.md)

## Context

The Rails fleet CMS (`rails/`) was deleted on 2026-10-27 (ADR 0008). Two invariants in § 2 exist only to bound it: "Rails never writes content tables. Don't add a third Rails writer." and "Django never reads the Rails database; it receives Rails data as aggregated events (`app.user.interaction`) or through Rails MCP tools." With no Rails left they constrain nothing, and kept in place they tell every agent that reads the constitution first that a Rails plane exists.

## Amendment

Remove these two bullets from § 2 (Invariants):

> - Rails never writes content tables. Don't add a third Rails writer. _(AGENTS.md)_
> - Django never reads the Rails database; it receives Rails data as aggregated events (`app.user.interaction`) or through Rails MCP tools. _(AGENTS.md)_

Nothing replaces them. The invariant after them — frontends and clients are headless and never read a database — already covers any experience plane that returns.

## Consequences

`AGENTS.md`'s matching bullet under "The platform and its boundary" goes in the same change. If an experience plane outside the platform comes back, its boundary is a new amendment, not a revival of these.
