# Audit fixtures — where each file came from

Two kinds of file live here, and the difference matters.

**Verbatim copies** under `schemas/` are somebody else's file, byte for byte. They are what `schemaFromFrontmatterSchemaYml` and `schemaFromCmsConfig` are tested against, because a schema reader tested against a schema we wrote ourselves proves only that we can read our own handwriting. Never hand-edit one — re-copy it from the origin path below and note the new commit.

| staged as | origin repo | origin path | commit |
|---|---|---|---|
| `schemas/zer0-mistakes/frontmatter_schema.yml` | bamr87/zer0-mistakes | `.github/config/frontmatter_schema.yml` | 96776fa4 |
| `schemas/it-journey/cms-config.yml` | bamr87/it-journey | `.cms/config.yml` | e17040d3 |
| `schemas/it-journey/content-schema.json` | bamr87/it-journey | `.cms/schema/content-schema.json` | 7f2cba7d |

**Everything else is a purpose-built miniature site** — `zer0.json`, `.github/config/frontmatter_schema.yml`, `.cms/`, and the pages under `pages/_posts/`. It exists so `auditSite` can be run once over a real tree and every rule id checked against the one file that triggers it. Each page's filename says which rule it is for, and `2026-01-01-clean.md` is the control: it must keep producing exactly zero findings, or the suite is measuring noise instead of rules.

The `schemas/` copies are deliberately *outside* the site's own `.github/` and `.cms/` so that reading them is an explicit act in a test, and the site's merged schema stays the small one written for this fixture.

Nothing here is ever written to. `dryRunFix` renders a preview and the suite snapshots this whole tree before and after to prove it.
