---
title: "Impact-Weighted Accounting"
type: concept
complexity: intermediate
domain: "sustainable finance / ESG measurement"
description: "Measuring corporate success not only by revenue but by weighted social and environmental outcomes — a methodology that can be expressed declaratively, version-controlled, and PR-reviewed like any other config."
aliases:
  - "Impact-Weighted Accounts"
created: 2026-07-06
updated: 2026-07-06
tags:
  - concept
  - esg
  - sustainable-finance
  - accounting
status: seed
related:
  - "[[wiki/concepts/esg-investing]]"
  - "[[wiki/concepts/radical-transparency]]"
  - "[[wiki/concepts/stakeholder-capitalism]]"
  - "[[wiki/entities/hbs-impact-weighted-accounts]]"
sources:
  - "[[wiki/sources/wizard-topples-capitalist-dominance]]"
---

# Impact-Weighted Accounting

## Definition

Impact-weighted accounting measures corporate success "not only by revenue, but by social and environmental outcomes." In [[wiki/sources/wizard-topples-capitalist-dominance|the wizard post]] it is the third reform pillar and the audit engine's ESG-scorecard branch. Its real-world anchor is [[wiki/entities/hbs-impact-weighted-accounts|Harvard Business School's Impact-Weighted Accounts Project]]. The post's contribution is to show it is **not just theory** — "Impact-weighted accounting can be expressed declaratively."

## How It Works

Represent the weighting scheme as a version-controlled config. The post's starter `impact-weights.yml`:

```yaml
# impact-weights.yml
version: 1
weights:
  financial:
    revenue: 1.0
    operating_margin: 0.8
  social:
    living_wage_compliance: 1.2
    workforce_diversity: 0.6
    workplace_safety: 1.0
  environmental:
    scope1_emissions: -1.5     # negative = penalizes harm
    scope2_emissions: -1.0
    scope3_emissions: -0.5
    water_intensity: -0.4
thresholds:
  publish_alert_if_score_below: 0.0
report:
  format: [html, json]
  destination: s3://transparency-reports/
```

The load-bearing design ideas:

- **Positive and negative weights** — financial and social goods score positive; environmental harms (Scope 1/2/3 emissions, water intensity) carry **negative** weights that penalize harm directly in the score.
- **Thresholds trigger action** — e.g. `publish_alert_if_score_below: 0.0`.
- **Declarative and reviewable** — "Combine the YAML with a small scoring function and you have the third pillar — measurable, version-controlled, and PR-reviewable corporate impact."

## Why It Matters

The point is integration, not annexation. The practitioner's checklist insists impact metrics be "part of the same dashboard as financial metrics — not a separate 'ESG appendix.'" Encoding impact as reviewable config makes it a first-class engineering artifact: diffable, testable, and auditable alongside the financials it sits next to.

## Examples

- **Companion data file** — the post's own asset backlog proposes extracting the YAML into `_data/impact_weights_example.yml` so other posts can reuse it (not yet created).
- **Harm as negative score** — a high-emissions quarter mechanically drags the weighted score below the alert threshold, forcing publication rather than burying it.

## Connections

- [[wiki/entities/hbs-impact-weighted-accounts|HBS Impact-Weighted Accounts Project]] — the authoritative real-world methodology.
- [[wiki/concepts/esg-investing|ESG Investing]] — the broader frame; impact weighting is how the "E" and "S" become numbers.
- [[wiki/concepts/radical-transparency|Radical Transparency]] — the pipeline that produces the scorecard.
- [[wiki/concepts/stakeholder-capitalism|Stakeholder Capitalism]] — scoring stakeholder outcomes operationalizes stakeholder-first governance.

## Sources

- [[wiki/sources/wizard-topples-capitalist-dominance|Wizard Topples Capitalist Dominance Ingeniously]] — "Example 3: Impact-Weighted Accounting Config" and the practitioner's checklist.
