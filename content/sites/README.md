# `sites/` — the sites the platform manages

Every site the platform manages, its generated file tree, and keeping the two in step — PLAN G4, TARGET.md § Sites — Manage, ADR 0006 decisions 8 and 13. It absorbs the Rails fleet CMS's catalog, front-matter surgery, confined writer, `SiteSync`, `PageEditor` and the Ruby `zer0 doctor`, and is what the studio's Sites area works with.

| Module | What it is |
|---|---|
| `models.py` | `ManagedSite`: a Wagtail `Site` plus its checkout (the generated file tree), `content_source` (`files`: people still edit the files and sync brings them in; `platform`: the files are generated), how it renders (`react`, or `jekyll-theme` with the theme's tag and the Jekyll server — the setting PLAN P2 put in workspace.yml), domains, deploy target, when it was last synced, written back and checked, the digest of each content file as the platform last read or wrote it, and the last doctor run's findings. `SiteSettings`: per-site settings through `wagtail.contrib.settings` — SEO defaults, analytics ids, navigation, brand voice, skin and design tokens, a monthly budget |
| `access.py` | Who sees a site (its root page is one the studio shows them) and who manages it (also `sites.manage_site`) |
| `catalog.py` | The Jekyll 4.4 reader rules, ported from the Rails catalog: which files are pages, posts, drafts and documents. `tests/sites/test_catalog.py` holds it to the lists Jekyll 4.4.1's own reader produced for the fixture sites, byte for byte. The importer reads sites through it, so the platform has one Jekyll reader |
| `frontmatter.py` | Front-matter line surgery: `update_keys` rewrites only the lines a change touches — comments, quoting, list style, CRLF, a BOM and a `...` fence survive — and verifies every edit by reading it back. The exporter renders a changed page over its original file with it |
| `writer.py` | The confined writer: plain relative paths only, no symlink at any component (`lstat`), realpath inside the root; O_EXCL for a new file; an atomic replace that compares the bytes again right before the rename; file-name slugs |
| `doctor.py` | zer0 doctor: config, image engine, cms, fleet, distribution and content checks as findings (`findings.jsonl`). Its docstring says what changed from the Ruby doctor and why (the theme's rules are gone) |
| `services.py` | Registering and discovering sites, changing them, and the work of their jobs: `sync`, `export` (the write-back) and `doctor` |
| `views.py`, `serializers.py`, `urls.py` | `/api/v2/sites/` |

None of `catalog.py`, `frontmatter.py`, `writer.py` and `doctor.py` imports Django: `python -m sites.doctor PATH [--format findings]` (from `content/`) is what `bin/zer0 doctor` and the reusable `zer0-doctor.yml` run, with PyYAML and jsonschema.

## Sync and write-back

**Sync** is `importers.jekyll.import_site` as a job: the catalog's files become pages; a file changed by hand updates its page unless the page changed here since (a conflict, reported, never overwritten — `force` takes the file). The digest of each file read is recorded on the site — an ABC book's spec sidecar (`_data/abc_books/<slug>.json`, read with its page, `../books/README.md`) too. A page is live exactly when the catalog says the site builds its file (`Entry.live`): a draft (`published: false`, `draft: true`, `status: draft`, `_drafts/`) is a draft page, never published, and a file dated in the future is scheduled for its date unless `_config.yml` sets `future: true`; a changed file moves its page with it, an unchanged one never does.

**Write-back** (`export`) writes what `exporters.jekyll.site_files` renders — the live pages, or the latest revisions with `include_drafts` — into the checkout under the stale-write guard of the Rails `PageEditor`:

- a file is written only while its bytes on disk still have the digest the platform last read or wrote there, and — when the job names one (`base`, `{path: digest}` as the caller saw it) — while that is still the indexed digest; the bytes are compared again right before the atomic rename;
- a file whose rendering equals what is on disk is not written at all, so a write-back with nothing to do writes nothing;
- a file changed (or deleted) by hand since is a conflict and stays as it is: sync first;
- a page is never written into another page's file (a new page whose slug lands on a draft's file name, say): a conflict;
- the file of a page deleted here is removed while it is unchanged since, and an ABC book's sidecar stays while its page does;
- a page that is not live — never published, unpublished or expired — reaches its file as not built: Jekyll's own switch, `published: false` (the file stays, Jekyll skips it), goes in before the closing fence, unless the file already keeps itself out of the build in the site's own way (`catalog.held_back`: `published: false`, `draft: true`, `status: draft`, a draft in `_drafts/` or a future date — the reader's own rules, so such a file exports byte for byte); a page that goes live again loses only the marker the platform added (`exporters.jekyll.mark`);
- every write-back covers the pages that are not live, not only one with `include_drafts`: a file without the marker is live on the site, so a take-down that waited for "drafts too" would leave an unpublished page built after every ordinary write-back. A write-back of the live pages writes only the marker onto the file as the platform last read or wrote it — never a draft's content, and never a new file (a page with no file yet, or moved since, has nothing to take down there) — and with `include_drafts` the latest revision is written, marked;
- a changed page is rendered over its original file by line surgery, so only the keys and the body that changed move.

What a write-back writes is recorded both ways, the digest on the site and the text on the page's `ImportedSource` (an ABC book's sidecar in its `sidecars`), so the next sync sees the platform's own file and the next write-back writes it verbatim.

## The API

| Path | What |
|---|---|
| `GET /api/v2/sites/` | The sites the caller sees (the studio's site switcher, since P4), each with `managed` (its registry entry, or null) and `can_manage` |
| `POST /api/v2/sites/` | Register a checkout — inside the repository or `SITES_DIR` — as a site; its first sync starts (201 with the site and the job) |
| `GET /api/v2/sites/discover/` | What could be registered: workspace.yml's sites (with their `render:` setting) and the Jekyll roots one or two levels under `SITES_DIR` |
| `GET`/`PATCH /api/v2/sites/<id>/` | A site: its registry entry, page counts, files and latest jobs; change its content source, renderer, theme tag, Jekyll server, domains, deploy target |
| `GET`/`PATCH /api/v2/sites/<id>/settings/` | Its settings |
| `GET /api/v2/sites/<id>/findings/` | The last doctor run's findings, `?severity=`, `?check=` |
| `POST /api/v2/sites/<id>/sync/`, `export/`, `doctor/` | Start a job (202 with it; `Idempotency-Key`); follow it at `/api/v2/jobs/<id>/` (jobs/README.md) |

Commands: `manage.py doctor PATH [--format findings]` (or `--site KEY`, recorded), `manage.py site_job sync|export|doctor --site KEY`. Setting: `SITES_DIR` (environment), where checkouts outside this repository may be registered from — unset, only the repository's own sites can be; compose mounts it at `/sites`, writable for the worker that runs the jobs. Tests: `tests/sites/`.

## Not here yet

Building a site with the Jekyll-theme option as a job (its build needs the Jekyll server, a container the worker does not start — `pages.yml` builds it), deploy, and preview are later work (`sites.render-jekyll`, `sites.deploy` in docs/plan/capabilities.yml); so is a hand edit to a generated file arriving as a suggestion rather than a conflict (ADR 0006 decision 13).
