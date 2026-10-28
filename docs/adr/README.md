# Architecture decision records

> The architecture decision records, 0001–0008, one per decision that changes how the repository is put together; ADR 0006 (one Python platform with a React frontend, every merged repository absorbed, no Ruby) is the current target.

One file per decision that changes how the repository is put together. An ADR records the question, the answer and what it costs; it changes only when the decision does. The extension's own decisions (D1–D17) and lettered decisions (D-A–D-I) predate this directory and live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the build plan the ADRs feed is [`../plan/PLAN.md`](../plan/PLAN.md).

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-target-architecture.md) | One agent-native headless CMS: a Django/Wagtail content plane, a Rails experience plane, the extension and the Jekyll sites as its clients and frontends | accepted, partially implemented |
| [0002](0002-one-home-cutover.md) | One home: work happens only here, the originals are archived, releases and Pages move here, and content goes DB-first site by site (PLAN-D1) — amended by 0005: the theme is not one of the originals this applies to | accepted, not yet implemented |
| [0003](0003-framework-rebuild.md) | The framework rebuild: PLAN-D4 decided (barodybroject becomes `apps/parodynews`, no product brand in the framework), theme includes ship no person, PR evidence and vendored tool copies leave the tree, history rewrite recorded as the owner's call | accepted, implemented |
| [0004](0004-one-platform.md) | One platform: `content/` absorbs the Rails plane and the apps function by function behind parity gates, the Wagtail admin is the CMS, the extension stays as its client (PLAN-D5), the platform is built to the fleet's enterprise rows, deploy is cloud-agnostic and sign-in is OIDC first | accepted, in progress (Phase G/H) |
| [0006](0006-one-python-platform.md) | One Python platform with a React frontend: a complete, modern, AI-assisted CMS (Wagtail as a headless library, the studio and the site renderer in React, the extension at parity with the studio) that manages, monitors and improves sites with AIEO in the loop; every merged repository absorbed with its content and capabilities, tracked in a gated ledger; no Ruby | accepted, in progress (Phase P) — **the current target; read it first** |
| [0005](0005-theme-goes-home.md) | The theme goes home: `jekyll-theme-zer0` is developed in `bamr87/zer0-mistakes` again (with its Rails theme studio), `packages/zer0-mistakes/` leaves this repository after its changes are upstream, and the platform consumes the theme as each site declares it | accepted, in progress (Phase T) |
| [0007](0007-outbox-desk.md) | The outbox desk: the outbox harness (bamr87/outbox) as a dependency loaded under its own name, its belt's files the record (no mirror tables), a page going live announced on the belt through the transactional outbox's consumer, a claim desk that only advises, every run in the worker — the studio's Outbox area | proposed |
| [0008](0008-retire-the-rails-cms.md) | Retire the Rails fleet CMS now: G4 and G5 merged, `rails/` deleted, and what it still owes kept as a spec ([`plan/rails-cms-spec.md`](../plan/rails-cms-spec.md)) — a ledger row whose source the owner deleted early is `specified` | accepted |

A new ADR takes the next number, opens with a status line, and names the mechanism that enforces it — a decision no test or gate defends is a preference.
