# `lib/zer0_cms/data/` — bundled data

| File | Source | Used by |
|---|---|---|
| `abc_art_styles.yml` | this repository | `Zer0Cms::Abc::ArtStyles` |
| `frontmatter_schema.yml` | vendored byte-identically from `bamr87/zer0-mistakes` `.github/config/frontmatter_schema.yml` at commit `4349ea17d690e5e6b8585f1d3a33b3ea4d3bf4fe` (file last changed in `96776fa48bbe7b63058d1d246962019c745d7b93`) | `Zer0Cms::Doctor` — the theme's front-matter contract; a site's own `.github/config/frontmatter_schema.yml` wins when present, and `--schema FILE` wins over both |

Refresh the schema by copying the theme's file unchanged and updating the commit above; never edit the vendored copy here — fix the contract upstream in zer0-mistakes.
