# Recorded site builds (PLAN P1)

Each `<site>/manifest.json` records what one routed site's Jekyll build wrote, made on 2026-10-22 while every site still built with Jekyll. A site keeps its URLs, content, feeds and redirects whichever way it renders ([ADR 0006](../../../docs/adr/0006-one-python-platform.md) decision 4), so it moves — to the Jekyll-theme option ([PLAN](../../../docs/plan/PLAN.md) P2) or to the React renderer (P6, P7) — only when its new build reproduces its recording. These files are that baseline: never edit one by hand, and re-record one only with `tools/site_manifest.py`.

## What a recording holds

[`tools/site_manifest.py`](../../../tools/site_manifest.py) writes them (schema `site-manifest/v1`, stdlib Python, tests in [`tools/tests/test_site_manifest.py`](../../../tools/tests/test_site_manifest.py)) as JSON with sorted keys and a trailing newline:

- `paths` — every output file and its media type. An HTML page also has its `title` and `text_sha256`, the SHA-256 of its main text: the text of its `<main>` (else of its `<article>`s, else of its `<body>`) without the `header`, `nav`, `footer`, `aside`, `button`, `svg`, `time`, `script`, `style`, `noscript` and `template` elements in it, with a space at every block boundary and whitespace collapsed. The digest follows the words, not the markup: a renderer that writes the same words in other elements gets the same digest, and the theme's chrome (sidebars, menus, share buttons, the build stamp) does not count. Dates are left out because a page with no date of its own shows the build's date as its published date (108 zer0-pages pages and each demo's about page), and a recording must not change by the day.
- `feeds` — each Atom or RSS file's entries (`id`, `link`, `title`), in the feed's order.
- `sitemaps` — each sitemap's URLs, sorted.
- `redirects` — each page that redirects with a meta refresh (as jekyll-redirect-from writes them) and its target. No routed site has one today.

The bytes of other files (styles, scripts, images, fonts) are not recorded: most are the theme's, which a renderer in another design system will not reproduce, and a lost image still shows up as a missing path. Media types come from a fixed table in the tool rather than Python's `mimetypes`, whose table changes between releases, so the same build gives the same bytes under Python 3.12, 3.13 and 3.14 alike.

## How they were built

The way `.github/workflows/pages.yml` builds each site, in a `ruby:3.3` container: the routes from `bin/zer0 routes --json`; per site, a config file that sets only `url: "https://bamr87.github.io"` and `baseurl: "/zer0-CMS<route>"` (the workflow's defaults for `vars.PAGES_URL` and `PAGES_BASE_PATH`), `PAGES_REPO_NWO=bamr87/zer0-CMS` and `LANG=C.UTF-8`; `bundle install` in the site's bundle directory; then `bin/zer0 run pages <site>`, the site's own `pages` task (`bundle exec jekyll build --config "_config.yml,$ZER0_PAGES_CONFIG" --destination "$ZER0_PAGES_DEST"`). `--check` and `--write` run exactly that.

The remote-theme sites (all but zer0-pages) fetch the theme from its repository's default branch at build time — for these recordings, commit `98e978d` of 2026-10-20 — so a theme commit can change a recording without any change here: the theme's asset paths, and the main text where the theme writes inside `<main>`. P2's option pins the theme by tag.

## Rebuild and compare

```bash
python3 tools/site_manifest.py --check                  # rebuild every routed site, compare each with its recording; exit 1 on any difference
python3 tools/site_manifest.py --check --site drsai     # one site
python3 tools/site_manifest.py --write --site drsai     # re-record it, and say why in the commit
python3 tools/site_manifest.py build <dir> --site <name> --out <file>   # the manifest of any built tree (the renderer's, in P6)
python3 tools/site_manifest.py compare <recorded> <candidate>           # what differs; exit 1 when anything does
```

`--check` and `--write` need what `pages.yml` needs: Ruby 3.3 with bundler, and the network for the gems and the remote theme. Run them in CI, or in a `ruby:3.3` container (it has `python3`) that mounts the repository at its own path: `docker run --rm -v "$PWD:$PWD" -w "$PWD" ruby:3.3 python3 tools/site_manifest.py --check --site drsai`. Run in place, they leave what any local build leaves: a `Gemfile.lock` where none is committed, and Jekyll's caches. In CI, dispatch the **site-manifests** workflow ([`site-manifests.yml`](../../../.github/workflows/site-manifests.yml)): it rebuilds each routed site (or only the one named in `site`) and uploads the fresh recordings as the `site-manifests` artifact — unzip it over this directory to re-record — and with `check: true` it fails when one differs from what is committed here. It never commits: a baseline a machine rewrites is no baseline.

A recording describes the build as it was. When a site's content changes on purpose (a new post), re-record that site in the same commit; when it changes by accident, `--check` is what notices.

## Status, 2026-10-22

Every routed site built and is recorded.

| Site | Route | Built with | Paths | HTML pages | Feed entries | Sitemap URLs | Redirects | Notes |
|---|---|---|---|---|---|---|---|---|
| `zer0-demo-cookbook` | `/demos/cookbook/` | Jekyll 4.4.1, remote theme | 356 | 11 | 3 | 11 | 0 | |
| `zer0-demo-garden` | `/demos/garden/` | Jekyll 4.4.1, remote theme | 357 | 12 | 2 | 12 | 0 | Its notes' `[[wikilinks]]` and `> [!tip]` callouts come out as plain text — nothing in this build resolves them — and the recording keeps them that way |
| `drsai` | `/drsai/` | github-pages 232 (Jekyll 3.10.0), remote theme | 383 | 16 | 0 | 16 | 0 | |
| `parodynews` (`apps/parodynews/src/pages`) | `/parodynews/` | github-pages 231 (Jekyll 3.9.5), remote theme | 403 | 58 | 10 | 59 | 0 | Its 58 posts ask for layouts the theme does not have (57 `journals`, one `blog`), so they are written with no layout at all — no `<title>`, no `<main>` — and are recorded as built. Two of them (`2024-08-07-Generated Title.md`, `2024-08-07-generated-title.md`) write the same URL, so the build keeps one and the sitemap lists that URL twice. Five `.md` files are copied unrendered |
| `wargames` | `/wargames/` | Jekyll 4.4.1, remote theme | 587 | 221 | 0 | 221 | 0 | |
| `zer0-pages-remote` | `/zer0-pages-remote/` | github-pages 231 (Jekyll 3.9.5), remote theme | 341 | 1 | 0 | 1 | 0 | One page, its feed, sitemap and `robots.txt`; the other 337 paths are the theme's assets |
| `zer0-pages` | `/zer0-pages/` | Jekyll 4.4.1, the theme gem 1.28.0 (its `Gemfile.lock`) | 450 | 203 | 10 | 202 | 0 | 108 pages show the build's date as their published date (left out of the digest, above) |

Not recorded, because nothing routes them yet (`bin/zer0 routes`): `sites/2005` (published by year-of-ai.github.io), `sites/irony-works` (built by GitHub Pages' own Jekyll after a Node step) and `sites/1987` (no Jekyll config). Each needs a recording before its Jekyll build goes — PLAN P1's open sub-task.

**Determinism.** Every site was rebuilt twice more after these recordings were written, and matched both times: once from a separate copy of the tree through `--write` in a fresh container (byte-identical manifests), and once through `--check` on the container's own filesystem — another directory order — with a fresh gem install and the clock moved three days ahead with libfaketime (every site `identical`). The same build trees give byte-identical recordings under Python 3.12, 3.13 and 3.14.
