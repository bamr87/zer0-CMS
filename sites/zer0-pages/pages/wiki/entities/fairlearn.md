---
title: "Fairlearn"
type: entity
entity_type: software
description: "An open-source Python toolkit for assessing and improving the fairness of machine-learning models; the concrete tool behind the wizard post's algorithmic-accountability example."
role: "Fairness-assessment library"
first_mentioned: "[[wiki/sources/wizard-topples-capitalist-dominance]]"
created: 2026-07-06
updated: 2026-07-06
tags:
  - entity
  - software
  - responsible-ai
  - fairness
status: seed
related:
  - "[[wiki/concepts/algorithmic-accountability]]"
sources:
  - "[[wiki/sources/wizard-topples-capitalist-dominance]]"
---

# Fairlearn

## Overview

Fairlearn is an open-source Python toolkit for assessing and improving the fairness of machine-learning models. In [[wiki/sources/wizard-topples-capitalist-dominance|the wizard post]] it is the tool that makes [[wiki/concepts/algorithmic-accountability|algorithmic accountability]] "approachable" — the mechanism for auditing "the models that allocate capital." Its homepage is [fairlearn.org](https://fairlearn.org/).

## Key Facts

- **Core API used in the post:** `MetricFrame` (computes metrics disaggregated by a sensitive feature), plus the metric helpers `selection_rate` and `demographic_parity_difference`.
- **Usage pattern:** pass `y_true`, `y_pred`, and `sensitive_features` (e.g. a zip-code-derived demographic) to `MetricFrame`; inspect `metrics.by_group`; compute the demographic-parity gap as a single number.
- **Sibling tool:** the post names IBM's **AI Fairness 360 (AIF360)** ([aif360.res.ibm.com](https://aif360.res.ibm.com/)) as an equivalent alternative; both fill the same role and are not given separate treatment here.
- **Reference:** the post links the [Fairlearn user guide](https://fairlearn.org/main/user_guide/index.html) under Further Reading.

## Connections

- [[wiki/concepts/algorithmic-accountability|Algorithmic Accountability]] — the concept Fairlearn operationalizes; see that page for the full code example and decision rule.

## Sources

- [[wiki/sources/wizard-topples-capitalist-dominance|Wizard Topples Capitalist Dominance Ingeniously]] — "Example 2: Algorithmic Accountability Check."
