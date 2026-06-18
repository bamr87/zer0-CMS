# zer0-CMS — a fork of Front Matter CMS

**zer0-CMS** is an AI-augmented content CMS for VS Code, built for the
**IT-Journey / zer0-mistakes** platform. It is a fork of the excellent
[Front Matter CMS](https://github.com/estruyf/vscode-front-matter) by
**Elio Struyf**, and stands on its shoulders.

## Attribution & license

- Upstream: [`estruyf/vscode-front-matter`](https://github.com/estruyf/vscode-front-matter)
  (forked at **v10.10.1**).
- License: **MIT** — the original `LICENSE` (© 2019 Elio Struyf) is preserved
  unchanged, as MIT requires. zer0-CMS remains MIT.
- Front Matter is a mature, full-featured CMS. All of its content-management
  capabilities (content types, taxonomy, media, snippets, data files, SEO checks,
  the dashboard and panel) come from that upstream work.

## What zer0-CMS adds (the "zer0 layer")

On top of Front Matter, zer0-CMS integrates the IT-Journey AI content system:

- **Content-health insight** — reads the `.cms/` contract emitted by IT-Journey's
  engine (`scripts/cms/cms.py`): per-file health scores, freshness, and the
  mechanical/substantive issue lanes.
- **Embedded Claude Code agents** — runs the `cms-curator` skill via the
  `@anthropic-ai/claude-agent-sdk`, with an approve/deny diff gate for every edit.
- **Mechanical lane** — preview/apply the deterministic frontmatter normalizer,
  with vendored content always protected.

These are being grafted onto Front Matter's extensibility points rather than
replacing its UI. See `src/zer0/` for the added modules.

## Relationship to upstream

This is a GitHub fork, so we can pull Front Matter's future updates:

```bash
git fetch upstream
git merge upstream/main         # or: git rebase upstream/main
```

The internal command/configuration namespace (`frontMatter.*`) is **kept as-is**
for now so upstream merges stay clean; only the product identity (name,
publisher, branding) is changed. A namespace rename can happen later if desired.

## Build & run

```bash
npm install
npm run build:ext      # webpack: extension + dashboard + panel bundles
# then press F5 in VS Code (Run Extension)
```

## Thanks

Enormous thanks to **Elio Struyf** and the Front Matter contributors. If you find
zer0-CMS useful, please also support the upstream project:
<https://github.com/sponsors/estruyf>.
