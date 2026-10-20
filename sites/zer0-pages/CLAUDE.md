# zer0-pages — Architecture Contract

One repo, one body of content, two consumers: **Obsidian** (authoring/browsing) and **Jekyll** (publishing). The vault is never polluted with Liquid; the site never requires Obsidian. Every change must preserve that dual compatibility.

## Repo layout

```
zer0-pages/
├── claude-obsidian/          ENGINE — git submodule; authoring skills
│                             (/wiki-ingest, /wiki-query, /save, /autoresearch, ...)
│                             Never modify: it is an upstream submodule.
├── pages/                    VAULT + JEKYLL SOURCE (open this dir in Obsidian)
│   ├── _docs/ _posts/ _notes/    the three content collections
│   ├── _moc/                 Maps of Content — Home / Docs / Posts / Notes
│   ├── _templates/           Obsidian note templates (excluded from build)
│   ├── .raw/                 immutable ingest drop zone (excluded from build)
│   ├── wiki/                 claude-obsidian knowledge base (index/log/hot)
│   ├── .obsidian/            vault config (ignores Jekyll machinery dirs)
│   ├── _data/                THEME DATA — navigation/, ui-text, authors, ...
│   │                         (Jekyll never loads _data from theme gems)
│   ├── _includes/            local include overrides — bug-fix forks of two
│   │                         theme partials (Liquid allowed HERE only;
│   │                         no local _layouts/, all layout names resolve
│   │                         into the theme gem)
│   ├── _plugins/             BRIDGE — converts Obsidian constructs at build time
│   │                         + graph index generator (wiki-index.json)
│   └── assets/               css/js/images — css/user-overrides.css is the
│                             theme's custom-CSS hook (loaded after theme CSS)
├── _config.yml               Jekyll config (source: pages, destination: _site)
├── .theme-overrides.yml      declares the two intentional theme-partial forks
│                             (read by the theme's scripts/bin/audit-consumer)
├── Gemfile                   Jekyll 4 + jekyll-theme-zer0 (unconstrained) + plugins
├── tests/                    unit tests for the bridge + graph index (minitest)
├── .github/workflows/        pages.yml       build + deploy to GitHub Pages
│                             ci.yml          thin caller of the shared
│                                             bamr87/bamr87 standard-ci.yml
│                             schema-check.yml  SCHEMA.md pyramid lint
│                             markdown-oneline.yml  one-paragraph-per-line gate
│                             claude.yml      @claude mention handler
└── PRD.md                    product requirements (vision)
```

Content scope is deliberately narrow: **`_docs/`, `_posts/`, and `_notes/` only**, plus their MOC dashboards and the index pages at the vault root (`index.md`, `posts.md`, `notes.md`, `archives.md`, `categories.md`, `tags.md`). Do not add new collections without updating this contract.

## Content flow

1. **Author** — the claude-obsidian skills are THE content-creation path: `/wiki-ingest`
files sources dropped in `pages/.raw/` into structured notes, `/save` captures a conversation or insight, `/autoresearch` runs a research loop and files its findings, `/wiki-query` answers from the vault (and files good answers back). A human editing the vault in Obsidian works too — same rules apply.
2. **Bridge** — on push to `main`, CI runs `jekyll build`; `pages/_plugins/` converts
wikilinks, callouts, and Dataview fences to HTML during the build (source files are never rewritten) and generates the graph index JSON.
3. **Publish** — the built `_site` deploys to GitHub Pages at
`https://bamr87.github.io/zer0-pages/` (`url: https://bamr87.github.io`, `baseurl: /zer0-pages`). One-time manual step per repo: Settings → Pages → Build and deployment → Source: **GitHub Actions** — without it the first deploy fails with a `Get Pages site failed` 404.

## Theme

The site's UI is the **zer0-mistakes** theme, consumed as the published gem `jekyll-theme-zer0`. The Gemfile carries **no version constraint** — fleet policy is that every site tracks the latest theme, so a theme fix arrives on the next `bundle update jekyll-theme-zer0` rather than waiting on a bump PR. `Gemfile.lock` is committed and currently resolves **1.28.0**; the lock, not a constraint, is what makes a build reproducible. The trade is explicit: an upstream regression arrives as soon as you update, so theme bugs go **upstream** rather than getting pinned around. Layouts, includes, and vendored Bootstrap 5 come from the gem — the repo has **no local `_layouts/`**; every layout name (`default`, `article`, `note`, `section`, ...) resolves straight into the gem. The repo keeps exactly two local include overrides in `pages/_includes/`, declared in `.theme-overrides.yml` at the repo root so the theme's `scripts/bin/audit-consumer` classifies them as intentional rather than drift.

**Both of the bugs these forks were originally cut for are fixed upstream.** `bamr87/zer0-mistakes#293` (double `relative_url` on `preview_path`) and `#294` (`OBSIDIAN_WIKI_INDEX_URL` global-name mismatch) both shipped in theme **v1.26.0** (2026-07-07) — see that release's entries in the theme's `CHANGELOG.md`. An earlier version of this section claimed the opposite (that both were "still present upstream as of gem v1.26.0"); that was backwards. The forks are still kept, but for the reasons below — not for those two bugs.

- `content/intro.html` — the `preview_path` / `relative_url` logic in this fork is now **byte-identical** to the theme's, so it carries no baseurl fix any more (#293 is fixed; a build against 1.28.0 renders the hero banner as `url('/zer0-pages/assets/…')`, a single baseurl segment). What the fork still does differently: (a) it keeps the **"Copilot Agent" prompt dropdown** driven by `pages/_data/prompts.yml`, which the theme replaced with its page-feedback "Improve" widget — and that widget is gated on `site.page_feedback.enabled`, which this site does not set, so taking the theme's copy would leave the intro with no prompt/report button at all; (b) it predates the theme's **i18n integration** — no `{%- include core/i18n.html -%}`, no `ui.*` lookups — so every label in the fork is hard-coded English while the theme's copy is translatable.
- `obsidian/full-graph.html` — the `#294` workaround (pinning `window.OBSIDIAN_WIKI_INDEX_URL` explicitly) is **redundant** against 1.26.0+, whose `assets/js/obsidian-graph.js` reads `window.OBSIDIAN_CONFIG.wikiIndexUrl` first and only falls back to the legacy global. It is harmless (it sets the same baseurl-correct URL the fallback would use) and is left in place. The real reason this fork still exists is that it is **frozen at a pre-1.26 snapshot of the theme's graph page**: the theme has since redesigned that page entirely — a collapsible "Graph settings" panel (Filters / Display / Forces accordion), per-collection toggles with counts that double as the legend, an unresolved-links switch, node-size / link-thickness / label-fade sliders, repulsion / link-distance sliders with animated re-layout, a vertical zoom-in/out/fit/fullscreen button group, a hover preview card, `tag:` and `path:` search operators, and localStorage-persisted settings. The fork has none of it: just a flat toolbar (search + Reset view + orphans switch), a static legend, and its own scoped `<style>` block (the theme styles this from `_sass/core/_obsidian.scss`). It also drops the theme's H1/intro and its "See also" wikilinks — which point at theme-only pages that do not exist in this vault — and credits the local `pages/_plugins/obsidian_graph_index.rb` in "How it's built".

**Retiring either fork is a real change, not a cleanup.** Dropping `content/intro.html` trades the Copilot dropdown for a button this site has disabled; dropping `obsidian/full-graph.html` gains the redesigned graph UI but re-introduces five broken wikilinks and a "How it's built" table that credits the theme's Liquid template instead of this repo's generator. Do neither without building and eyeballing the rendered pages.

- **Data files are ours to provide.** Jekyll never loads `_data` from theme gems, so
every data file the theme reads lives in `pages/_data/`: site navigation in `pages/_data/navigation/*.yml`, plus `ui-text.yml`, `authors.yml`, `theme_skins.yml`, `theme_backgrounds.yml`, and structured stubs for `content_statistics.yml` / `features.yml`.
- **Custom CSS hook.** `_config.yml` sets `user_overrides: true`, so the theme loads
`pages/assets/css/user-overrides.css` LAST (after its own CSS) — bridge styling (Dataview tables, callouts, unresolved-wikilink flags) lives there.
- **The theme repo's own `obsidian_links.rb` is intentionally NOT used**: plugins
never load from theme gems, and it resolves wikilinks by title while this vault's links are path-qualified — copying it in would double-convert. The bridge in `pages/_plugins/` is the sole Obsidian→HTML converter.
- **Local theme development** (tip): to hack on the theme, temporarily point the
Gemfile at the local checkout — `gem "jekyll-theme-zer0", path: "../github/zer0-mistakes"` — but the *committed* Gemfile MUST reference the published gem, unconstrained. Never re-add a version constraint to dodge an upstream bug; fix it in `bamr87/zer0-mistakes` and pick up the release.

## Obsidian graph UI

The site ships an interactive vault graph (theme feature, enabled end-to-end):

- **Data** — `pages/_plugins/obsidian_graph_index.rb` (Jekyll shim over the pure-ruby
core `pages/_plugins/obsidian/graph_index.rb`) walks the same document pool as the bridge, extracts each doc's outgoing wikilinks (reusing the bridge's parser and fence-masking — never duplicate that logic), and emits `/assets/data/wiki-index.json` (`{generated_at, count, entries[]}`; entry = title/basename/url/collection/tags/categories/aliases/outgoing/excerpt). This local synthetic page overrides the theme's own Liquid template for the same path — the theme template must NOT win, because it parses wikilinks at render time, after the bridge has already rewritten them.
- **UI** — the theme's `js-cdn.html` (included by the gem's layout chain) sets
`window.OBSIDIAN_CONFIG` and loads the gem's `assets/js/obsidian-graph.js` + vendored Cytoscape, which fetch the JSON and render the graph. The theme treats this as on unless `obsidian.enabled == false`; `_config.yml` pins `obsidian: { enabled: true }` explicitly. Unresolved link targets render as red "broken" nodes — that is a feature, not a bug; fix the dead wikilink, not the graph.
- **Page** — the graph lives at `/docs/obsidian/graph/`
(`pages/_docs/obsidian/graph.md`), whose body is a short intro plus `{% include obsidian/full-graph.html %}`. That file is the ONE content file with `render_with_liquid: true` (the include is Liquid). The include itself is a local override at `pages/_includes/obsidian/full-graph.html`, trimmed of theme-repo-only links.
- **Backlinks** — the theme's `note` layout includes a client-side backlinks panel
  that consumes the same `wiki-index.json`, so notes show "linked from" for free.

## Dual-compatibility rules — ALL new content

- **Frontmatter** (flat YAML): every file must carry `title`, `type`, and `description`.
Give each page a `permalink:` and mirror it in `aliases:` (aliases carry old/canonical URLs so wikilinks and historic links resolve). Collections also apply pattern permalinks (`/docs/:path/`, `/notes/:path/`) — an explicit `permalink:` in frontmatter always wins. **`_posts/` is the exception**: it is Jekyll's built-in posts collection, not a custom one, so it has no entry under `collections:` in `_config.yml` and instead uses the sitewide `permalink: pretty` date-based scheme — individual post files do not need an explicit `permalink:`/`aliases:` pair unless their URL needs to diverge from that default (the seven `NNNN-01-01-index.md` category-index pages under `_posts/<category>/` are the diverging case, and do carry explicit permalinks).
- **Wikilinks** are fine and preferred: `[[path/from/vault-root|Display]]` —
path-qualified from the vault root, no `.md` extension. The bridge resolves them to URLs; unresolved links render as a flagged `<span>` (and as red nodes in the graph).
- **Callouts**: both `> [!NOTE]` and `> [!note] Title` styles convert to Bootstrap
  alerts.
- **NO Liquid in content, ever.** `render_with_liquid: false` is defaulted for all
content; `{% %}` / `{{ }}` will appear literally. Liquid belongs only in `pages/_layouts/` and `pages/_includes/`. The sole exception is `pages/_docs/obsidian/graph.md`, which opts in with `render_with_liquid: true` for its single include line. Docs that *teach* Liquid keep examples inside code fences (the bridge skips fences).
- **Dataview** fences are supported ONLY within this grammar (anything outside it falls
back to a plain link list) — authoritative spec: the header comment of `pages/_plugins/obsidian/dataview.rb`:
  - Mode: `TABLE <col>[, <col>...]` or `LIST [<expr>]`; col := `expr [AS label]`
  - `FROM "folder" [OR "folder"...]` or `FROM "" AND -"excluded" [AND -"..."]`
    (e.g. `"_docs"`, `"_docs/features"`, `"wiki"`)
  - Optional `WHERE clause [AND clause...]`; clause := `expr [=|!= expr]` or a truthy
    `expr`
  - Optional `FLATTEN expr AS alias` (repeatable), `GROUP BY expr [AS alias]`,
    `SORT key [ASC|DESC][, key ...]`, `LIMIT n`
  - expr := `field.path` | `"literal"` | number | `true|false|null` | fn(args) with
    fns `length`, `default`, `choice`, `dateformat`, `regexreplace`, `lower`, `upper`;
    file fields `file.name`/`file.folder`/`file.link`/`file.path`; `rows.<path>`
    after GROUP BY

## Build & test

- **Unit tests** (system ruby 2.6 is enough — the cores under
  `pages/_plugins/obsidian/` are stdlib-only):
  - Bridge: `ruby -Ipages/_plugins tests/test_obsidian_bridge.rb`
  - Graph index: `ruby -Ipages/_plugins tests/test_graph_index.rb`
- **Local site build** (needs bundler + Jekyll 4):
  `bundle install && bundle exec jekyll build`
- **CI** — five workflows, only two of which build the site:
  - `pages.yml` — builds on ruby 3.3 (`JEKYLL_ENV: production`, `actions/configure-pages`)
and deploys to GitHub Pages. Triggers: **push to `main`** touching `pages/**`, `_config.yml`, `Gemfile*`, or the workflow itself, plus `workflow_dispatch`. **There is no `pull_request` trigger**, so the exact production build-and-deploy path is never exercised before merge. Deployment requires the one-time GitHub Pages setting described under [Content flow](#content-flow) (Source: GitHub Actions).
  - `ci.yml` — runs on **`pull_request`** and push to `main`; a thin caller of the shared
`bamr87/bamr87/.github/workflows/standard-ci.yml@main`. That reusable workflow auto-detects the stack, and because this repo has a `Gemfile`, no Rakefile `test` task, and no `spec/`, it falls through to `bundle exec jekyll build` — so a PR that breaks the themed build **is** caught. Two caveats: the gate's logic lives in another repo and floats on `@main` (it can change without a commit here), and it builds without `JEKYLL_ENV: production` and without `actions/configure-pages`, so it is not a byte-for-byte rehearsal of the deploy build.
  - `schema-check.yml` — `python3 tools/schema_lint.py check .` on PRs, pushes to `main`,
    and dispatch. Errors gate; warnings only log.
  - `markdown-oneline.yml` — `tools/unwrap-prose.py --check` on `**/*.md` in PRs and
    pushes to `main` (`SCHEMA.md` / `CHANGELOG.md` excluded). Fix with `--write`.
  - `claude.yml` — `@claude` mention handler for issues and PR comments; not a gate.

## More detail

- Vault-level conventions (wiki index/log/hot, ingest workflow, MOCs):
  `pages/CLAUDE.md`.
- Product vision: `PRD.md`.
- Do not modify `claude-obsidian/` (submodule) or `.backups/`.


## SCHEMA.md protocol (Pyramid Schema)

This repository is structured by `SCHEMA.md` files — one per directory, each a lintable contract describing its own contents, one level deep. They are your primary source of structural truth. Prefer reading the schema chain over running `ls -R` / `find` to understand layout.

**Orient.** At the start of work, read `./SCHEMA.md`. Before touching any directory, read its `SCHEMA.md` and, if placement is in question, the chain of schemas from root down to it. `## Conventions` inherit from ancestors; the nearest schema wins.

**Follow.** Place and name new files according to `## Placement` and `## Structure` in the nearest schema. If nothing routes your file, do not guess: add a row to the appropriate Structure table (and a Placement route if it will recur), then create the file. Respect `## Forbidden`. Never hand-edit entries marked `generated`. Never descend into directories marked `terminal`.

**Propagate.** Creating a directory is one atomic act with three parts:
1. Create the directory.
2. Create its `SCHEMA.md` from `templates/SCHEMA.template.md`, filling every
   placeholder — especially the one-line purpose.
3. Register it in the parent directory's Structure table.
Never leave a new directory schemaless.

**Maintain.** Any add / remove / rename updates the local `SCHEMA.md` in the same commit as the change itself. Schema edits ride with the work they describe. If you find drift you didn't cause, fix it and note it.

**Verify.** Before declaring a task done, run:

```
python tools/schema_lint.py check .
```

Fix errors. Surface warnings to the user with a one-line explanation each if you choose not to fix them.
