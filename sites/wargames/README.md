# Wargames

Curated **security wargames** content — a vendored, markdown mirror of the [OverTheWire](https://overthewire.org/wargames/) community challenges (Bandit, Natas, Narnia, Behemoth, Leviathan, Krypton, and more).

> **Provenance:** This collection was extracted from
> [bamr87/it-journey](https://github.com/bamr87/it-journey) (`pages/_docs/wargames/`) via
> `git subtree split`, so the full edit history is preserved here. It now lives as a standalone
> repository so the IT-Journey site can stay focused on its gamified quests.

## Source & license

All challenge content is aggregated from the OverTheWire website and is distributed under the **MIT License**.

- **Upstream:** <https://github.com/OverTheWireOrg/OverTheWire-website> (`gh-pages` branch)
- **License:** [MIT](https://github.com/OverTheWireOrg/OverTheWire-website/blob/gh-pages/LICENSE)

This is **vendored content** — treat it as read-only and re-sync from upstream rather than editing the challenge pages by hand. Each page carries `source_repo` / `source_url` / `license` frontmatter recording its origin.

## Structure

```
index.md                 # Wargames hub (game list, getting started)
overthewire/
  bandit/                # Linux/Unix fundamentals
  natas/                 # Server-side web security
  narnia/ behemoth/ ...  # Binary exploitation and beyond
```

## Regenerating from upstream

The `scripts/docs-aggregator/` pipeline clones the OverTheWire repo, extracts the wargames markdown, and rewrites frontmatter with provenance metadata.

```bash
pip install -r scripts/docs-aggregator/requirements.txt
./scripts/docs-aggregator/aggregate_docs.sh
```

Sources are registered in `scripts/docs-aggregator/docs_config.yml`.

## Using this content

The pages are plain Markdown with YAML frontmatter (Jekyll-compatible). They can be served as a standalone Jekyll site, embedded in another docs system, or read as-is on GitHub.
