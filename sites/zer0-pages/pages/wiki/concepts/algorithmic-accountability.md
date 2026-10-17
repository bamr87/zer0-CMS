---
title: "Algorithmic Accountability"
type: concept
complexity: intermediate
domain: "responsible AI / fairness"
description: "Ensuring automated decision-making systems — especially those that allocate capital or credit — are fair, explainable, and free from discriminatory bias, verified with concrete fairness metrics rather than asserted."
aliases:
  - "Fairness Auditing"
created: 2026-07-06
updated: 2026-07-06
tags:
  - concept
  - responsible-ai
  - fairness
  - algorithmic-accountability
status: seed
related:
  - "[[wiki/concepts/radical-transparency]]"
  - "[[wiki/concepts/ethical-engineering]]"
  - "[[wiki/concepts/esg-investing]]"
  - "[[wiki/entities/fairlearn]]"
sources:
  - "[[wiki/sources/wizard-topples-capitalist-dominance]]"
---

# Algorithmic Accountability

## Definition

Algorithmic accountability is "ensuring that automated decision-making systems are fair, explainable, and free from discriminatory bias." In [[wiki/sources/wizard-topples-capitalist-dominance|the wizard post]] it is the second of three principles and the audit engine's "bias checks" branch. Its distinguishing feature is that fairness is **measured, not asserted** — "the wizard's second trick is auditing the models that allocate capital."

## How It Works

Audit models with an open-source fairness toolkit — the post names [[wiki/entities/fairlearn|Fairlearn]] and IBM's AI Fairness 360 (AIF360). The core pattern is a grouped metric frame plus a parity measure:

```python
# scripts/audit_model.py
from fairlearn.metrics import MetricFrame, selection_rate, demographic_parity_difference
from sklearn.metrics import accuracy_score

metrics = MetricFrame(
    metrics={"accuracy": accuracy_score, "selection_rate": selection_rate},
    y_true=y_true,
    y_pred=y_pred,
    sensitive_features=sensitive,   # e.g. a zip-code-derived demographic
)

print(metrics.by_group)
print("Demographic parity gap:",
      demographic_parity_difference(y_true, y_pred, sensitive_features=sensitive))
```

The decision rule is unambiguous: "If the gap is non-trivial, that's your spellcheck failing. Document it, file an issue, and refuse to ship until it's addressed." When a gap is found, the FAQ prescribes: **don't ship**; investigate root causes (training-data skew, feature proxies, labeling bias); and consider mitigations — re-weighting, threshold optimization, or removing the model entirely.

## Why It Matters

Capital- and credit-allocation models can "deepen inequality" at scale and silently. Accountability turns that from an invisible externality into a reviewable artifact: every model should carry "a published model card and a fairness report," surfaced on the same dashboard as everything else. The post's governing maxim: **"'We knew and shipped anyway' is worse than 'we found nothing.'"**

## Examples

- **Parity gap gate** — the Fairlearn snippet above, wired into CI so a regression in `demographic_parity_difference` blocks a merge.
- **Proxy hunting** — a "zip-code-derived demographic" sensitive feature illustrates how a seemingly neutral input can act as a proxy for a protected attribute.

## Connections

- [[wiki/entities/fairlearn|Fairlearn]] — the toolkit implementing the metrics above (with AIF360 as a sibling).
- [[wiki/concepts/radical-transparency|Radical Transparency]] — supplies the auditable data these checks run against.
- [[wiki/concepts/ethical-engineering|Ethical Engineering]] — the ethic behind "refuse to ship."
- [[wiki/concepts/esg-investing|ESG Investing]] — accountability reports feed the governance ("G") dimension.

## Sources

- [[wiki/sources/wizard-topples-capitalist-dominance|Wizard Topples Capitalist Dominance Ingeniously]] — "Example 2: Algorithmic Accountability Check" and the fairness-audit FAQ.
