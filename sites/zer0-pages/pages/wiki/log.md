---
type: meta
title: "Log"
updated: 2026-07-06
---

# Log

Append-only. Newest entries on top.

## 2026-07-06 — PR-prep cleanup: contract fixes + second-brain framing
- Ran a 4-dimension audit (contract compliance, wiki integrity, repo hygiene, second-brain-for-zer0-mistakes alignment) before opening the first PR from this branch to `main`. Repo hygiene came back fully clean (0 findings). Full results: contract-compliance 3 findings, wiki-integrity 1 finding, second-brain-alignment 4 findings.
- **Fixed** `pages/index.md` (added missing `description`, `permalink: /`, `aliases: [/]`) and `pages/posts.md` (added `permalink: /posts/`, `aliases: [/posts/]` — confirmed `/posts/` is the URL `_data/navigation/home.yml` and `main.yml` already expect, so this was a latent nav mismatch, not just a style gap).
- **Clarified, did not backfill**, the `_posts/` collection: 31 of 38 post files lack explicit `permalink`/`aliases` (only the 7 category-index pages have them). Confirmed via `_config.yml` that `_posts` is Jekyll's native collection (no custom `collections:` entry, governed by sitewide `permalink: pretty`), so this is by-design, not a defect. Added one clarifying sentence to root `CLAUDE.md`'s Dual-compatibility rules instead of mass-editing 31 files.
- **Fixed** 3 orphan wiki pages (`wiki/sources/_index.md`, `wiki/concepts/_index.md`, `wiki/entities/_index.md` had zero inbound wikilinks) by turning their backtick-quoted mentions in `wiki/index.md` into real `[[wikilinks]]`.
- **Established second-brain-for-zer0-mistakes framing**, per the repo owner's explicit statement of that goal this session: created [[wiki/entities/zer0-mistakes|zer0-mistakes]] (the first entity page for the upstream theme repo itself — previously absent despite being central to the whole architecture), added a "second brain" purpose paragraph to `README.md` and `wiki/overview.md`, and cross-linked it from [[wiki/entities/zer0-pages|zer0-pages]]. Documented, on the new page itself, that the relationship is **declared but not yet built out**: no zer0-mistakes-internals knowledge has been ingested into this vault yet, only the existing surface-level `_docs/development/` consumer docs which explicitly defer to the zer0-mistakes repo's own `docs/` directory.
- **Added a caveat** to `README.md`'s PRD.md link and a status-note callout at the top of `PRD.md` itself, both flagging it as an aspirational Django+React+PostgreSQL vision that predates and doesn't match the shipped vault+bridge system — closing the gap where that awareness existed only in the wiki (`wiki/sources/zer0-pages-prd.md`), not in the documents themselves.
- Verified: unit tests 93/93 passing (`test_obsidian_bridge.rb` 74, `test_graph_index.rb` 19); full local `bundle exec jekyll build` not possible in this sandbox (system Ruby 2.6.10, theme requires >=3.2 — matches documented CI-only build capability, not a new gap).
- Deferred (flagged, not actioned): actually ingesting zer0-mistakes' own `docs/` directory (architecture, release-automation internals) into this wiki — a real content-authoring project, out of scope for a cleanup pass. Left as an active thread below.

## 2026-07-06 — Ingested "Wizard Topples Capitalist Dominance"
- Ingested `pages/_posts/2024-06-17-wizard-topples-capitalist-dominance-ingeniously.md` (satirical draft post, dated 2024-06-17) via `/wiki-ingest`. First non-PRD source, and first ingested from `_posts/` rather than `.raw/`.
- Created source [[wiki/sources/wizard-topples-capitalist-dominance|Wizard Topples Capitalist Dominance Ingeniously]].
- Created concepts [[wiki/concepts/radical-transparency|Radical Transparency]], [[wiki/concepts/algorithmic-accountability|Algorithmic Accountability]], [[wiki/concepts/impact-weighted-accounting|Impact-Weighted Accounting]], [[wiki/concepts/ethical-engineering|Ethical Engineering]], [[wiki/concepts/esg-investing|ESG Investing]], [[wiki/concepts/stakeholder-capitalism|Stakeholder Capitalism]].
- Created entities [[wiki/entities/fairlearn|Fairlearn]], [[wiki/entities/sec-edgar|SEC EDGAR]], [[wiki/entities/gleif|GLEIF]], [[wiki/entities/hbs-impact-weighted-accounts|HBS Impact-Weighted Accounts Project]], [[wiki/entities/b-corp|B Corp]].
- Updated `wiki/index.md`, `wiki/sources/_index.md`, `wiki/concepts/_index.md`, `wiki/entities/_index.md`, `wiki/hot.md`.
- Editorial calls: kept the fictional wizard "Merlin Financialis" inside the source page (no entity); folded AIF360, OpenCorporates, dbt/Postgres/Parquet, ACM/IEEE, and EPIC into concept prose rather than spawning thin pages; merged the "transparency pipeline" architecture into the Radical Transparency concept.
- Key insight: the satire is a wrapper — the extractable substance is a concrete, swappable accountability pipeline (public data → open ledger → audit engine → dashboard) plus real tools (EDGAR/Fairlearn/impact-weights.yml) and frameworks (ESG/B-Corp/HBS IWA); this cluster is thematically independent of the existing PRD-vs-reality wiki, with no contradictions.
- No addresses assigned (DragonScale off — no `./scripts/allocate-address.sh` at CWD, `.vault-meta/` has only the lock-meta stub); solo pass, no wiki-lock (`flock` unavailable).

## 2026-07-05 — Authored engine-showcase content
- Created post [[_posts/development/2026-07-05-inside-the-zer0-pages-engine|Inside the zer0-pages Engine: Obsidian In, GitHub Pages Out]] — end-to-end walkthrough of the pipeline: claude-obsidian skills author into the vault → `_plugins/` bridge converts wikilinks/Dataview/callouts → `jekyll-theme-zer0` themes → Actions deploys to Pages. Wikilinked to the four ingested concept pages, both entity pages, the PRD source page, and [[_docs/obsidian/graph|the graph view]].
- Created note [[_notes/claude-obsidian-cheatsheet|claude-obsidian Cheatsheet]] — quick reference covering the skills (`/wiki-ingest`, `/wiki-query`, `/save`, `/wiki-lint`, `/autoresearch`), dual-compatibility rules, folder layout, and the publish flow. Wikilinked to [[wiki/index|the wiki index]], [[wiki/meta/conventions|conventions]], and the ingested wiki pages.
- Updated `wiki/index.md` (collection counts 38 posts / 6 notes + showcase links), this log, and `wiki/hot.md`.
- First published content authored *about* the engine *by* the engine — both pieces double as backlink anchors pulling the `wiki/` layer into the site graph.

## 2026-07-05 — Ingested zer0-pages PRD
- Ingested `pages/.raw/zer0-pages-prd.md` (v1.0.0, dated 2025-12-01) via `/wiki-ingest`.
- Created source [[wiki/sources/zer0-pages-prd|zer0-pages PRD]].
- Created entities [[wiki/entities/zer0-pages|zer0-pages]] and [[wiki/entities/claude-obsidian|claude-obsidian]].
- Created concepts [[wiki/concepts/ai-content-engine|AI Content Engine]], [[wiki/concepts/jekyll-obsidian-dual-rendering|Jekyll/Obsidian Dual-Rendering Architecture]], [[wiki/concepts/github-pages-deployment|GitHub Pages Deployment Model]], [[wiki/concepts/prd-machine|PRD Machine]].
- Updated `wiki/index.md`, `wiki/entities/_index.md`, `wiki/concepts/_index.md`, `wiki/sources/_index.md`.
- Flagged a `[!contradiction]` in the source page and cross-referenced it from both entity pages: the PRD describes a Django+React+PostgreSQL+Redis "shipped" product; this repo has none of that — the real system is `claude-obsidian` authoring an Obsidian vault that Jekyll bridge plugins publish to GitHub Pages. Every PRD "✅ Shipped" marker should be read as marketing copy, not verified status.
- `bash claude-obsidian/scripts/wiki-lock.sh` was tested but is inoperable on this machine (`flock: command not found`); pages were written directly since this was a solo ingestion pass, not a parallel batch.

## 2026-07-05 — Slim-down to docs / posts / notes
- Narrowed the vault to three content collections (`_docs/`, `_posts/`, `_notes/`) per project directive; everything else removed (committed history keeps it recoverable).
- Deleted collections: `_quests/` (3), `_quickstart/` (5), `_about/` (~30), `_notebooks/` (10 incl. `.ipynb`).
- Deleted MOCs: `_moc/Quests`, `_moc/Quickstart`, `_moc/About`, `_moc/Notebooks`.
- Deleted 13 loose root pages: quests, notebooks, contact, faq, features, glossary, hobbies, privacy-policy, roadmap, services, setup, sitemap, terms-of-service.
- Swept kept content for dead references: trimmed [[_moc/Home]] collections/find-your-way lists, fixed Dataview `FROM` clauses in `tags`/`categories`, retargeted or dropped wikilinks and prose mentions across `_docs/` and `_notes/`, updated [[wiki/index|wiki index]], [[overview]], [[hot]], and `wiki/meta/conventions`.
- Rationale: focus the site + graph on the docs/posts/notes knowledge base ahead of enabling the Obsidian graph UI and the claude-obsidian content engine.

## 2026-07-05 — Vault conversion
- Converted `pages/` (zer0-mistakes Jekyll content) into an Obsidian vault with claude-obsidian.
- Backed up pristine Jekyll tree to `../.backups/pages-jekyll-20260705-200505/` (197 files).
- Rewrote 302 permalink links → wikilinks across 173 notes (fence-aware; assets/external links left intact).
- Rewrote 241 pre-existing bare concept links (`[[Jekyll]]`…) → path-qualified via a title map.
- Augmented frontmatter on 173 notes with `type` + `aliases`.
- Re-authored 18 dynamic Liquid listing pages as Dataview pages; converted 3 `.html` → `.md`.
- Cleaned unfenced Liquid from 24 pages (`{% raw %}`, `{% include %}` widgets, `{{ site.* }}`).
- Built 7 MOCs (`_moc/Home` + one per collection).
- Scaffolded `.obsidian/`, `.raw/`, `wiki/`, `_moc/`, `_templates/`.
- Final lint: 662 wikilinks, 4 intentional unresolved (template placeholders + 2 future-page stubs), 0 stray Liquid, 0 `.html`.
