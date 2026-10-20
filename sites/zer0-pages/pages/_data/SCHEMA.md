---
schema: "0.1"
coverage: listed
---

# SCHEMA — _data

> The live Jekyll data files — navigation, authors, UI text, and theme behaviour (Jekyll never loads _data from theme gems, so these copies rule).

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `navigation/` | dir | One YAML menu per navigation surface (navbar, docs sidebar, header quick-links, posts sections) | |
| `authors.yml` | file | Author profiles for frontmatter `author:` keys and the theme's author includes | |
| `content_statistics.yml` | file | Stats-layout data — zeroed stub (auto-generation disabled in _config.yml) | |
| `features.yml` | file | Theme feature-registry stub read by the gem's feature-card/showcase includes | |
| `landing.yml` | file | Hero and section content for pages that opt into `layout: landing` | |
| `prompts.yml` | file | Prompt templates for the Copilot Agent issue dropdown in _includes/content/intro.html | |
| `theme_backgrounds.yml` | file | Per-skin gradient/pattern/noise background asset map (fffuel.co assets) | |
| `theme_skins.yml` | file | Ordered theme-skin registry driving the appearance panel | |
| `ui-text.yml` | file | Localized UI strings — site.data.ui-text[site.locale] | |

## Placement

- New navigation surface → `navigation/<surface>.yml`.
- New author → an entry in `authors.yml` plus an avatar in `assets/images/authors/`.
