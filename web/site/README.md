# web/site — the site renderer

**Not built yet; today this directory holds the recordings it will be measured against.** This is where the React site renderer will live ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 4, [PLAN](../../docs/plan/PLAN.md) P6): a TypeScript build that reads a site's generated file tree (its config, data, collections, posts and pages — decision 13), evaluates the Liquid in its content with `liquidjs`, renders its Markdown with kramdown-compatible unified plugins, lays the pages out in the platform's own design system (tokens and components seeded from the zer0 UI tokens, not ported from the theme), and writes the static site — pages, feeds, sitemap, robots, a Pagefind search index and redirects — with no live database. zer0-pages's Obsidian features (wikilinks, embeds, callouts, Dataview, the graph index) become renderer plugins. A site that keeps the zer0 Jekyll look takes the Jekyll-theme option instead (P2), which does not use this code.

A site keeps its URLs, content, feeds and redirects whichever way it renders, so it moves to this renderer one at a time (`P7-<site>`, sites chosen by the owner, P-D5) and only when its build here reproduces the recording of its Jekyll build in [`fixtures/`](fixtures/README.md): the same output paths, the same main text on every page, the same feed entries, sitemap URLs and redirects. Those recordings were made in P1, while every site still built with Jekyll, by [`tools/site_manifest.py`](../../tools/site_manifest.py). P6's `npm run site -- --site <name> --compare` measures the renderer against them; the tool's `build` writes the same kind of manifest of any built tree, so that comparison can use its `compare` as it is.

| Path | What it is |
|---|---|
| `fixtures/<site>/manifest.json` | What the site's Jekyll build wrote, recorded in P1 — the parity baseline, never edited by hand |
| `fixtures/README.md` | What a recording holds, how to rebuild and compare one, and each site's status |

The renderer's own code (`package.json`, sources, tests) arrives with P6, inside the `web/` workspace the studio starts (P4).
