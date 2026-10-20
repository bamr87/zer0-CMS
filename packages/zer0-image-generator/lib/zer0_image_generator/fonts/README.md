# Bundled fonts

The illustration loop authors banner headlines as `<text>` and ships them as `<path>` — `svg_text_to_paths()` in `preview_generator.py` (Ruby twin: `svg/text_to_paths.rb`) outlines every glyph with one of these fonts, so a committed banner never depends on what the viewer has installed.

| File | Family key | Used for | License |
| --- | --- | --- | --- |
| `PressStart2P-Regular.ttf` | `press-start-2p` | the `retro-pixel` style card's headlines | [OFL-PressStart2P.txt](OFL-PressStart2P.txt) — shipped **unmodified** (the license reserves the font name, so it is not subset) |
| `Inter-Regular.ttf` | `inter` | every other card, weights below 600 | [OFL-Inter.txt](OFL-Inter.txt) |
| `Inter-Bold.ttf` | `inter-bold` | every other card, weights 600 and up | [OFL-Inter.txt](OFL-Inter.txt) |

The two Inter files are static instances of Google Fonts' `Inter[opsz,wght].ttf` (Regular: `wght=400 opsz=14`, Bold: `wght=700 opsz=32`), subset to Basic Latin + Latin-1 + common punctuation, with hinting and layout tables dropped. Regenerate them with fontTools (a dev-time tool only — the engine reads TrueType with the standard library):

```bash
fonttools varLib.instancer "Inter[opsz,wght].ttf" wght=700 opsz=32 -o bold.ttf
pyftsubset bold.ttf --unicodes="U+0020-007E,U+00A0-00FF,U+2013-2014,U+2018-201D,U+2022,U+2026,U+20AC" \
  --layout-features='' --no-hinting --desubroutinize \
  --drop-tables+=GPOS,GSUB,GDEF,kern,DSIG,STAT,fvar,gvar,avar,HVAR,MVAR --output-file=Inter-Bold.ttf
```

The reader supports exactly what these files use: TrueType outlines (`glyf`/`loca`, simple and composite glyphs), `cmap` format 4 and `hmtx`. A replacement font must be a TrueType-flavoured `.ttf` (not CFF/`.otf`). Changing a file changes every converted headline's path data, and the Ruby differential test pins those bytes — regenerate deliberately.
