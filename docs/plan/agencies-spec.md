# The agencies: five content sites that moved to lifehacker.dev, and what the platform still owes them

> What five content sites — 1987, 2005, drsai, irony-works and wargames — did here before they moved to lifehacker.dev's `agencies/` (ADR 0012): where each lives now and, per ledger row, what it did, where the platform is and what it owes.

The owner moved the five trees out of this repository on 2026-11-22 ([ADR 0012](../adr/0012-content-lives-in-lifehacker.md)): lifehacker.dev is the content source, and zer0-CMS is the platform that imports, round-trips, renders and manages what it holds. Each row section below is a row of [`capabilities.yml`](capabilities.yml) with status `specified`: its source is no longer in this repository, what it did here is written down, and its platform target still owes it. The milestone that builds one sets the row `done` with a test as its proof and removes the section.

## Where each source lives

Every tree was exported whole from this repository at commit `9b68af57` — content, site configuration and the site's own tooling — into `bamr87/lifehacker.dev`, under `agencies/`. That repository's registry, `_data/agencies.yml`, is the record of the import: per tree, the source commit, the file count, a digest, and anything its own rules made the import change. This file does not repeat it.

| Source (ledger) | Was here | Lives in `bamr87/lifehacker.dev` at | Files at `9b68af57` | What it is |
|---|---|---|---|---|
| `site-1987` | `sites/1987` | `agencies/1987` | 73 | A self-growing knowledge base about the year 1987: plain-Markdown topic pages in five categories, with the growth framework that writes them. No Jekyll configuration. |
| `site-2005` | `sites/2005` | `agencies/year-of-ai/2005` | 155 | The year-2005 knowledge base of the year-of-ai lineage: 80 posts in five categories on the zer0 theme, their preview images, and the growth ledger. |
| `site-drsai` | `sites/drsai` | `agencies/drsai` | 109 | The children's picture-book site: a `books` collection (a story book and an ABC book), the Python story engine `drsai/`, and the import and illustration tools. |
| `site-irony-works` | `sites/irony-works` | `agencies/irony-works` | 140 | The encyclopedia of irony and paradox: an Obsidian vault (62 Markdown files), the Node germination engine that grows it, and a thin layer over the zer0 theme. |
| `site-wargames` | `sites/wargames` | `agencies/wargames` | 269 | The OverTheWire wargames mirrored as a study site (219 challenge pages with spoiler-free study guides), and the aggregator that re-syncs it from upstream. |

Reading the sections: a path is relative to the site's tree, so `tools/import_abc_book.py` under drsai is `git show 9b68af57:sites/drsai/tools/import_abc_book.py` here and `agencies/drsai/tools/import_abc_book.py` in lifehacker.dev. **Did** is what the source did in this repository until ADR 0012; every test named under **Platform today** was found by name when this was written; the tests under **Owed** are to be written.

| Row | Platform target | Where it gets built |
|---|---|---|
| [`site-1987.content`](#site-1987content) | `content.import` | an importer for a plain-Markdown tree (G4's open items) |
| [`site-1987.publish`](#site-1987publish) | `sites.render` | P6, then P7 for the site, once the owner decides where the agencies publish |
| [`site-1987.grow`](#site-1987grow) | `sites.evolve` | G13 |
| [`site-2005.content`](#site-2005content) | `content.import` | G4's open items |
| [`site-2005.publish`](#site-2005publish) | `sites.render-jekyll` | P2's option over an external checkout, or P7 |
| [`site-drsai.content`](#site-drsaicontent) | `content.import` | G4's open items |
| [`site-drsai.publish`](#site-drsaipublish) | `sites.render-jekyll` | P2's option over an external checkout, or P7 |
| [`site-drsai.story-engine`](#site-drsaistory-engine) | `ai.briefs` | G9 |
| [`site-drsai.abc-import`](#site-drsaiabc-import) | `books.abc` | G9 |
| [`site-irony-works.content`](#site-irony-workscontent) | `content.import` | G4's open items |
| [`site-irony-works.publish`](#site-irony-workspublish) | `sites.render-jekyll` | P2's option over an external checkout, or P7 |
| [`site-irony-works.wikilinks`](#site-irony-workswikilinks) | `sites.obsidian` | P2's option (a `before:` step for an external site), or P6's renderer plugins |
| [`site-wargames.content`](#site-wargamescontent) | `content.import` | G4's open items |
| [`site-wargames.publish`](#site-wargamespublish) | `sites.render-jekyll` | P2's option over an external checkout, or P7 |

## How the platform reaches an agency today

The platform treats an agency as it treats any external site repository: a checkout under `SITES_DIR` ([`content/sites/README.md`](../../content/sites/README.md)).

- **Register by path.** `POST /api/v2/sites/` (and the studio's Sites area) takes a checkout at any depth under `SITES_DIR`, so `…/lifehacker.dev/agencies/drsai` and `…/lifehacker.dev/agencies/year-of-ai/2005` both register, under the keys `drsai` and `2005` (`content/sites/services.py`, `resolve_checkout` and `register`). A registered site syncs, writes back under the stale-write guard and runs the doctor as jobs (G4).
- **Discover.** `GET /api/v2/sites/discover/` lists the Jekyll roots one or two levels under `SITES_DIR` (`services.discover`). With `SITES_DIR` set to lifehacker.dev's `agencies/` directory it finds all four Jekyll trees. With `SITES_DIR` set to the lifehacker.dev checkout it finds `agencies/drsai`, `agencies/irony-works` and `agencies/wargames` and misses `agencies/year-of-ai/2005`, three levels down. With `SITES_DIR` set to a directory of repositories (`SITES_DIR=~/github`, the fleet layout) it finds none of them.
- **1987 cannot be registered.** It has no `_config.yml`, and a checkout must be a Jekyll root.
- **Rendering and deploying are not reachable.** The Jekyll-theme option builds a project that `workspace.yml` names, from the files this repository's git tracks ([`tools/jekyll_theme.py`](../../tools/jekyll_theme.py)); an external checkout is neither.
- **The tests read the agencies directory.** `ZER0_AGENCIES_DIR`, else a sibling checkout `../lifehacker.dev/agencies` ([`content/tests/agencies.py`](../../content/tests/agencies.py)); `content.yml` checks it out of `bamr87/lifehacker.dev`. A tree that is absent skips its cases and names the variable.

## The recorded builds

`web/site/fixtures/{2005,drsai,irony-works,wargames}/manifest.json` are the recordings of what each site's Jekyll build wrote, made in PLAN P1 while each still built with its own Gemfile (irony-works re-recorded on 2026-10-27) and reproduced exactly by the Jekyll-theme option in P2: every output path, each page's title and text, the feed entries, the sitemap URLs and the redirects ([`web/site/fixtures/README.md`](../../web/site/fixtures/README.md)). They stay in this repository, unedited. Nothing here rebuilds those sites any more, so nothing compares against them: `tools/site_manifest.py --check` rebuilds only the sites `workspace.yml` still names. They travel as the parity record: whoever publishes one of these sites next — from lifehacker.dev, through the option or the React renderer — reproduces its recording (`python3 tools/site_manifest.py compare [--pages] web/site/fixtures/<site>/manifest.json <candidate>`), or re-records it and says why. 1987 has no recording: it never had a build.

## site-1987

**Lives at** `bamr87/lifehacker.dev` `agencies/1987`. The tree holds the topic pages (`arts-culture/`, `history-politics/`, `people/`, `science-technology/`, `society-economics/`, each with a generated `index.md`), `seed.md` (the concept definition every command reads), `ROADMAP.md`, `TIMELINE.md`, `index.md`, and the growth framework twice over: Claude Code's (`.claude/commands/` — `grow`, `genesis`, `evolve`, `deep-dive`, `encode-seed`, `publish`, `update-readme`; `.claude/agents/` — the Architect and the Curator; `.claude/skills/` — `research`, `add-topic`, `build-structure`, `plan-roadmap`, `sync-seed`, `publish-session`) and Copilot's copy of the same under `.github/`.

Its `workspace.yml` entry at `9b68af57`, deleted with the tree:

```yaml
"1987":
  path: sites/1987
  kind: site
  stack: [python]
  summary: The self-growing knowledge base about the year 1987 — plain-markdown topic pages by category, grown by Claude Code slash commands and published by GitHub Pages from the original repository.
  upstream: bamr87/1987
  publishes: [pages]
  route: none — a plain-markdown repository with no Jekyll config of its own; its GitHub Pages site went with the deleted bamr87/1987, and it gets a route once it has a _config.yml
  ci: ci.yml
  tasks:
    check: python3 ../../tools/unwrap-prose.py --check --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$' . || true
```

### site-1987.content

**Did.** Nothing imported it. The tree is Markdown by category, each topic page with a small front matter (`title`, `date`, `category`), and it has no `_config.yml`.

**Platform today.** The Jekyll importer refuses the tree: `roundtrip_jekyll --path <tree>` ends with "has no _config.yml — not a Jekyll site" (run against the tree for this spec). The ledger held the row `partial`, and no test has read this site.

**Owed.**

- Decide the site's shape first (the owner's): give it a `_config.yml`, as its route note asked, and it is a Jekyll site like the others; or teach the importer a plain-Markdown tree.
- Then the round trip: `content/tests/importers/test_jekyll.py::test_the_real_sites_round_trip_byte_for_byte[agencies/1987]`, and the generated regions (`<!-- BEGIN GENERATED: … -->`) written back byte for byte.

### site-1987.publish

**Did.** Nothing: no build, no route and no recording. Its GitHub Pages site was served from `bamr87/1987`, which no longer exists.

**Platform today.** `sites.render` (the React renderer) is not built (P6).

**Owed.** A first build is its first recording (`web/site/fixtures/README.md`); it has no URLs to keep, since no site answers today.

### site-1987.grow

**Did.** The knowledge base grows by one tick of `/grow`: the Architect agent orients, calls `plan-roadmap` for one to three items, sends content items to the Curator (which researches with the `research` skill and writes with `add-topic`), structure items to `build-structure`, then runs `sync-seed`, `encode-seed` and `publish-session`, the one gate that pushes. Nothing in the framework names 1987: it reads `seed.md`. These are prompts a person runs in Claude Code or Copilot, not code this repository executed.

**Platform today.** `sites.evolve` is `missing` on every surface. The pieces it will be built from exist: research sources and cited answers (`content/research/`), ideas and their promotion to briefs (`content/ideas/`), briefs and pipelines (`content/ai/`), and suggestions a person accepts.

**Owed.** G13's improvement loop, able to do for a site what a tick does: read a site's editorial plan (its seed and roadmap), research a topic, propose a new page and the index and cross-reference updates as suggestions, and record the tick. Until then the commands run where the tree lives.

## site-2005

**Lives at** `bamr87/lifehacker.dev` `agencies/year-of-ai/2005`. The tree holds `_config.yml` (a `remote_theme` consumer; `url` `https://year-of-ai.github.io`, `baseurl` `/2005`), `_posts/<category>/` (80 posts), `_data/navigation/`, `assets/images/previews/` (37 images), `index.html`, `news.md`, `TIMELINE.md`, `telemetry/` (the append-only growth ledger) and a legacy `.claude/` its own guide marks for removal. The archived `year-of-ai/2005` still serves the site it last built, at <https://year-of-ai.github.io/2005/>.

Its `workspace.yml` entry at `9b68af57`:

```yaml
"2005":
  path: sites/2005
  kind: site
  stack: [jekyll, docker]
  summary: The year-2005 knowledge base of the year-of-ai lineage — a site on the zer0 theme, built the way zer0-pages-remote is.
  upstream: year-of-ai/2005
  publishes: [pages]
  route: none — published by year-of-ai.github.io at /2005/, which builds it from this repository (ADR 0002 §4)
  ci: sites.yml
  site: .
  render: {as: jekyll-theme, theme: v1.31.3, server: github-pages}
  tasks:
    build: python3 ../../tools/jekyll_theme.py build 2005
```

### site-2005.content

**Did.** The importer read the tree and the exporter wrote it back unchanged, in the slow tier of `content.yml`.

**Platform today.** The same test, reading the agency: `content/tests/importers/test_jekyll.py::test_the_real_sites_round_trip_byte_for_byte[agencies/year-of-ai/2005]`; its bodies' structured blocks in `content/tests/importers/test_blocks.py::test_on_the_real_sites_each_cut_is_its_own_text_and_changes_nothing_the_body_writes[agencies/year-of-ai/2005]`; its URLs as the Ruby lane computed them in `content/tests/distribution/test_lane.py::test_every_site_gets_the_urls_the_ruby_lane_gave_it[2005]`. Each skips where the tree is absent.

**Owed.** What every content row here still owes (ADR 0006 decision 13): the site registered and synced in a running platform, its files then generated from the database by the write-back job and committed by a job — into lifehacker.dev's checkout now — and a hand edit there arriving as a suggestion. Discovery two levels down does not reach it from a lifehacker.dev checkout (above).

### site-2005.publish

**Did.** `sites.yml` built it through the Jekyll-theme option (`bin/zer0 run build 2005`: the theme at `v1.31.3`, GitHub Pages' own builder, its own `url` and `baseurl`) and failed a pull request whose build differed from `web/site/fixtures/2005/manifest.json` (464 paths, 84 pages, 10 feed entries, 79 sitemap URLs). Nothing here deployed it: no route.

**Platform today.** The option cannot build an external checkout (above). A registered site's renderer, theme tag and server are registry fields (G4), but its build does not run as a job.

**Owed.**

- The option over an external checkout: `tools/jekyll_theme.py` taking a site's root and `render:` setting from the registry rather than `workspace.yml`, exporting the files its repository tracks.
- The build as a job a person follows, compared with the recording.
- Where it deploys: the owner's decision (ADR 0012). Its URLs are the recording's.

## site-drsai

**Lives at** `bamr87/lifehacker.dev` `agencies/drsai`. The tree holds the site (`_config.yml`, `index.html`, `pages/_books/dodge-and-reena/` — a story of twelve monthly chapters and its index — and `pages/_books/it-alphabet/`, `_data/abc_books/it-alphabet.json`, `_data/series.yml`, 27 story images), the story engine (`drsai/`: a Python package, `drsai` 0.1.0, with its tests and PyPI packaging), the tools (`tools/import_abc_book.py`, `tools/import_dodge_and_reena.py`, `tools/generate_illustrations.py`), reference copies of its original workflows (`.github/workflows/ci.yml`, `pages.yml`) and its planning documents at the root.

Its `workspace.yml` entry at `9b68af57`:

```yaml
drsai:
  path: sites/drsai
  kind: site
  stack: [jekyll, docker, python]
  summary: The children's picture-book site and its Python story engine; the CMS's ABC wizard exports into it.
  upstream: bamr87/drsai
  publishes: [pages, "pypi:drsai"]
  ci: drsai.yml
  site: "."
  route: /drsai/
  render: {as: jekyll-theme, theme: v1.31.3, server: github-pages}
  tasks:
    setup: cd drsai && pip install -e ".[dev]"
    check: python3 tools/import_abc_book.py --check
    test:
      run: (cd drsai && pytest tests/ -q) && python3 tools/import_abc_book.py --check
    build: python3 ../../tools/jekyll_theme.py build drsai
    pages: python3 ../../tools/jekyll_theme.py build drsai
```

`tools/import_dodge_and_reena.py` defaults to a sibling `../Dodge-and-Reena-Book` checkout, which was never imported; pass `--source`. `drsai.yml`, deleted with the entry, ran three jobs: the story engine's `ruff check src/`, `black --check src/ tests/` and `pytest tests/ -q` on Python 3.10, 3.11 and 3.12 (after `nltk.download('cmudict')`); `python3 tools/import_abc_book.py --check` and the one-paragraph-per-line check; and the site's `build` task.

### site-drsai.content

**Did.** The importer read the tree — its books as `BookPage`s, the ABC book with one `letter` block per plate and its spec sidecar — and the exporter wrote it back unchanged, in the fast tier.

**Platform today.** `content/tests/importers/test_jekyll.py::test_the_real_sites_round_trip_byte_for_byte[agencies/drsai]`, `content/tests/importers/test_blocks.py::test_on_the_real_sites_each_cut_is_its_own_text_and_changes_nothing_the_body_writes[agencies/drsai]` and `content/tests/distribution/test_lane.py::test_every_site_gets_the_urls_the_ruby_lane_gave_it[drsai]`, each reading the agency and skipping where it is absent. Its books stay that site's pages: the Books workspace does not hold them (`content/tests/books/test_api.py`, "drsai's picture books and ABC books stay their site's pages until they are book types").

**Owed.** As [site-2005.content](#site-2005content); and its books as book types (G9), below.

### site-drsai.publish

**Did.** `pages.yml` built it at `/drsai/` through the option (the theme at `v1.31.3`, GitHub Pages' own builder) and failed a pull request whose build differed from `web/site/fixtures/drsai/manifest.json` (383 paths, 16 pages, 16 sitemap URLs); `drsai.yml` built it too. The deploy was never switched on (`PAGES_DEPLOY_ENABLED`), so `/drsai/` was built and checked, not served.

**Platform today, owed.** As [site-2005.publish](#site-2005publish). No site answers for it today: `bamr87/drsai` no longer exists.

### site-drsai.story-engine

**Did.** `drsai/` is a command-line generator of rhyming verse in the manner of Dr. Seuss: `drsai generate` (`src/drsai/commands/generate.py`) builds a prompt (`core/prompt_builder.py`), calls a model (`core/llm_client.py`: OpenAI or Anthropic), and checks the result — rhyme (`validation/rhyme_checker.py`), scansion (`validation/scansion.py`) and quality (`validation/quality_checker.py`) — over the schemas in `models/schemas.py`. Its tests are unit, integration and end to end (`drsai/tests/`). This repository ran its lint and tests in `drsai.yml` and never published it to PyPI: the original's tag-triggered publish job was not ported (the plan was a prefixed tag, `drsai-v*`).

**Platform today.** The drafter's `story` profile exists (`content/agents/definitions/drafter.yaml`), and briefs turn a prompt into a structured draft (`ai.briefs`, done on the API, the studio and the extension). Nothing in the platform checks rhyme or metre.

**Owed** (G9, ADR 0006 decision 14: "the ABC wizard and drsai's story engine become book types and generators").

- A story book type whose generator is an assistant or pipeline, its result a suggestion the author accepts.
- The engine's checks as a gate on that result: rhyme scheme, scansion and the quality rules, re-expressed from `validation/` with its unit tests' cases (`drsai/tests/unit/`).
- Tests on recorded fixtures: a generated stanza that fails the rhyme check is refused with the line that broke it.

### site-drsai.abc-import

**Did.** `tools/import_abc_book.py --check` holds every ABC book's page (`pages/_books/<slug>/index.md`, layout `book-abc`) to its spec sidecar (`_data/abc_books/<slug>.json`): each letter's word, tagline, image and prompt, and the book's series, art style and cover, by meaning rather than bytes. It ran in `drsai.yml` and as the project's `check` task. The deleted Rails wizard wrote both files ([`rails-cms-spec.md`](rails-cms-spec.md#railsabc-generator)); `tools/generate_illustrations.py` draws a plate whose image is missing.

**Platform today.** The platform reads the sidecar with the page and writes both back; an edited letter exports a plate planned for it and a sidecar that agrees, and drsai's own tool accepts the export: `content/tests/books/test_abc.py` (`test_an_edited_word_exports_a_plate_planned_for_it_and_a_sidecar_that_agrees`, `test_an_edited_subject_recomposes_the_prompt_and_the_sidecar_keeps_it`, `test_the_write_back_writes_records_and_keeps_the_sidecar_with_its_page`). The tool is the tests' oracle, read from `agencies/drsai/tools/import_abc_book.py`; where the agency is absent each of those tests skips at the point it would have run the tool. The golden book stays here, frozen from `d0a572fb`, in `content/tests/fixtures/abc/`.

**Owed** (G9, with [`rails.abc-generator`](rails-cms-spec.md#railsabc-generator)). The check itself in the platform — a book's page validated against its spec before an export, in Python beside `content/books/abc.py` — so the export is proven without a tool from another repository, and the oracle test becomes a comparison of two implementations rather than the only proof.

## site-irony-works

**Lives at** `bamr87/lifehacker.dev` `agencies/irony-works`. The tree holds the vault (`vault/`: 62 Markdown files — the notes in `forms/`, `works/`, `figures/`, `instances/`, `paradoxes/`, `mirrors/`, `futures/` and `nursery/`, the two `compost/` ledgers, the `templates/` and three notes at its root), the engine (`engine/seed.config.yml`, `engine/prompts/` — five irony prompts and three paradox prompts — and `engine/scripts/`: `germinate.mjs`, `gate.mjs`, `transplant.mjs`, `preview.mjs`, `usage-ledger.mjs`, `make-favicon.mjs`, `lib.mjs`), the theme layer (`_layouts/section.html`, four `_includes/`, `.theme-overrides.yml`), the branch pages at the root, `zer0.json`, and reference copies of its workflows (`.github/workflows/publish.yml`, `alanis-gate.yml`, `germinate.yml`).

Its `workspace.yml` entry at `9b68af57`:

```yaml
irony-works:
  path: sites/irony-works
  kind: site
  stack: [node, jekyll, docker]
  summary: The perpetual encyclopedia of irony — a self-growing, AI-tended Obsidian vault whose engine transplants entries into a Jekyll collection published with the zer0 theme.
  upstream: bamr87/irony-works
  publishes: [pages]
  route: none — bamr87/irony-works still deploys it; it builds here with the Jekyll-theme option after its node transplant step, and routes at /irony-works/ once its deploy moves here (C4)
  ci: irony-works.yml
  site: "."
  # Its build publishes node_modules/ (its exclude: replaces Jekyll 3's defaults; PLAN P1),
  # so js-yaml and argparse are pinned at the versions its recording holds.
  render: {as: jekyll-theme, theme: v1.31.3, server: github-pages, before: npm i js-yaml@5.5.0 argparse@3.0.3 --no-save && node engine/scripts/preview.mjs && node engine/scripts/transplant.mjs}
  tasks:
    setup: npm i js-yaml --no-save
    check: for f in engine/scripts/*.mjs; do node --check "$f" || exit 1; done
    build: python3 ../../tools/jekyll_theme.py build irony-works --repository bamr87/irony-works
```

Never ported here, and still only reference copies in the tree: the scheduled Germinate loop (scout, gate, scribe into `vault/nursery/`, a nursery pull request a person merges) and the advisory Alanis Gate on vault pull requests. Whoever hosts Germinate gives it its own `*_ENABLED` kill switch, off by default, so the loop never runs in two places.

### site-irony-works.content

**Did.** The importer read the Jekyll source as it is tracked — the pages at the root, 13 by the lane's recording — and the exporter wrote it back unchanged, in the fast tier. `_config.yml` excludes `vault/` and `engine/`, and the `_entries/` collection exists only in a build, after the transplant.

**Platform today.** `content/tests/importers/test_jekyll.py::test_the_real_sites_round_trip_byte_for_byte[agencies/irony-works]`, `content/tests/importers/test_blocks.py::test_on_the_real_sites_each_cut_is_its_own_text_and_changes_nothing_the_body_writes[agencies/irony-works]` and `content/tests/distribution/test_lane.py::test_every_site_gets_the_urls_the_ruby_lane_gave_it[irony-works]`. The vault — what people and the engine write — is not what the platform reads.

**Owed.** As [site-2005.content](#site-2005content); and the vault itself as content: an importer over `vault/` (`content.import` names Obsidian sites), with the round trip held on its notes.

### site-irony-works.publish

**Did.** `irony-works.yml` built it through the option — the `before:` step above on the exported tree (install js-yaml 5.5.0 and argparse 3.0.3, render the previews, transplant the vault into `_entries/`), then GitHub Pages' own builder with `--repository bamr87/irony-works` — and failed a pull request whose build differed from `web/site/fixtures/irony-works/manifest.json` (496 paths, 72 pages, 71 sitemap URLs; its published `node_modules/` included, as recorded). Nothing here deployed it.

**Platform today, owed.** As [site-2005.publish](#site-2005publish), and the option's `before:` step for an external site. No site answers for it today: `bamr87/irony-works` no longer exists.

### site-irony-works.wikilinks

**Did.** `engine/scripts/transplant.mjs` resolves every `[[wikilink]]` before Jekyll runs: it indexes each note's `title:`, matches a link case-insensitively by title or filename slug, rewrites it to a `/entries/<slug>/` permalink (or to plain text, reported as a dead link), and stops on a note whose front matter is not valid YAML. It ran here as the option's `before:` step.

**Platform today.** `sites.obsidian` is `done` for operations on zer0-pages's bridge, ported to Python (`tools/obsidian/`, `tools/tests/test_obsidian_bridge.py::WikilinksTest`), which resolves wikilinks by its own rules, not the transplant's. The React renderer's plugins are P6's.

**Owed.** One resolver for both vaults: the transplant's rules (title or slug, case-insensitive, a dead link reported and written as text) as cases of `tools/obsidian`'s, proven on this vault — every link in the vault resolving to the permalink the recording holds — so the site builds with `obsidian: true` and no Node step.

## site-wargames

**Since 2026-11-23 it is no longer a site of its own.** lifehacker.dev published Wargames as a collection of its own site (its ADR 0003, `docs/adr/0003-agencies-as-collections.md` there): the 219 pages moved from `agencies/wargames/overthewire/` to `pages/_wargames/` and are served under `/wargames/…` of that site, their pinned permalinks rewritten from `/docs/wargames/…` and their byline key from `bamr87` to `amr`; the 21 images moved to `assets/images/wargames/`. `agencies/wargames` is now the agency's back office — the old site configuration, `index.md`, `tags.md`, `search.json`, the guides, the aggregator and `tools/carry-study-guides.py` — with no pages in it. The platform reaches the pages as part of the lifehacker.dev site, not as a site it registers by this tree. What follows describes the tree as it moved here on 2026-11-22.

**Lives at** `bamr87/lifehacker.dev` `agencies/wargames`. The tree holds the site (`_config.yml`, `index.md`, `tags.md`, `search.json`, `overthewire/<game>/` — 219 pages across Bandit, Natas, Leviathan, Krypton, Narnia, Behemoth, Utumno, Maze, Vortex, Semtex, Manpage, Drifter, FormulaOne and more — `_data/`, 21 images, `assets/css/user-overrides.css`), the aggregator (`scripts/docs-aggregator/`: `aggregate_docs.sh`, `aggregate.py`, `transform.py`, `docs_config.yml`), `tools/carry-study-guides.py`, and a reference copy of its original workflow (`.github/workflows/jekyll-gh-pages.yml`).

Its `workspace.yml` entry at `9b68af57`:

```yaml
wargames:
  path: sites/wargames
  kind: site
  stack: [jekyll, docker, python]
  summary: OverTheWire security wargames (Bandit, Natas and more) mirrored as a Jekyll study site with spoiler-free study guides — a site on the zer0 theme.
  upstream: bamr87/wargames
  publishes: [pages]
  ci: sites.yml
  site: "."
  route: /wargames/
  render: {as: jekyll-theme, theme: v1.31.3, server: jekyll-4}
  tasks:
    check: python3 ../../tools/unwrap-prose.py --check --exclude '(^|/)SCHEMA\.md$' --exclude '(^|/)CHANGELOG\.md$' .
    build: python3 ../../tools/jekyll_theme.py build wargames
    pages: python3 ../../tools/jekyll_theme.py build wargames
```

A re-sync from upstream is a person's procedure, not a job: run the aggregator, unwrap the fresh text to one paragraph per line, then `tools/carry-study-guides.py` to restore each page's study guide and site-owned front matter (its `README.md`).

### site-wargames.content

**Did.** The importer read the tree — bodies that are mostly HTML blocks and tables — and the exporter wrote it back unchanged, in the slow tier.

**Platform today.** Nothing in this suite reads Wargames any more. Its round-trip and block cases left `test_jekyll.py` and `test_blocks.py` when the pages left the tree, and `content/tests/distribution/test_lane.py::test_every_site_gets_the_urls_the_ruby_lane_gave_it[wargames]` skips with the reason (`content/tests/agencies.py`, `ABSORBED`): the Ruby lane's recording names a site that no longer exists as one. Until 2026-11-23 all three ran against `agencies/wargames`.

**Owed.** As [site-2005.content](#site-2005content). The upstream text of `overthewire/**` is vendored: a platform edit to it would be overwritten by the next re-sync, so the study-guide block and the site-owned front matter are the editable parts. The pages now round-trip, if at all, as part of the lifehacker.dev site, which this suite does not read: whether the platform's corpus should include the content source's own site is open.

### site-wargames.publish

**Did.** `pages.yml` built it at `/wargames/` through the option (the theme at `v1.31.3`, the jekyll-4 server) and failed a pull request whose build differed from `web/site/fixtures/wargames/manifest.json` (587 paths, 221 pages, 221 sitemap URLs); `sites.yml` built it too, with its own `url` and `baseurl`. The deploy was never switched on, so `/wargames/` was built and checked, not served.

**Platform today, owed.** Published since 2026-11-23, but not by the platform and not as this row describes: lifehacker.dev serves the pages as a collection of its own site, by its own build, under `/wargames/…` rather than the `/docs/wargames/…` the recording holds, and with no feed of its own. The recording therefore describes a site that no longer exists, and nothing can reproduce it. Whether the row is still owed, in any form, is the owner's to say; it stays `specified` until they do.

## Found while writing this spec

- **Commands in the moved trees point back into this repository.** drsai's and wargames's guides build with `python3 ../../tools/jekyll_theme.py build <name>`, which resolved to this repository's option when the tree was `sites/<name>`; from `agencies/<name>` it resolves to lifehacker.dev's `tools/`, which has no such file. drsai's `_config.yml` describes its preview banners as made by `python3 ../../packages/zer0-image-generator/lib/zer0_image_generator/preview_generator.py`, a path that exists only here. The trees were moved whole and unedited, so these are theirs to correct where they live.
- **No original repository is left to fall back on for four of the five.** On 2026-11-22 the GitHub API answered 404 for `bamr87/1987`, `bamr87/drsai`, `bamr87/irony-works` and `bamr87/wargames`; `year-of-ai/2005` is archived and still serves its last build. [`docs/MONOREPO.md`](../MONOREPO.md) had described three of them as still deploying. Before this change the trees existed in this repository alone; after it, in lifehacker.dev, and here in history at `9b68af57`.
- **This repository's Pages deploy never ran.** It has no Pages site and no `PAGES_DEPLOY_ENABLED` variable (read on 2026-11-22), so `/drsai/` and `/wargames/` were built and compared on every pull request but never served from here.
- **The import is whole, and byte for byte except for reflowed Markdown.** lifehacker.dev holds its Markdown to one paragraph per line, as this repository does, and its import applies that. Its import branch, read on 2026-11-22 before it merged, differed from the trees at `9b68af57` in 21 Markdown files, each in its whitespace alone, and in nothing else — no file missing, none added: 11 in 1987, 5 in wargames (four of them challenge pages), 2 in irony-works, 2 in 2005 and 1 in drsai. Its registry counts them per tree (`reflowed`). The round trips do not depend on it: they hold whatever bytes the agency has. A recorded build might: a reflowed paragraph renders to the same words, which is what a recording compares, but that has not been checked by a build.
- **A skip is not a pass.** Where the agencies directory is absent, the cases above skip. `content.yml` prints which trees it found, and a tree that lifehacker.dev renames will skip until `content/tests/agencies.py` follows it.
