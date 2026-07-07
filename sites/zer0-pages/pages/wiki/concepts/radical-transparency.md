---
title: "Radical Transparency"
type: concept
complexity: intermediate
domain: "civic tech / financial accountability"
description: "Making financial and corporate data openly accessible and auditable by the public — the first of the wizard post's three principles — realized as a concrete, swappable open-source pipeline from public data sources to a public dashboard."
aliases:
  - "Open Financial Ledgers"
  - "Transparency Pipeline"
created: 2026-07-06
updated: 2026-07-06
tags:
  - concept
  - transparency
  - civic-tech
  - open-data
status: seed
related:
  - "[[wiki/concepts/algorithmic-accountability]]"
  - "[[wiki/concepts/impact-weighted-accounting]]"
  - "[[wiki/concepts/ethical-engineering]]"
  - "[[wiki/entities/sec-edgar]]"
  - "[[wiki/entities/gleif]]"
sources:
  - "[[wiki/sources/wizard-topples-capitalist-dominance]]"
---

# Radical Transparency

## Definition

Radical transparency is the practice of **making financial and corporate data openly accessible and auditable by the public**. In [[wiki/sources/wizard-topples-capitalist-dominance|the wizard post]] it is the first of three principles (with [[wiki/concepts/algorithmic-accountability|algorithmic accountability]] and [[wiki/concepts/ethical-engineering|ethical engineering]]) and the foundation of the first reform pillar, "open financial ledgers" — leveraging distributed-ledger technology to make transactions publicly verifiable "without sacrificing individual privacy." The post's key move is to de-mystify it: "Merlin's magic" is not arcane, it is "a small, well-composed open-source pipeline."

## How It Works

### The transparency pipeline

The post's architecture diagram lays out a linear, fully swappable pipeline — each node "maps to a real, swappable piece of software — nothing proprietary, nothing arcane":

1. **Public data sources** — [[wiki/entities/sec-edgar|SEC EDGAR]], [[wiki/entities/gleif|GLEIF]], OpenCorporates.
2. **Ingest & normalize** — Python / dbt.
3. **Open ledger** — Postgres + Parquet.
4. **Audit engine** — fans out to three outputs:
   - an [[wiki/concepts/algorithmic-accountability|algorithmic-accountability]] report (bias checks),
   - an [[wiki/concepts/esg-investing|ESG]] scorecard ([[wiki/concepts/impact-weighted-accounting|impact weighting]]),
   - investigative alerts (anomaly detection).
5. **Public dashboard** — a static site + JSON API.
6. **Stakeholders** — citizens, regulators, boards.

### Start boring: a public-filing ingest

"Most 'radical transparency' projects start with a boring 30-line script that pulls a public filing and writes it somewhere queryable." The post's minimal [[wiki/entities/sec-edgar|SEC EDGAR]] XBRL ingest:

```python
# scripts/ingest_edgar.py
import json
from pathlib import Path
import requests

UA = {"User-Agent": "merlin-financialis contact@example.org"}
OUT = Path("data/filings")
OUT.mkdir(parents=True, exist_ok=True)

def fetch_company_facts(cik: str) -> dict:
    """Fetch a company's structured XBRL facts from SEC EDGAR."""
    url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik.zfill(10)}.json"
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    return r.json()
```

"Run it, commit the output to a public repo, and you have built the first stone of an 'open ledger.' No spellbook required."

## Why It Matters

Transparency is the substrate everything else stands on: you cannot hold a model or a company [[wiki/concepts/algorithmic-accountability|accountable]] for what no one can see. The post frames the whole effort as, ultimately, "refusing to look away" — the data has "been on the shelf the whole time." Making it queryable and public is what converts inert filings into artifacts a journalist, regulator, or DAO can act on.

## Examples

- **Open ledger seed** — commit `AAPL.json` (from the EDGAR ingest above) to a public repo; that queryable artifact is the pipeline's first node made real.
- **Internal first move** — the FAQ notes that even without open-sourcing financials, "internal transparency is a credible first move": open the data lake to all employees, publish model cards on the intranet, add fairness checks to CI.

## Connections

- [[wiki/concepts/algorithmic-accountability|Algorithmic Accountability]] — what transparency enables downstream: auditing the models the ledger feeds.
- [[wiki/concepts/impact-weighted-accounting|Impact-Weighted Accounting]] — the ESG-scorecard branch of the audit engine.
- [[wiki/concepts/ethical-engineering|Ethical Engineering]] — the ethic that motivates opening the data at all.
- [[wiki/entities/sec-edgar|SEC EDGAR]] · [[wiki/entities/gleif|GLEIF]] — the public data sources feeding the pipeline.

## Sources

- [[wiki/sources/wizard-topples-capitalist-dominance|Wizard Topples Capitalist Dominance Ingeniously]] — "Unraveling the Web of Corruption," "Enacting Sweeping Financial Reform," and "The Wizard's Workshop / Example 1."
