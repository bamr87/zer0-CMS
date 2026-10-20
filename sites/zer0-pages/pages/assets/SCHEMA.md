---
schema: "0.1"
coverage: listed
---

# SCHEMA — assets

> Site-owned static assets — everything else (Bootstrap, theme CSS/JS, layout assets) ships inside the jekyll-theme-zer0 gem.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `backgrounds/` | dir | Theme background textures referenced by _data/theme_backgrounds.yml | |
| `css/` | dir | Site CSS override hook loaded after the theme's stylesheets | |
| `images/` | dir | Site imagery — identity art, author avatars, docs screenshots, generated preview banners | |
| `js/` | dir | Site JS override hook loaded by the theme | |

## Placement

- Site-specific styles → `css/user-overrides.css`; site-specific scripts → `js/user-overrides.js`.
- New images → the matching subdirectory of `images/` (see its SCHEMA.md).
