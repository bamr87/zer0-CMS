# Architecture decision records

One file per decision that changes how the repository is put together. An ADR records the question, the answer and what it costs; it changes only when the decision does. The extension's own decisions (D1–D17) and lettered decisions (D-A–D-I) predate this directory and live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the build plan the ADRs feed is [`../plan/PLAN.md`](../plan/PLAN.md).

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-target-architecture.md) | One agent-native headless CMS: a Django/Wagtail content plane, a Rails experience plane, the extension and the Jekyll sites as its clients and frontends | accepted, partially implemented |
| [0002](0002-one-home-cutover.md) | One home: work happens only here, the originals are archived (the theme repository becomes a read-only mirror), releases and Pages move here, and content goes DB-first site by site (PLAN-D1) | accepted, not yet implemented |
| [0003](0003-framework-rebuild.md) | The framework rebuild: PLAN-D4 decided (barodybroject becomes `apps/parodynews`, no product brand in the framework), theme includes ship no person, PR evidence and vendored tool copies leave the tree, history rewrite recorded as the owner's call | accepted, implemented |

A new ADR takes the next number, opens with a status line, and names the mechanism that enforces it — a decision no test or gate defends is a preference.
