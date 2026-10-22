# The zer0 stack

Three repositories, one contract each: a theme that renders, an image engine that draws, a CMS that edits. A content repository is aligned when it consumes each pillar through its contract and nothing else — no vendored forks, no copied generators. This page is zer0-CMS's side of that agreement: what it owns, the consumer contract `zer0 doctor` checks, the reusable workflow that runs it, and what zer0-CMS itself consumes from the other two. The image generator's side is its own `docs/ZER0-STACK.md`. The decisions were taken on 2026-09-14.

## The three pillars

| Pillar | Repo | Owns | A content repo consumes it as |
|---|---|---|---|
| Theme | [bamr87/zer0-mistakes](https://github.com/bamr87/zer0-mistakes) | layouts, includes, the front-matter contract (`.github/config/frontmatter_schema.yml`), the consumer kit (`templates/consumer/`), the consumer registry (`_data/consumers.yml`) | `remote_theme: bamr87/zer0-mistakes` (a floating ref is a deliberate posture in lifehacker.dev and it-journey; pinning stays the owner's call) |
| Image engine | [bamr87/zer0-image-generator](https://github.com/bamr87/zer0-image-generator) | the preview pipeline (the Python oracle and its pure-Ruby port under `lib/zer0_image_generator/`), the `preview_images:` config, the `jekyll preview-images` command, the web image forge, the design tokens | the `zer0-image-generator` gem in `group :jekyll_plugins` plus one `preview_images:` block — no vendored `_plugins/preview_*` forks, no copied Python or bash generators |
| CMS | [bamr87/zer0-CMS](https://github.com/bamr87/zer0-CMS) (this repo) | the Rails fleet CMS (`rails/`), the VS Code extension (`src/`), the platform (`content/`, with the Jekyll catalog and the consumer contract check `zer0 doctor` in `content/sites/`), the `zer0.json` schema | a valid `zer0.json` (console dialect, with a `$schema` pointer) plus an optional report-only `zer0-doctor` workflow caller |

lifehacker.dev's Trace Bloom generator (`scripts/preview/`) is the one sanctioned exception: a deliberate offline style, recorded as a candidate to port upstream into the image engine, not a drifted copy of it.

## The consumer contract

A content repository is aligned when the doctor reports no errors:

```bash
cd content
python -m sites.doctor /path/to/site                     # a readable report
python -m sites.doctor /path/to/site --format findings   # one JSON finding per line
python manage.py doctor --site KEY                       # a managed site's doctor job: its findings are kept
```

It is Python (the platform's, 3.12 or newer) with PyYAML and jsonschema, and needs neither Django nor Ruby. It exits 0 with no errors, 1 with any error, and 2 on bad usage. The checks are `content/sites/doctor.py` (PLAN G4 ported them from the Ruby `rails/bin/zer0-cms doctor`, and the studio's Sites area runs them as a job):

| Check | Error when | Warning when |
|---|---|---|
| `config` | `_config.yml` is unreadable, does not parse, or is not a mapping | — |
| `image-engine` | a vendored fork exists: `_plugins/preview_image_generator.rb`, `_plugins/preview_generator.rb` or `scripts/lib/preview_generator.py` | no `preview_images:` block; a Gemfile without the `zer0-image-generator` gem |
| `cms` | `zer0.json` is present but not valid JSON with comments, or names a content folder that does not exist | no `zer0.json`; no `$schema`; it breaks `schemas/zer0.schema.json` |
| `fleet` | `fleet.manifest.yml` is present but not strict YAML | — |
| `distribution` | `zer0.json` `distribution.linkedin` names an author that is not a person or organization URN, a `Linkedin-Version` past LinkedIn's twelve-month support window, `acceptStatuses` outside pending and approved, or a path outside the repository; the ledger it names is not valid JSON | an unknown key, no author or site URL, a version within two months of sunset; a per-site LinkedIn publisher under `scripts/features/linkedin/` ([`DISTRIBUTION.md`](DISTRIBUTION.md)) |
| `content` | a file the catalog reads as content has front matter that does not parse | a field its content type in `zer0.json` marks `required` is empty (counted per rule) |

Findings use lifehacker.dev's `findings.jsonl` shape — `check_id`, `severity`, `file`, `line`, `rule`, `evidence`, `fingerprint` (the first 12 hex digits of SHA-1 over `check_id|rule|file|evidence`) — so the same triage tooling reads them. A required field is one the site's own content types declare (`zer0.json` `contentTypes[].fields[]` with `required: true`, the type resolved per file as the extension resolves it — the file's `type`, its folder's one bound type, the only type, the type named `default`); a site with no `zer0.json` has none. Content warnings are report-only: the content repositories are on a content stand-down, and a missing key is a backlog item, not a gate. The `content` check reads a site with the platform's one Jekyll 4.4 reader (`content/sites/catalog.py`, held to Jekyll's own lists), the one its sync uses, so "a file the site publishes" means the same thing in both.

**What the Ruby doctor checked and this one does not** (ADR 0006 decision 4: the theme leaves this repository, and no doctor rule may name it): the `theme` check's `theme-not-zer0` error (a `_config.yml` naming neither the theme's `remote_theme` nor its gem) and its `no-theme-overrides` warning, and the theme's front-matter schema behind `missing-key:*` (the vendored copy, a site's own copy, `--schema`). The `theme` check's generic rule, `config-unreadable`, is now the `config` check's. Every other rule is the Ruby doctor's word for word, held to its recorded findings by `content/tests/sites/test_doctor.py`; only a YAML or JSON syntax error's evidence is worded by the Python parser.

## Running the doctor in CI

`.github/workflows/zer0-doctor.yml` is a reusable workflow. A content repository calls it without vendoring anything:

```yaml
name: zer0-doctor
on:
  workflow_dispatch:
  schedule:
    - cron: "17 6 * * 1"
permissions:
  contents: read
jobs:
  doctor:
    uses: bamr87/zer0-CMS/.github/workflows/zer0-doctor.yml@main
    with:
      site-path: "."
      fail-on-error: false
```

| Input | Default | Meaning |
|---|---|---|
| `site-path` | `.` | The Jekyll root, relative to the caller repository; an absolute path or one that climbs out of the checkout fails the job |
| `fail-on-error` | `false` | Fail the job when the doctor reports an error; otherwise the run is report-only |

The workflow checks out the caller and `bamr87/zer0-CMS` at `main` side by side, runs the doctor on Python 3.13, writes a job summary (errors and non-content warnings as a table, content warnings counted per rule) and uploads the findings as the `zer0-doctor-findings` artifact. Callers trigger it on `workflow_dispatch` and a weekly schedule, never on `pull_request`: the caller cannot redden a pull request before this workflow exists on `main`, and a new doctor rule here cannot redden one afterwards.

## What zer0-CMS consumes

**The image engine.** The Rails app bundles `zer0-image-generator ~> 0.6` with `require: false`, and `app/services/image_engine.rb` is the only file that loads or runs it. It lists a site's missing previews (the `missing_preview:` filter) and draws one page's preview with the free `local` provider, writing the key back through `PageEditor` so the engine's own writer never has the last word. Against the released 0.6.0 gem it runs the gem's Python engine as the CLI would; when a release ships `Zer0ImageGenerator::Facade` (the first after 0.7.0), raise the Gemfile floor, re-lock, and the app uses the facade with no code change. Everything bigger than one page links out to the image generator's panel at `ZER0_IMAGE_GENERATOR_URL`. See [`PLATFORM.md`](PLATFORM.md#the-image-engine-seam).

**The design tokens.** `rails/app/assets/stylesheets/zer0-tokens.css` is a byte-identical copy of the image generator's `web/app/assets/stylesheets/zer0-tokens.css`, the `zer0-ui-tokens` kit (1.0.1 today; the stamp is its first comment line). Administrate is themed through it by `administrate-theme.css`. Never edit the copy: change the kit in `packages/zer0-image-generator`, bump its version, and re-vendor with `bin/zer0 vendor --write`; `bin/zer0 check` fails CI while the two differ.

**The theme's contracts.** `rails/lib/zer0_cms/data/frontmatter_schema.yml` is the theme's front-matter schema, and `rails/lib/zer0_cms/data/abc_art_styles.yml` is the image generator's ABC art-style catalog; both are byte-identical vendored copies, re-synced rather than edited.

## Ports and compose

| App | Repo | Start | URL | Sites mount |
|---|---|---|---|---|
| Fleet CMS (admin, editor, ABC wizard) | zer0-CMS | `docker compose up --build` at the repo root | http://localhost:3001/admin | `${SITES_DIR:-.}:/sites` |
| Image generator (forge, runs, studio) | zer0-image-generator | `docker compose --profile imagegen up --build` here, or `docker compose up --build` in `packages/zer0-image-generator` | http://localhost:3000 | `${SITES_DIR:-.}:/sites` |

- Both apps mount the same `SITES_DIR` at `/sites`, so a site registered as `/sites/<name>` means the same checkout in both. Register container paths, never host paths.
- The default `.` is this repository: the CMS discovers the zer0 sites the monorepo holds (`/sites/sites/drsai`, `/sites/sites/zer0-pages`, …) with no setup. To manage repositories that live outside it, export `SITES_DIR` once (for example `export SITES_DIR=~/github`). The `imagegen` profile builds from `${ZER0_IMAGE_GENERATOR_DIR:-./packages/zer0-image-generator}`.
- Both ports are published on 127.0.0.1 only. `PORT` moves the CMS and `IMAGEGEN_PORT` moves the image generator; point `ZER0_IMAGE_GENERATOR_URL` at the new address when you move it.
