# zer0-pages

**Zero friction. Infinite possibilities.**

zer0-pages is an AI-powered knowledge site with a twist: the content is an [Obsidian](https://obsidian.md) vault, the librarian is [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian), and the publisher is [Jekyll](https://jekyllrb.com) running in GitHub Actions. You (or Claude, on your behalf) write plain Obsidian-native markdown — wikilinks, callouts, Dataview queries — and a set of custom build-time "bridge" plugins convert those constructs to HTML for GitHub Pages. The site's look and feel comes from the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme, consumed as the published `jekyll-theme-zer0` gem.

The vault is never polluted with Liquid templating. The published site never requires Obsidian. One body of content, two first-class consumers.

Beyond showcasing the theme, zer0-pages' declared purpose is to act as a **second brain for [zer0-mistakes](https://github.com/bamr87/zer0-mistakes)** — a place where research, decisions, and usage knowledge about the theme accumulate and can feed back into its development, rather than living only in this repo's own showcase content. See [pages/wiki/entities/zer0-mistakes.md](pages/wiki/entities/zer0-mistakes.md) for the current state of that relationship (and an open gap: the deep technical knowledge still lives only in the zer0-mistakes repo itself, not yet ingested here).

## Architecture

```
             AUTHOR                      BUILD                      SERVE
  ┌──────────────────────┐   ┌─────────────────────────┐   ┌──────────────────┐
  │  claude-obsidian     │   │  GitHub Actions          │   │  GitHub Pages    │
  │  skills (engine)     │   │                          │   │                  │
  │   /wiki-ingest       │   │  Jekyll 4 + theme gem    │   │  bamr87.github   │
  │   /save              ├──▶│  (jekyll-theme-zer0)     ├──▶│  .io/zer0-pages/ │
  │   /autoresearch      │   │   + pages/_plugins/      │   │                  │
  │   /wiki-query        │   │     obsidian bridge:     │   │  static HTML,    │
  │          │           │   │     wikilinks → <a>      │   │  zer0-mistakes   │
  │          ▼           │   │     callouts  → alerts   │   │  theme + an      │
  │  pages/  (Obsidian   │   │     dataview  → tables   │   │  interactive     │
  │  vault = Jekyll src) │   │     graph → JSON index   │   │  vault graph     │
  └──────────────────────┘   └─────────────────────────┘   └──────────────────┘
```

- **`claude-obsidian/`** — git submodule; the content engine. Its skills read sources,
  synthesize knowledge, and file structured notes into the vault.
- **`pages/`** — the Obsidian vault *and* the Jekyll source. Three content collections
(`_docs/`, `_posts/`, `_notes/`), Maps of Content (`_moc/`), a growing `wiki/` knowledge base, plus the bridge plugins, the theme's data files (`_data/` — navigation, UI text, authors; theme gems can't ship these), and two local include overrides that fix bugs still present in the theme gem. Everything else — layouts, includes, vendored Bootstrap 5 — comes from the `jekyll-theme-zer0` gem (~> 1.25).
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
4. **Publish**: push to `main`. GitHub Actions builds the site with Jekyll, the
`jekyll-theme-zer0` theme, and the Obsidian bridge plugins, and deploys it to [bamr87.github.io/zer0-pages](https://bamr87.github.io/zer0-pages/).

To build locally instead: `bundle install && bundle exec jekyll build` (Ruby 3.x recommended; CI uses 3.3). Unit tests run on plain system Ruby: `ruby -Ipages/_plugins tests/test_obsidian_bridge.rb` (bridge) and `ruby -Ipages/_plugins tests/test_graph_index.rb` (graph index).

## Graph view

The published site includes an interactive Obsidian-style graph of the whole vault at [/docs/obsidian/graph/](https://bamr87.github.io/zer0-pages/docs/obsidian/graph/). At build time, a plugin (`pages/_plugins/obsidian_graph_index.rb`) reuses the bridge's wikilink parser to emit `/assets/data/wiki-index.json`; in the browser, the theme's Cytoscape-based UI renders every doc/post/note as a node, every wikilink as an edge, colored by collection — dead links show up as red "broken" nodes, which makes the graph double as a link-rot detector. Note pages also get a backlinks panel driven by the same JSON index.

## Writing content

Everything in `pages/` follows one rule: **Obsidian-native markdown, no Liquid.** Use
wikilinks (`[[_docs/jekyll/index|Jekyll docs]]`), callouts (`> [!tip] Title`), and the
supported Dataview grammar for listings. Frontmatter carries `title`, `type`, `description`, and a `permalink`/`aliases` pair. The full contract, including the exact Dataview grammar the bridge supports, lives in [CLAUDE.md](CLAUDE.md); vault-level conventions live in [pages/CLAUDE.md](pages/CLAUDE.md).

## Preview images

AI banner images come from the [zer0-image-generator](https://github.com/bamr87/zer0-image-generator) gem (a zer0-mistakes companion, installed via the Gemfile):

```bash
bundle exec jekyll preview-images --list-missing   # what needs a banner?
bundle exec jekyll preview-images                  # generate + wire `preview:` front matter
```

Images land in `pages/assets/images/previews/` (the gem honors `source: pages`); config lives under `preview_images:` in `_config.yml`. Rendering uses OpenAI by default (`OPENAI_API_KEY`); `--provider local` needs no keys.

## Learn more

- [PRD.md](PRD.md) — an early, aspirational product-requirements document; it describes
a Django+React CMS vision that predates and does not match the vault+bridge system described above (see [pages/wiki/sources/zer0-pages-prd.md](pages/wiki/sources/zer0-pages-prd.md) for the reality check).
- [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) — the Jekyll theme behind
the site's UI, published as the `jekyll-theme-zer0` gem, and the project this repo exists to be a second brain for (see [pages/wiki/entities/zer0-mistakes.md](pages/wiki/entities/zer0-mistakes.md)). Working on the theme itself? See the "local theme development" tip in [CLAUDE.md](CLAUDE.md).
- [claude-obsidian](https://github.com/AgriciDaniel/claude-obsidian) — the upstream
  knowledge-engine project (Karpathy's LLM Wiki pattern).
