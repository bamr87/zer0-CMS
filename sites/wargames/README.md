# Wargames

Curated **security wargames** content — a vendored, markdown mirror of the [OverTheWire](https://overthewire.org/wargames/) community challenges (Bandit, Natas, Narnia, Behemoth, Leviathan, Krypton, and more), published as a Jekyll site with the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) theme.

> **Provenance:** This collection was extracted from
> [bamr87/it-journey](https://github.com/bamr87/it-journey) (`pages/_docs/wargames/`) via
> `git subtree split`, so the full edit history is preserved here. It now lives as a standalone
> repository so the IT-Journey site can stay focused on its gamified quests.

## Source & license

All challenge content is aggregated from the OverTheWire website and is distributed under the **MIT License**.

- **Upstream:** <https://github.com/OverTheWireOrg/OverTheWire-website> (`gh-pages` branch)
- **License:** [MIT](https://github.com/OverTheWireOrg/OverTheWire-website/blob/gh-pages/LICENSE)

This is **vendored content** — treat it as read-only and re-sync from upstream rather than editing the challenge pages by hand. Each page carries `source_repo` / `source_url` / `license` frontmatter recording its origin.

## Theme & site

The site is built with the **zer0-mistakes** Jekyll theme, loaded remotely on GitHub Pages via the `remote_theme: bamr87/zer0-mistakes` directive — no theme files are vendored here, so this repo stays content-only.

The framework (`_config.yml`, `Gemfile`, `_data/`, `.github/workflows/jekyll-gh-pages.yml`, `.devcontainer/`) was scaffolded with the theme's AI installer and is described declaratively in [`zer0.install.yml`](zer0.install.yml). Re-scaffold or upgrade it with:

```bash
# from a checkout of bamr87/zer0-mistakes
scripts/bin/install init /path/to/wargames --config /path/to/wargames/zer0.install.yml --non-interactive --force
```

### Content wiring

- `index.md` → the homepage (`/`), using the theme's `home` layout.
- `overthewire/**` → the challenge pages, served at their `permalink` (`/docs/wargames/…`) with the theme's `default` layout and the games sidebar (`_data/navigation/wargames.yml`). The `overthewire/index.md` is the games index at `/docs/wargames/`.
- `_config.yml` `defaults` attach layouts to the root-level content (there are no Jekyll collections), and `exclude` keeps tooling/docs out of the build.

### Local development

GitHub Pages renders the theme remotely; for a local preview, load the theme as a gem instead of `remote_theme`:

```bash
bundle install
bundle exec jekyll serve   # http://localhost:4000/wargames/
```

## Structure

```
index.md                 # Homepage (layout: home) — wargames hub
overthewire/             # Vendored OverTheWire challenge pages
  index.md               #   Games index (/docs/wargames/)
  bandit/                #   Linux/Unix fundamentals
  natas/                 #   Server-side web security
  narnia/ behemoth/ ...  #   Binary exploitation and beyond
_config.yml              # Jekyll config (remote_theme, defaults, excludes)
_data/navigation/        # Top navbar (main.yml) + games sidebar (wargames.yml)
zer0.install.yml         # Installer config that scaffolds the framework
scripts/docs-aggregator/ # Upstream content sync pipeline
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
