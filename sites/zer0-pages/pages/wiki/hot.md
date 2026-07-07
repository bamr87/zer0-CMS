---
type: meta
title: "Hot Cache"
updated: 2026-07-06
---

# Recent Context

## Last Updated
2026-07-06. Ingested the satirical post [[wiki/sources/wizard-topples-capitalist-dominance|Wizard Topples Capitalist Dominance Ingeniously]] via `/wiki-ingest` — the **first source ingested that isn't the PRD**, and the first sourced from `_posts/` rather than `.raw/`. It spawned a whole accountability-and-ethics cluster in `wiki/`.

## Key Recent Facts
- The post is a **satire wrapper around a real payload**: a wizard-vs-capitalism fable whose second half ("The Wizard's Workshop") is a hands-on tutorial. The ingest deliberately extracted the real, reusable substance and left the fictional "Merlin Financialis" framing in the source page only (no entity page for the wizard).
- New concepts (6): [[wiki/concepts/radical-transparency|Radical Transparency]] (carries the concrete public-data → ingest → open-ledger → audit-engine → dashboard pipeline + the SEC EDGAR ingest snippet), [[wiki/concepts/algorithmic-accountability|Algorithmic Accountability]] (fairness metrics via Fairlearn), [[wiki/concepts/impact-weighted-accounting|Impact-Weighted Accounting]] (declarative `impact-weights.yml` with negative weights for harm), [[wiki/concepts/ethical-engineering|Ethical Engineering]] (the post's thesis + practitioner checklist), [[wiki/concepts/esg-investing|ESG Investing]], and [[wiki/concepts/stakeholder-capitalism|Stakeholder Capitalism]].
- New entities (5): [[wiki/entities/fairlearn|Fairlearn]], [[wiki/entities/sec-edgar|SEC EDGAR]], [[wiki/entities/gleif|GLEIF]], [[wiki/entities/hbs-impact-weighted-accounts|HBS Impact-Weighted Accounts Project]], [[wiki/entities/b-corp|B Corp]]. These are real-world referents that stand independent of the fable and will be reused by any future ESG/fintech/responsible-AI ingest.
- This cluster is **thematically separate** from the pre-existing wiki (which is all about zer0-pages PRD-vs-reality). No contradictions with existing pages; the only tie-in is that the post is itself an artifact of the [[wiki/entities/zer0-pages|zer0-pages]] content engine.
- Content scope unchanged — docs / posts / notes only, 89 / 38 / 6 ([[_moc/Home]]).

## Recent Changes
- Created `wiki/sources/wizard-topples-capitalist-dominance.md`; 6 concept pages; 5 entity pages (12 new pages total).
- Updated `wiki/index.md`, `wiki/sources/_index.md`, `wiki/concepts/_index.md`, `wiki/entities/_index.md`, this hot cache, and appended `wiki/log.md`.

## Active Threads
- `.raw/` still holds `README.md` un-ingested; drop further sources and say "ingest [filename]".
- `scripts/wiki-lock.sh` remains inoperable here (`flock` missing) — solo passes only; no addresses (DragonScale off in this vault).
- Next `/wiki-lint` should confirm the new cluster's wikilinks resolve and that the source's backlink to [[_posts/2024-06-17-wizard-topples-capitalist-dominance-ingeniously|the published post]] renders in the graph.
