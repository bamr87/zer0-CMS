# The zer0 stack

Three repositories, one contract each: a theme that renders, an image engine that draws, a CMS that edits. A content repository is aligned when it consumes each pillar through its contract and nothing else — no vendored forks, no copied generators. This page is zer0-CMS's side of that agreement: what it owns, the consumer contract `zer0 doctor` checks, the reusable workflow that runs it, and what zer0-CMS itself consumes from the other two. The image generator's side is its own `docs/ZER0-STACK.md`. The decisions were taken on 2026-09-14.

## The three pillars

| Pillar | Repo | Owns | A content repo consumes it as |
|---|---|---|---|
| Theme | [bamr87/zer0-mistakes](https://github.com/bamr87/zer0-mistakes) | layouts, includes, the front-matter contract (`.github/config/frontmatter_schema.yml`), the consumer kit (`templates/consumer/`), the consumer registry (`_data/consumers.yml`) | `remote_theme: bamr87/zer0-mistakes` (a floating ref is a deliberate posture in lifehacker.dev and it-journey; pinning stays the owner's call) |
| Image engine | [bamr87/zer0-image-generator](https://github.com/bamr87/zer0-image-generator) | the preview pipeline (the Python oracle and its pure-Ruby port under `lib/zer0_image_generator/`), the `preview_images:` config, the `jekyll preview-images` command, the web image forge, the design tokens | the `zer0-image-generator` gem in `group :jekyll_plugins` plus one `preview_images:` block — no vendored `_plugins/preview_*` forks, no copied Python or bash generators |
| CMS | [bamr87/zer0-CMS](https://github.com/bamr87/zer0-CMS) (this repo) | the Rails fleet CMS (`rails/`), the VS Code extension (`src/`), the stdlib content library (`rails/lib/zer0_cms/cms`), the consumer contract check (`zer0 doctor`), the `zer0.json` schema | a valid `zer0.json` (console dialect, with a `$schema` pointer) plus an optional report-only `zer0-doctor` workflow caller |

lifehacker.dev's Trace Bloom generator (`scripts/preview/`) is the one sanctioned exception: a deliberate offline style, recorded as a candidate to port upstream into the image engine, not a drifted copy of it.

## The consumer contract

A content repository is aligned when the doctor reports no errors:

```bash
ruby -I rails/lib rails/bin/zer0-cms doctor /path/to/site                    # a readable report
ruby -I rails/lib rails/bin/zer0-cms doctor /path/to/site --format findings  # one JSON finding per line
ruby -I rails/lib rails/bin/zer0-cms doctor /path/to/site --schema FILE      # another front-matter schema
```

It is stdlib Ruby (3.3 or newer) and needs no bundle. It exits 0 with no errors, 1 with any error, and 2 on bad usage. The checks are `Zer0Cms::Doctor` in `rails/lib/zer0_cms/doctor.rb`:

| Check | Error when | Warning when |
|---|---|---|
| `theme` | `_config.yml` is unreadable, or names neither `remote_theme: bamr87/zer0-mistakes` nor `theme: jekyll-theme-zer0` | no `.theme-overrides.yml` |
| `image-engine` | a vendored fork exists: `_plugins/preview_image_generator.rb`, `_plugins/preview_generator.rb` or `scripts/lib/preview_generator.py` | no `preview_images:` block; a Gemfile without the `zer0-image-generator` gem |
| `cms` | `zer0.json` is present but not valid JSON with comments, or names a content folder that does not exist | no `zer0.json`; no `$schema` |
| `fleet` | `fleet.manifest.yml` is present but not strict YAML | — |
| `distribution` | `zer0.json` `distribution.linkedin` names an author that is not a person or organization URN, a `Linkedin-Version` past LinkedIn's twelve-month support window, `acceptStatuses` outside pending and approved, or a path outside the repository; the ledger it names is not valid JSON | an unknown key, no author or site URL, a version within two months of sunset; a per-site LinkedIn publisher under `scripts/features/linkedin/` ([`DISTRIBUTION.md`](DISTRIBUTION.md)) |
| `content` | a file the catalog reads as content has front matter that does not parse | a key the theme's front-matter schema requires is missing (counted per rule) |

Findings use lifehacker.dev's `findings.jsonl` shape — `check_id`, `severity`, `file`, `line`, `rule`, `evidence`, `fingerprint` (the first 12 hex digits of SHA-1 over `check_id|rule|file|evidence`) — so the same triage tooling reads them. The front-matter schema is `--schema FILE` when given; otherwise the site's own `.github/config/frontmatter_schema.yml` when it has one, else the byte-identical copy of the theme's vendored at `rails/lib/zer0_cms/data/frontmatter_schema.yml` (its source commit is recorded beside it). Content warnings are report-only: the content repositories are on a content stand-down, and a missing key is a backlog item, not a gate. The `content` check reads a site with the same Jekyll 4.4 reader rules as the Rails index, so "a file the site publishes" means the same thing in both.

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

The workflow checks out the caller and `bamr87/zer0-CMS` at `main` side by side, runs the doctor on Ruby 3.3, writes a job summary (errors and non-content warnings as a table, content warnings counted per rule) and uploads the findings as the `zer0-doctor-findings` artifact. Callers trigger it on `workflow_dispatch` and a weekly schedule, never on `pull_request`: the caller cannot redden a pull request before this workflow exists on `main`, and a new doctor rule here cannot redden one afterwards.

## What zer0-CMS consumes

**The image engine.** The Rails app bundles `zer0-image-generator ~> 0.6` with `require: false`, and `app/services/image_engine.rb` is the only file that loads or runs it. It lists a site's missing previews (the `missing_preview:` filter) and draws one page's preview with the free `local` provider, writing the key back through `PageEditor` so the engine's own writer never has the last word. Against the released 0.6.0 gem it runs the gem's Python engine as the CLI would; when a release ships `Zer0ImageGenerator::Facade` (the first after 0.7.0), raise the Gemfile floor, re-lock, and the app uses the facade with no code change. Everything bigger than one page links out to the image generator's panel at `ZER0_IMAGE_GENERATOR_URL`. See [`PLATFORM.md`](PLATFORM.md#the-image-engine-seam).

**The design tokens.** `rails/app/assets/stylesheets/zer0-tokens.css` is a byte-identical copy of the image generator's `web/app/assets/stylesheets/zer0-tokens.css`, the `zer0-ui-tokens` kit (1.0.0 today; the stamp is its first comment line). Administrate is themed through it by `administrate-theme.css`. Never edit the copy: change the kit upstream, bump its version, and re-vendor; `cmp` is the whole check.

**The theme's contracts.** `rails/lib/zer0_cms/data/frontmatter_schema.yml` is the theme's front-matter schema, and `rails/lib/zer0_cms/data/abc_art_styles.yml` is the image generator's ABC art-style catalog; both are byte-identical vendored copies, re-synced rather than edited.

## Ports and compose

| App | Repo | Start | URL | Sites mount |
|---|---|---|---|---|
| Fleet CMS (admin, editor, ABC wizard) | zer0-CMS | `docker compose up --build` at the repo root | http://localhost:3001/admin | `${SITES_DIR:-..}:/sites` |
| Image generator (forge, runs, studio) | zer0-image-generator | `docker compose --profile imagegen up --build` here, or `docker compose up --build` in its own repo | http://localhost:3000 | `${SITES_DIR:-..}:/sites` |

- Both apps mount the same `SITES_DIR` at `/sites`, so a site registered as `/sites/<name>` means the same checkout in both. Register container paths, never host paths.
- The default `..` works when the repositories sit side by side in one fleet checkout; otherwise export `SITES_DIR` once (for example `export SITES_DIR=~/github`). The `imagegen` profile builds from `${ZER0_IMAGE_GENERATOR_DIR:-../zer0-image-generator}`.
- Both ports are published on 127.0.0.1 only. `PORT` moves the CMS and `IMAGEGEN_PORT` moves the image generator; point `ZER0_IMAGE_GENERATOR_URL` at the new address when you move it.
