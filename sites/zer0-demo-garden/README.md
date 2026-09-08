# Marginalia

A public digital garden about reading, note-taking and how ideas connect — written in the open and revised in place.

**Live site: <https://bamr87.github.io/zer0-demo-garden/>**

This is a demonstration site for the [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) Jekyll theme. Every file in this repository was produced by the theme's **Site Builder** — the guided wizard at `/setup/` — from a single brief, then written to disk and built in Docker before being pushed here. Nothing was hand-assembled afterwards.

## What it demonstrates

- **Obsidian `[[wiki-links]]` and backlinks** — the notes link to each other in plain Markdown, the theme resolves them, and every note lists the notes that point at it. Open `pages/_notes/` as an Obsidian vault and the same links work there.
- **Callouts** — `> [!tip]` blocks render as themed admonitions on the site and in Obsidian.
- **The `editorial` landing template** — a left-aligned hero, the latest writing, a prose section and a subscribe call to action.
- **Theme overrides layered on a skin** — the `mint` skin with the `forest` palette, Merriweather + Source Sans 3, and round corners.
- **A `notes` collection alongside posts**, which is the distinction the site itself is about.

## How it was made

1. Ran the theme locally (`docker compose up`) and opened `/setup/`.
2. Connected an AI provider on the Connect step and described the site in one brief.
3. The wizard applied the identity, URL, structure, appearance and voice fields, then a **site plan** — landing template and sections, navigation shape, palette, font pairing, corner radius, and the pages themselves.
4. **Write project** scaffolded 26 files into a new folder; **docker compose up** built and served it; `jekyll build` inside the container validated it.

Total time from brief to a site serving on localhost: under a minute, plus the container's first gem install.

> **On authorship.** The machine that produced this had no xAI key and a revoked Claude token, so the model's turns were served by a local stand-in speaking the provider's real wire protocol. The wizard, its generators, the sandbox, Docker and Jekyll all ran for real; the prose in these pages was written by a human. It is not model output, and is not presented as any.

## Running it yourself

```bash
git clone https://github.com/bamr87/zer0-demo-garden.git
cd zer0-demo-garden
docker compose up          # http://localhost:4410/
```

Edit anything under `pages/` and the browser reloads. Site-wide settings are in `_config.yml`; restart the server after changing it.

## How it is published

GitHub Pages builds this repository directly from `main`. The theme arrives via `remote_theme: bamr87/zer0-mistakes`, so there is no vendored theme code here and no build workflow — updates to the theme reach this site on its next Pages build.

## Layout

| Path | What it holds |
| --- | --- |
| `_config.yml` | Production settings, collections and integrations |
| `_config_dev.yml` | Local overrides (localhost URL, live reload, analytics off) |
| `_data/landing.yml` | The landing page's hero and sections |
| `_data/navigation/main.yml` | The navigation bar |
| `assets/css/user-overrides.css` | Palette, fonts and corner radius over the skin |
| `pages/_notes/` | The notes, interlinked |
| `pages/_posts/` | Dated posts |
| `pages/_about/` | About page |
| `zer0.install.yml` | The answers this site was generated from |

---

Built with [zer0-mistakes](https://github.com/bamr87/zer0-mistakes) · [Site Builder documentation](https://zer0-mistakes.com/docs/features/site-builder/)
