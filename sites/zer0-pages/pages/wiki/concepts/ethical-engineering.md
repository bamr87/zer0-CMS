---
title: "Ethical Engineering"
type: concept
complexity: beginner
domain: "engineering ethics"
description: "Building technology that prioritizes human well-being over profit maximization — the wizard post's central ethic, grounded in the ACM/IEEE ethics frameworks and operationalized as a practitioner's checklist."
aliases:
  - "Ethics-First Engineering"
created: 2026-07-06
updated: 2026-07-06
tags:
  - concept
  - ethics
  - responsible-tech
status: seed
related:
  - "[[wiki/concepts/algorithmic-accountability]]"
  - "[[wiki/concepts/radical-transparency]]"
  - "[[wiki/concepts/stakeholder-capitalism]]"
sources:
  - "[[wiki/sources/wizard-topples-capitalist-dominance]]"
---

# Ethical Engineering

## Definition

Ethical engineering is "building technology that prioritizes human well-being over profit maximization." It is the third of [[wiki/sources/wizard-topples-capitalist-dominance|the wizard post]]'s three principles and, really, its thesis. The post's epigraph states it plainly: *"The tools we build shape the world we live in. Every line of code is a choice between reinforcing the status quo and building something better."*

## How It Works

The post treats ethics not as a vibe but as a practice with prerequisites and a checklist.

- **Grounding frameworks.** It expects the reader to have "read at least once" an ethical framework — naming the [ACM Code of Ethics](https://www.acm.org/code-of-ethics) and the IEEE *Ethically Aligned Design* report as examples.
- **A practitioner's checklist** ("before declaring a project 'Merlin-grade'"):
  - Source data and transformations live in a public (or auditor-readable) repo.
  - Every model ships a published model card and a fairness report.
  - Stakeholder representatives (employees, customers, affected communities) are named in the governance README.
  - Impact metrics sit on the same dashboard as financial metrics — not a separate "ESG appendix."
  - There is a low-friction channel for whistleblowers and external researchers to file findings.

## Why It Matters

The post situates this against a live tension in the field: "engineers increasingly grapple with the ethical implications of the systems they create — from recommendation algorithms that amplify misinformation to financial platforms that deepen inequality." Ethical engineering is the disposition that turns [[wiki/concepts/radical-transparency|transparency]] and [[wiki/concepts/algorithmic-accountability|accountability]] from optional features into defaults — and, in the fable's terms, the wizard's "real magic was simply *refusing to look away*."

## Examples

- **Refuse to ship** — a failed fairness audit is not a warning to override but a gate: "refuse to ship until it's addressed" (see [[wiki/concepts/algorithmic-accountability|algorithmic accountability]]).
- **Internal-first** — where full open-sourcing isn't possible, apply the same ethic internally: open the data lake to employees, publish model cards on the intranet, add fairness checks to CI.

## Connections

- [[wiki/concepts/algorithmic-accountability|Algorithmic Accountability]] — the ethic made checkable.
- [[wiki/concepts/radical-transparency|Radical Transparency]] — the ethic applied to data access.
- [[wiki/concepts/stakeholder-capitalism|Stakeholder Capitalism]] — the governance form the ethic implies.

## Sources

- [[wiki/sources/wizard-topples-capitalist-dominance|Wizard Topples Capitalist Dominance Ingeniously]] — "A Call to Action for Technologists," "Prerequisites," and "A Practitioner's Checklist."
