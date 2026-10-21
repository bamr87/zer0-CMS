# ADR 0003 — The framework rebuild: one headless CMS, no product brands in the framework, a tree that carries only what runs

- **Status:** accepted 2026-10-20; implemented by the pull request that adds this file, except where a row below says otherwise.
- **Amends:** [ADR 0001](0001-target-architecture.md) (decides PLAN-D4) and [ADR 0002](0002-one-home-cutover.md) §4 (the news app's route). The target architecture itself does not change: a Django + Wagtail **content plane** (`content/`), a Rails **experience plane** (`rails/`), and the extension and Jekyll sites as clients and frontends.

## Context

A full validation of `main` at `e8a8876e` (every project's `check`, `test`, `build` and `pages` task, the Rails and content-plane stacks booted from the root compose file, the theme's Playwright tier) found the code green and the repository heavy: 204 MB of tracked files, 168 MB of them images, in a 545 MB pack of which 82 % is history that no current file references. The imported products also carried their old identities into the framework: a Django app named after a defunct site, personal author defaults baked into theme includes every consumer renders, and seven byte-identical copies of one tool kept only so each import's old CI could call it by a relative path.

## Decisions

| # | Decision | Mechanism that enforces it |
|---|---|---|
| 1 | **PLAN-D4 is decided: barodybroject does not survive as a product or a brand.** The app lives on as `apps/parodynews/` — the same Django 5.2 + React code, its project package renamed `config` (the convention `content/` already uses), its brand strings, domains, e-mail addresses, cache prefixes and Azure resource names replaced by `parodynews` or placeholders — until PLAN M20 absorbs its models into the content plane. Its upstream stays recorded as `bamr87/barodybroject` in `workspace.yml` and `docs/MONOREPO.md`, because that is the repository it was imported from. | `bin/zer0 check` (registration, workflow filters, vendored copies); `parodynews.yml` (its pytest, pre-checks, lint and frontend gates); `content/tests/importers/test_parodynews.py` |
| 2 | **The framework ships no person.** Theme includes and layouts take the author from the site (`site.author.key`, then the `default` entry of `_data/authors.yml`, then its first entry) and the JSON-LD `Person` from `site.founder`, `site.author.name` or `site.title`. A site that wants a byline sets it in its own `_config.yml`, as the theme's docs site and `sites/zer0-pages` now do. | The theme's quality suite and Obsidian build; the rendered JSON-LD is checked in the rebuild validation |
| 3 | **Visual PR evidence is a pull-request artifact, never tree content.** `packages/zer0-mistakes/test/visual/evidence/` (371 screenshots, 57 MB) is removed and ignored; the generators (`test/visual/*-evidence.mjs`) stay, and a PR attaches what they render. Stray browser-session screenshots (`sites/irony-works/.playwright-mcp/`) are removed and ignored likewise. | `.gitignore` in both trees |
| 4 | **One copy of a hub-seeded tool per repository.** `tools/unwrap-prose.py` is the only copy; projects call it as `../../tools/unwrap-prose.py`. The theme keeps the one exception because its `scripts/translate.rb` and `test/test_i18n.sh` must also run in the read-only mirror (ADR 0002), which has no root `tools/`. | `workspace.yml` `vendored:` lists the theme's copy only; `bin/zer0 vendor` fails on drift |
| 5 | **Images that a site's own content references stay with the site.** `sites/zer0-pages` carries 136 images byte-identical to the theme's (31 MB) because its posts and docs reference them and the published theme gem deliberately excludes `assets/images/`. They are not removed; sharing them is a build-time concern for the Pages deploy (a path gem or a symlinked `assets/images/` in a non-safe build), decided when that site cuts over (ADR 0002 §5). | — (recorded, not enforced) |
| 6 | **History is not rewritten in this PR.** 798 MB of the 970 MB of blob data exist only in history (a 42 MB debug log, superseded preview renders, old `.gem` files, a 7 MB gif). A `git filter-repo` pass would shrink a fresh clone by roughly four fifths, but it is a force-push that invalidates every clone, the theme mirror's parentage and the open import branches, so it is the owner's call, made once and announced. The measured plan is in the section below. | AGENTS.md § Git hygiene (no history rewrites on shared branches) |
| 7 | **The directory moves in PLAN M2 stay held.** Moving `rails/` → `app/`, `src/` → `clients/vscode/` and the sites under `frontends/` is cosmetic until PLAN-D5 (does the extension stay?) is decided, and it changes what the hub's `detect-stack` sees at the root. The two-plane shape is already the one `AGENTS.md`, the compose file and `workspace.yml` describe. | — |

## What this PR removed, and why each removal keeps every capability

| Removed | Size | Why nothing is lost |
|---|---|---|
| `packages/zer0-mistakes/test/visual/evidence/` | 57 MB, 371 files | Screenshots of past PRs; regenerated on demand by the checked-in generators; the baselines the Playwright tier compares against are elsewhere (`test/visual/**/*-snapshots/`) |
| `sites/irony-works/.playwright-mcp/` | 2 MB, 39 files | Browser-session captures that no test or page reads |
| 10 images under `apps/parodynews/src/assets/` | 9 MB | Referenced by nothing in the tree (checked with `git grep` per file) |
| 7 copies of `tools/unwrap-prose.py` | 60 KB | Byte-identical to the root copy; every caller now uses `../../tools/unwrap-prose.py` |
| `apps/parodynews/.github/workflows/markdown-oneline.yml` | — | A nested workflow never runs here; the root `markdown-oneline.yml` covers the whole repository |

Tracked files: **204 MB → 136 MB**. The pack a fresh clone downloads is unchanged until decision 6 is taken.

## History rewrite — the owner's decision

If and when the owner decides to rewrite, the measured plan is:

```bash
# in a fresh mirror clone, never in a working checkout
git clone --mirror https://github.com/bamr87/zer0-CMS zer0-CMS.git && cd zer0-CMS.git
git filter-repo --strip-blobs-bigger-than 2M \
  --path packages/zer0-mistakes/logs/debug-trace.log --path-glob 'packages/zer0-mistakes/*.gem' \
  --path-glob 'docs/public/releases/**' --path packages/zer0-mistakes/test/visual/evidence --invert-paths
git push --force --mirror   # every collaborator re-clones; the theme mirror is re-seeded by theme-mirror.yml
```

Before that push: close or rebase every open branch and PR, re-seed the theme mirror, and tell the fleet hub the SHAs changed. None of it is done by this PR.

## Consequences

- `apps/parodynews` tests, pre-checks and frontend gates pass unchanged in behaviour (403 tests, 31 Vitest tests); the renamed importer in the content plane passes its round-trip test; `bin/zer0 check` passes with one vendored copy.
- Consumers of the theme that never set `site.author.key` and have no `default` author now get the first entry of their own `_data/authors.yml` instead of a person they never configured.
- The news app's Jekyll sidecar `_config.yml` no longer carries the undefined `*site_domain` alias that made `zer0 doctor` report an error for it.
- Branding that is *content* — bylines in posts, the theme docs site's own founder, the fleet fixtures the extension's tests model (`lifehacker`, `it-journey`, `bash-365`) — is untouched: a framework strips its own defaults, not its users' pages.
