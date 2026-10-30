# ADR 0008 — Retire the Rails fleet CMS now: merge G4 and G5, delete `rails/`, and keep what it still owes as a spec

> The owner deleted the Rails fleet CMS (`rails/`) ahead of its absorption gate: the two branches that had already ported most of it (G4 and G5) merged first, and every capability the platform does not have yet is kept as a written spec, recorded in the ledger with a new status, `specified`.

- **Status:** accepted 2026-10-27 (the owner's decision); lands with the pull request that adds this file.
- **Inputs:** the owner's request of 2026-10-27, "remove the old rails CMS completely. you only need to retain the functionality specs that need to be built into the django app and frontend"; and the owner's two answers the same day: retire, rather than keep, the shared workflows other repositories call (made moot by the next answer, because G4 and G5 had already moved both to Python), and merge G4 and G5 before deleting.
- **Where:** `rails/` (deleted), the compose `cms` service and its `storage` volume, the workflows `rails-app.yml` and `abc-engine.yml`, the `cms-rails` project and its vendored copies in `workspace.yml`; [`../plan/rails-cms-spec.md`](../plan/rails-cms-spec.md); the `rails-app` and `rails-lib` rows of [`../plan/capabilities.yml`](../plan/capabilities.yml); `tools/check_absorption.py`; [amendment 0002](../amendments/0002-retire-the-rails-invariants.md).

## Context

[ADR 0006](0006-one-python-platform.md) absorbs every merged repository with its capabilities intact, and its gate refuses to let a source directory go while any of its ledger rows is `missing` or `partial`. The plan absorbed the Rails fleet CMS in three milestones — G4 (sites and jobs), G5 (distribution) and G9 (books) — and deleted it in G11.

On 2026-10-27 `main` had all 20 Rails rows open. G4 and G5 had been built on 2026-10-22, on `overhaul/sites-jobs` and `overhaul/distribution`, and never merged, nor pushed: the catalog, front-matter surgery, the confined writer, the site registry, sync and write-back, the doctor, LinkedIn channels, the queue, the lane and statistics were all in Python on branches 21 commits behind. Meanwhile the Rails app still cost a Ruby toolchain in CI, two workflows, a container that a bare `docker compose up` started, and a section of rules in `AGENTS.md` — for a CMS the platform's studio replaces.

## Decisions

| # | Decision | Mechanism that enforces it |
|---|---|---|
| 1 | **G4 and G5 merge first.** Their ports replace the Rails catalog, surgery, writer and doctor (G4) and its LinkedIn queue, channels, lane and statistics (G5); `zer0-doctor.yml` and `zer0-linkedin.yml` already run them in Python, so the repositories that call those workflows (lifehacker.dev, it-journey, zer0-mistakes, bash-365.com, ai-world-view) keep working. The merge's one integration bug — a page-published event's belt handoff written by a consumer without the belt's volume — is fixed beside it. | The merge commits and their tests; those rows `done` with their proofs. |
| 2 | **`rails/` is deleted whole**, with what only it needed: the compose `cms` service and `storage` volume, `rails-app.yml` and `abc-engine.yml`, the `cms-rails` project and its two vendored copies, the Rails keys in `.env.example`, and the ignore, lint and editor entries. | `check_absorption.py --tighten` dropped `rails/` from `ruby_ratchet` and `theme_ratchet`: Ruby under a prefix the ratchet does not list fails CI. |
| 3 | **What Rails did that the platform does not do yet is a spec**, [`rails-cms-spec.md`](../plan/rails-cms-spec.md): one section per row, with what Rails did (its paths at `d0a572fb`, the last commit that has them), where the platform stands, what to build with the tests to write, and the milestone. The milestone that builds a row sets it `done` and removes its section. | Every such row is `specified`, with `decided_by` and `spec`; the gate checks both. |
| 4 | **A new ledger status, `specified`:** the owner deleted the source before the row moved. The row keeps its `target` (the platform still owes it), does not hold up the deletion gate, and is not `done`. Only the owner sets it, as only the owner drops a row. | `check_absorption.py` (`STATUSES`, `spec_problem`): `decided_by` required, the spec file must exist, the target must still be a platform capability; `tools/tests/test_check_absorption.py`. |
| 5 | **Content is placed before the directory goes.** The ABC lexicon's platform copy (`content/agents/data/abc_lexicons/`) becomes its only copy; `abc-book.schema.json` moves to `schemas/books/`; G4 had moved the Jekyll parity fixtures to `content/tests/fixtures/`; the ABC art styles' source stays in `packages/zer0-image-generator`; drsai's `it-alphabet` book is the ABC generator's golden output. The Rails SQLite's LinkedIn channels and tokens are not migrated: a channel is set up again in the studio and its token re-entered, as G5 recorded. | `workspace.yml` declares no vendored copy; `bin/zer0 check`. |
| 6 | **The constitution's two Rails invariants are retired** — "Rails never writes content tables" and "Django never reads the Rails database" — because there is no Rails left for them to bound. | [Amendment 0002](../amendments/0002-retire-the-rails-invariants.md), ratified with this change. |

## Consequences

- The platform is the only CMS: `docker compose --profile content up -d --wait`, the studio at `/studio/`. A bare `docker compose up` starts nothing; the image generator's panel stays behind `--profile imagegen`.
- Ruby is left only in `packages/zer0-image-generator/` and `sites/zer0-pages/` (234 files, from 342).
- Until their milestones build them, a person loses what [the spec](../plan/rails-cms-spec.md) lists: the page list's filter language, duplicating and deleting a page, a rendered preview in source mode, the media library, listing and drawing missing previews, the ABC wizard and its export into drsai, registering every discovered site at once and detaching one, and re-recording the Jekyll parity fixtures.
- `app.user.interaction` has no publisher; the graph's behavioural edges wait for the site renderer to publish it (the Rails app never did in practice).
- The local Docker volume a Rails CMS used (`<project>_storage`, its SQLite) is no longer referenced; nothing deletes it.
- The uncommitted follow-up work in the G5 branch's worktree was not merged.

## Open — the owner's decisions

1. **The access guard.** Sign-in replaces Rails' loopback-or-password guard and Docker-gateway rule; the spec keeps only a test of the Host allow-list. Dropping the rest of `rails.access-guard` is the owner's call.
2. **What files sites receive.** Future-dated posts and `status: draft` files import as live; unpublishing a page does not reach its file; a draft written back has no `draft: true`. Each is in the spec's "Found while writing this spec".
3. **Two `distribution` doctor checks.** G4's `content/sites/doctor.py` runs its own; G5's `content/distribution/lane/doctor.py` ports the same check and nothing calls it. One should go.
