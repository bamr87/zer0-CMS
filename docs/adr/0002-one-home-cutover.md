# ADR 0002 — One home: zer0-CMS is where the zer0 stack lives, and content goes DB-first site by site

- **Status:** accepted 2026-10-19; not yet implemented — the cutover milestones C1–C7 in [`../plan/PLAN.md`](../plan/PLAN.md) carry it out, in order. **Amended by [ADR 0005](0005-theme-goes-home.md)** for the theme: `bamr87/zer0-mistakes` is the theme's home, not a mirror; decisions 2–5 below no longer apply to it, and the Pages deploy here targets this repository's own project site.
- **Amends:** [ADR 0001](0001-target-architecture.md) — decides PLAN-D1, which ADR 0001 left open. [`../MONOREPO.md`](../MONOREPO.md) § What still depends on the original repositories becomes the cutover checklist below.

## Context

The monorepo merge (#29, #36) imported ten repositories with their full history, but left each original as the place its releases, Pages sites and `remote_theme` come from. That is two homes for one codebase: a change made here does not reach the original, and a change merged there has to be re-imported. Every original also still costs the fleet hub a submodule, a CI run, a credential and a harness. The owner chose one direction, and answered the content question the plan had held open since M0.

## Decision

1. **zer0-CMS is the only place work happens.** Every commit to the zer0 stack lands here. The originals take no further commits of their own once the cutover reaches them (C1).
2. **Every original is archived — except `bamr87/zer0-mistakes`, which becomes a read-only mirror.** GitHub Pages loads a `remote_theme` only from the root of a repository, and about thirty sites (the fleet's and the year-of-ai/ai-world-view lineage's) name `remote_theme: bamr87/zer0-mistakes`. So that one repository keeps existing, fed from `packages/zer0-mistakes/` by a workflow here, with no history, issues or pull requests of its own. Every other original — `zer0-image-generator`, `books`, `drsai`, `zer0-pages`, `zer0-pages-remote`, `zer0-demo-cookbook`, `zer0-demo-garden`, `barodybroject` and `year-of-ai/2005` — is archived once nothing it publishes is left to move (`bamr87/1987` is already gone; its only home is `sites/1987/`).
3. **Releases are cut here.** release-please runs in manifest mode with one component per published package: the extension (`.`, as today), `jekyll-theme-zer0` (`packages/zer0-mistakes`), `zer0-image-generator` and the drsai story engine. Component tags are prefixed (`jekyll-theme-zer0-v1.31.4`), because ten version lines cannot share one `v*` series; the theme's release is also tagged `v1.31.4` on the mirror, so `remote_theme: bamr87/zer0-mistakes@v1.31.4` pins keep working. Each line continues from its original's last release rather than restarting.
4. **One Pages deploy, one domain, sub-paths.** A repository has one Pages site, so zer0-CMS publishes every in-repo site in one artifact on `zer0-mistakes.com`: the theme's docs at `/`, and `/zer0-pages/`, `/drsai/`, `/zer0-pages-remote/`, `/demos/cookbook/`, `/demos/garden/` and `/barodybroject/` for the rest. Before an original is archived its last commit replaces the site with redirects to the new URL, so old links forward. `sites/2005/` is the exception: it belongs to the year-of-ai organization's domain, so `year-of-ai.github.io` builds it from this repository into `/2005/`.
5. **PLAN-D1: content becomes DB-first in Wagtail, one site at a time.** A site cuts over when its byte-for-byte round trip (`roundtrip_jekyll`) has been green for two consecutive releases (PLAN §4.8). Cutting over means three things for that site: its Pages build renders from `export_jekyll` output instead of the Markdown in the tree; Wagtail is where its content is edited; and its Markdown becomes a generated snapshot the exporter commits, never hand-edited. Until a site cuts over, D16 holds for it — the files stay canonical and the content plane imports them. The smallest sites go first (`sites/zer0-pages-remote`, then the two demos), and the theme's docs site last.

## What enforces it

A decision no gate defends is a preference, so each part names its gate. The gates are built by the milestone named, not by this ADR.

| Part | Gate | Built by |
|---|---|---|
| One home | The originals' pull requests and issues are closed and their kill switches set; the hub stops targeting them | C1, C7 |
| The mirror stays a mirror | `mirror-theme.yml` refuses to push unless the mirror's `main` is exactly the commit it pushed last (a commit made there by hand fails the next sync instead of being overwritten) | C3 |
| Releases from here | release-please's manifest lists every published package; `bin/zer0 check` fails when a project declares `publishes:` without a component | C2 |
| One Pages deploy | `pages.yml` builds every site with its sub-path `baseurl`; `bin/zer0 check` fails when a site has no route | C4 |
| D1 per site | `workspace.yml` records each site's `content_source: files \| wagtail`; for a `wagtail` site, CI fails if its Markdown differs from what `export_jekyll` produces | D1-1 onwards |

## Consequences

- The ten-repository history becomes readable in one place — once C0 restores it: the import PRs were squash-merged, so until then `main` carries each imported tree as a single commit and the originals (and `refs/pull/29/head`, `refs/pull/36/head`) are the only full record. That is why no original is archived before C0. The fleet hub drops eight submodules (C7).
- Release tags change shape. Anything that matched `v*` on an original — Dependabot, a changelog link, a pinned `remote_theme@v…` — is served by the mirror's plain tag for the theme; the gem and PyPI versions themselves continue unchanged.
- URLs change for every site except the theme's docs. The redirect commit is what keeps an old link alive, which is why it is the last commit an original takes.
- Publishing credentials (RubyGems, PyPI) move to this repository. They are the owner's to add; the release milestone stops and asks rather than publishing without them.
- DB-first is a philosophy change for the sites that cut over: their history continues in Wagtail revisions, and git keeps the exported snapshots. A site that never meets the two-release bar simply stays files-first.
