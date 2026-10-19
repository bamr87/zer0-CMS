# Architecture decision records

One file per decision that changes how the repository is put together. An ADR records the question, the answer and what it costs; it changes only when the decision does. The extension's own decisions (D1–D17) and lettered decisions (D-A–D-I) predate this directory and live in [`../ARCHITECTURE.md`](../ARCHITECTURE.md); the build plan the ADRs feed is [`../plan/PLAN.md`](../plan/PLAN.md).

| ADR | Decision | Status |
|---|---|---|
| [0001](0001-target-architecture.md) | One agent-native headless CMS: a Django/Wagtail content plane, a Rails experience plane, the extension and the Jekyll sites as its clients and frontends | accepted, partially implemented |

A new ADR takes the next number, opens with a status line, and names the mechanism that enforces it — a decision no test or gate defends is a preference.
