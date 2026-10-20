---
schema: "0.1"
coverage: listed
---

# SCHEMA — noise

> SVG noise textures generated with fffuel.co's nnnoise tool — one per theme skin.

## Structure

| entry | kind | purpose | rules |
|---|---|---|---|
| `*.svg` | pattern | Noise texture for the matching skin key in _data/theme_skins.yml (air, aqua, dark, ...) | |

## Placement

- New skin → its noise SVG here, wired up in `_data/theme_backgrounds.yml`.
