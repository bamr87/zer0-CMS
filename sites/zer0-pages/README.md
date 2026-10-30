# zer0-pages

**Zero friction. Infinite possibilities.**

zer0-pages is an AI-powered knowledge site with a twist: the content is an [Obsidian](https://obsidian.md) vault, the librarian is [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), and the publisher is [Jekyll](https://jekyllrb.com) running in GitHub Actions. You (or Claude, on your behalf) write plain Obsidian-native markdown — wikilinks, callouts, Dataview queries — and a Python "bridge" resolves those constructs to HTML before a plugin-less Jekyll builds the site — zer0-CMS's Jekyll-theme option (`tools/jekyll_theme.py` and `tools/obsidian/` at the repository root; the site's Ruby plugins were retired when it moved, PLAN P-D7). The site's look and feel comes from the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme, fetched as a remote theme at the tag the site's `render:` setting in the root `workspace.yml` pins (`v1.28.0`).

The vault is never polluted with Liquid templating. The published site never requires Obsidian. One body of content, two first-class consumers.

Beyond showcasing the theme, zer0-pages' declared purpose is to act as a **second brain for [zer0-mistakes](https://github.com/bamr87/zer0-mistakes)** — a place where research, decisions, and usage knowledge about the theme accumulate and can feed back into its development, rather than living only in this repo's own showcase content. See [pages/wiki/entities/zer0-mistakes.md](pages/wiki/entities/zer0-mistakes.md) for the current state of that relationship (and an open gap: the deep technical knowledge still lives only in the zer0-mistakes repo itself, not yet ingested here).

## Architecture

```
             AUTHOR                      BUILD                      SERVE
  ┌──────────────────────┐   ┌─────────────────────────┐   ┌──────────────────┐
  │  claude-obsidian     │   │  GitHub Actions          │   │  GitHub Pages    │
  │  skills (engine)     │   │                          │   │                  │
  │   /wiki-ingest       │   │  tools/obsidian (Python) │   │  bamr87.github   │
  │   /save              ├──▶│  resolves the vault:     ├──▶│  .io/zer0-pages/ │
  │   /autoresearch      │   │     wikilinks → <a>      │   │                  │
  │   /wiki-query        │   │     callouts  → alerts   │   │  static HTML,    │
  │          │           │   │     dataview  → tables   │   │  zer0-mistakes   │
  │          ▼           │   │     graph → JSON index   │   │  theme + an      │
  │  pages/  (Obsidian   │   │  then Jekyll 4 + the     │   │  interactive     │
  │  vault = Jekyll src) │   │  theme, in Docker        │   │  vault graph     │
  └──────────────────────┘   └─────────────────────────┘   └──────────────────┘
```

- **`claude-obsidian/`** — git submodule; the content engine. Its skills read sources,
  synthesize knowledge, and file structured notes into the vault.
- **`pages/`** — the Obsidian vault *and* the Jekyll source. Three content collections
(`_docs/`, `_posts/`, `_notes/`), Maps of Content (`_moc/`), a growing `wiki/` knowledge base, plus the theme's data files (`_data/` — navigation, UI text, authors; a theme can't ship these), and two local include overrides kept for site-specific reasons (see `.theme-overrides.yml`), not for theme bugs — both bugs they were originally cut for shipped fixed in v1.26.0. Everything else — layouts, includes, vendored Bootstrap 5 — comes from the theme at its pinned tag; moving the tag is a change to the `render:` setting, re-recorded with its reason (`web/site/fixtures/zer0-pages/`).
- **`.github/workflows/pages.yml`** — builds and deploys on every push to `main`.

## Quickstart

```bash
git clone --recurse-submodules https://github.com/bamr87/zer0-pages
```

1. **Browse and author**: open the `pages/` directory as a vault in Obsidian (install the
   Dataview community plugin so the MOC dashboards populate). Start at `_moc/Home.md`.
2. **Let Claude do the writing**: run Claude Code in the repo and use the
claude-obsidian skills — they are the primary authoring path. Drop a file in `pages/.raw/` and say "ingest it" (`/wiki-ingest`), or "save this" (`/save`), or "research X" (`/autoresearch`); ask questions with `/wiki-query`. Docs, posts, and notes all flow from the same engine.
3. **One-time setup**: in the repo on GitHub, go to Settings → Pages → Build and
deployment and set **Source: GitHub Actions**. Skipping this makes the first deploy fail with a `Get Pages site failed` 404.
4. **Publish**: push to `main`. GitHub Actions resolves the vault's Obsidian syntax, builds the site with Jekyll and the zer0-mistakes theme, and deploys it to [bamr87.github.io/zer0-pages](https://bamr87.github.io/zer0-pages/).

To build locally instead, from the zer0-CMS repository root (Docker and Python with PyYAML; no Ruby): `bin/zer0 run build zer0-pages`, which writes `sites/zer0-pages/_site/`. The bridge's tests: `python3 -m unittest tools/tests/test_obsidian_bridge.py tools/tests/test_graph_index.py tools/tests/test_obsidian_vault.py`, which `bin/zer0 run check zer0-pages` runs with the SCHEMA lint.

## Graph view

The published site includes an interactive Obsidian-style graph of the whole vault at [/docs/obsidian/graph/](https://bamr87.github.io/zer0-pages/docs/obsidian/graph/). Before the build, the bridge (`tools/obsidian/graph_index.py`) reuses its wikilink parser to emit `/assets/data/wiki-index.json`; in the browser, the theme's Cytoscape-based UI renders every doc/post/note as a node, every wikilink as an edge, colored by collection — dead links show up as red "broken" nodes, which makes the graph double as a link-rot detector. Note pages also get a backlinks panel driven by the same JSON index.

## Writing content

Everything in `pages/` follows one rule: **Obsidian-native markdown, no Liquid.** Use
wikilinks (`[[_docs/jekyll/index|Jekyll docs]]`), callouts (`> [!tip] Title`), and the
supported Dataview grammar for listings. Frontmatter carries `title`, `type`, `description`, and a `permalink`/`aliases` pair. The full contract, including the exact Dataview grammar the bridge supports, lives in [CLAUDE.md](CLAUDE.md); vault-level conventions live in [pages/CLAUDE.md](pages/CLAUDE.md).

## Preview images

AI banner images come from the [zer0-image-generator](https://github.com/bamr87/zer0-image-generator)'s Python engine, `packages/zer0-image-generator/lib/zer0_image_generator/preview_generator.py` in zer0-CMS (`--dry-run` lists what needs a banner); the gem's `jekyll preview-images` left with the Gemfile, and PLAN G6 makes it a platform command. Images land in `pages/assets/images/previews/`; config lives under `preview_images:` in `_config.yml`. Rendering uses OpenAI by default (`OPENAI_API_KEY`); `--provider local` needs no keys.

## Learn more

- [PRD.md](PRD.md) — an early, aspirational product-requirements document; it describes
a Django+React CMS vision that predates and does not match the vault+bridge system described above (see [pages/wiki/sources/zer0-pages-prd.md](pages/wiki/sources/zer0-pages-prd.md) for the reality check).
- [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) — the Jekyll theme behind
the site's UI, published as the `jekyll-theme-zer0` gem, and the project this repo exists to be a second brain for (see [pages/wiki/entities/zer0-mistakes.md](pages/wiki/entities/zer0-mistakes.md)). Working on the theme itself? Change it in `bamr87/zer0-mistakes`; this site takes a release when its `render:` tag moves.
- [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) — the upstream
  knowledge-engine project (Karpathy's LLM Wiki pattern).
