# The Rails CMS: what the platform still owes

> What the deleted Rails fleet CMS (`rails/`) did that the platform does not do yet — one section per open capability, with what Rails did, where the platform stands and what to build — so the code could go while its behaviour stays specified.

The owner deleted `rails/` on 2026-10-27 ([ADR 0008](../adr/0008-retire-the-rails-cms.md)), after merging the branches that had already ported most of it: G4 (`overhaul/sites-jobs` at `61213c00`: the catalog, front-matter surgery, the confined writer, the site registry, sync, write-back and the doctor) and G5 (`overhaul/distribution` at `4eede020`: channels, the queue, the LinkedIn lane and statistics). Each section below is a row of [`capabilities.yml`](capabilities.yml) with status `specified`: its source is gone, its behaviour is here, and its platform target still owes it. The milestone that builds one sets the row `done` with a test as its proof and removes the section.

Reading the sections: Rails paths are relative to `rails/` at `d0a572fb`, the last commit that has them (`git show d0a572fb:rails/<path>`). **main** means `main` at `d0a572fb`, before the merges; **G4** and **G5** mean code those branches brought in. Every platform test named was found by name when this was written; the tests under **Build** are to be written.

| Row | Platform target | Where it gets built |
|---|---|---|
| [`rails.site-registry`](#railssite-registry) | `sites.registry` | G4's open items |
| [`rails.page-search`](#railspage-search) | `content.list` | P4 |
| [`rails.page-create`](#railspage-create) | `content.create` | P4; the file side with G4's write-back |
| [`rails.writer`](#railswriter) | `sites.sync` | with `rails.page-create` |
| [`rails.assets-terms`](#railsassets-terms) | `media.library` | G6; the terms with P4 |
| [`rails.markdown-preview`](#railsmarkdown-preview) | `content.preview` | P4 |
| [`rails.missing-previews`](#railsmissing-previews) | `media.generate` | G6 |
| [`rails.access-guard`](#railsaccess-guard) | `platform.ops` | a test (G11) |
| [`rails.parity-tools`](#railsparity-tools) | `content.import` | before the Jekyll fixtures are next re-recorded |
| [`rails.abc-wizard-ui`](#railsabc-wizard-ui) | `books.abc` | G9 |
| [`rails.abc-generator`](#railsabc-generator) | `books.abc` | G9 |

Already absorbed, with their proofs in the ledger: `rails.page-edit`, `rails.catalog`, `rails.front-matter`, `rails.doctor` and `workspace.doctor` (G4); `rails.distribution-queue`, `rails.channels`, `rails.linkedin` and `rails.linkedin-stats` (G5); `rails.events` (main's contract tests: the outbox envelope and every event schema, `app.user.interaction` included).

## rails.site-registry

**Did** (`app/models/site.rb`, `app/controllers/admin/sites_controller.rb`, `app/dashboards/site_dashboard.rb`, `app/views/admin/sites/{index,show}.html.erb`, `app/services/site_sync.rb`; tests `test/integration/site_sync_test.rb`, `test/integration/admin_routes_test.rb`)

- Register a site by name and absolute path. The path is stored as its realpath, so two spellings of one root cannot both register ("has already been taken"). Refusals, each with its message: the path is not absolute ("must be an absolute path (in Docker, sites live under /sites)"); it is not a directory ("check the volume mount"); it is outside `SITES_DIR` when `SITES_DIR` is set ("must be inside SITES_DIR (…)"); it has no `_config.yml` ("is this a Jekyll site root?"). Creating a site syncs it at once. A sync failure keeps the registration and flashes "registered, but the sync failed: …".
- `SITES_DIR` comes from the environment, or is `/sites` inside Docker. When it is unset, any absolute path may be registered.
- Discover: lists the Jekyll roots (directories holding `_config.yml`) one or two levels under `SITES_DIR` that are not registered yet. Each is realpathed, deduplicated, kept only if it is strictly inside `SITES_DIR`, and sorted. The sites index shows them in a card ("N Jekyll roots with a _config.yml") with a **Register and sync all** button, which registers each under its basename and syncs it, then flashes "Registered a, b and c." or "No unregistered sites under …". When `SITES_DIR` is unset the card says "SITES_DIR is not set: register a site by its absolute path."
- Sites list: name, path, page count, image count, last synced, sorted by name. Filters: `unsynced:` (never synced) and `failing:` (has a `sync_error`).
- Site page shows path, `source:` subdir, `collections_dir`, page and image counts, last synced and the last sync error (as an alert, "Last sync failed: …").
- **Collections** table: one row per collection with its page count and draft count. Drafts are `draft: true` or `status: draft`. Each collection links to the page list filtered `site:<id> collection:<name>`. With no rows it says "Not synced yet — press Sync" or "No content files".
- **`_config.yml (read-only)`**: the raw file through `SitePath` (no symlink at any component, a regular file, realpath inside the root). Reads at most 256 KiB as UTF-8, with invalid bytes scrubbed. When the file cannot be read it says "_config.yml is missing or not a regular file".
- Buttons: Sync (flashes "Synced N pages, N images, N terms." or "Sync failed: …"), New page (in this site), Missing previews (the `missing_preview:` filter), Image generator ↗, Edit, **Remove from index**.
- Remove from index: a Turbo confirm, then "Removed from the index. No file on disk was touched." Rows are deleted; files stay.
- Edit: name and path can be changed. A changed path re-syncs.
- Sync failures (an unsafe `source`/`collections_dir`, an OS error) record `sync_error` and `last_synced_at` on the site.

**Platform today**

- G4 `content/sites/{models,services,views,serializers}.py` provide:
  - `POST /api/v2/sites/`: register a checkout inside the repository or `SITES_DIR` (realpath, `_config.yml`, readable YAML); its first sync starts as a job.
  - `GET /api/v2/sites/discover/`: workspace.yml's sites plus Jekyll roots one or two levels under `SITES_DIR`, less those registered.
  - `GET/PATCH /api/v2/sites/<id>/`: content source, renderer, theme tag, server, domains, deploy target. The overview counts pages as total, live and drafts.
  - Settings, findings, and the sync, export and doctor jobs.
- G4 studio: `web/packages/ui/src/sites/{SitesWorkspace,SiteView,JobLog}.tsx` (registry, register one, overview, settings, findings, jobs).
- Tests (G4): `content/tests/sites/test_sites.py::test_registering_a_checkout_makes_the_site_and_syncs_it`, `::test_a_checkout_must_be_a_jekyll_site_inside_the_repository_or_sites_dir`, `::test_discover_lists_the_workspace_sites_not_yet_registered`, `::test_the_list_carries_what_the_platform_manages`, `::test_seeing_a_site_is_not_managing_it`; `web/packages/ui/test/sites.test.tsx` ("lists every site with how it renders…", "registers a checkout the workspace declares and opens the new site").
- Missing:
  - per-collection counts;
  - the read-only `_config.yml` (`SiteRootPage.jekyll_config` keeps only the keys the bridge reads, not the text);
  - register-all;
  - detach (remove from the registry, files untouched);
  - changing a site's checkout path or name;
  - showing `source`/`collections_dir`.
- Untested: a positive test that a `SITES_DIR` root (not a workspace.yml site) is discovered, and a test that a second spelling of a registered checkout is refused.

**Verdict:** specified.

**Build**

- API:
  - Add `collections: [{collection, pages, drafts}]` to `GET /api/v2/sites/<id>/`. Count `BasePage` descendants of each `CollectionPage` of the site; drafts are status `draft`. Add a `(pages)` row for pages under no collection.
  - Add `source` and `collections_dir` from `SiteRootPage.jekyll_config`.
  - `GET /api/v2/sites/<id>/config/` returns `{text, truncated}`. Read `_config.yml` through `sites.writer.confined_file` (no symlink, regular file), at most 262,144 bytes, decoded as UTF-8 with replacement. A missing or refused file is a 404 envelope, "_config.yml is missing or not a regular file". Visible to whoever sees the site.
  - `PATCH /api/v2/sites/<id>/` also takes `checkout`, re-validated by `resolve_checkout` and unique; a changed checkout starts a sync. It also takes `name` (the Wagtail `Site.site_name`).
  - `DELETE /api/v2/sites/<id>/managed/` detaches the checkout: it deletes the `ManagedSite` row only. The Wagtail site, its pages and every file stay. Needs `sites.manage_site`; 409 while a job of the site is queued or running.
- Studio (`SiteView` Overview, `SitesWorkspace`):
  - A "Collections" table with pages and drafts, each collection linking to Write's page list filtered `site:<id> collection:<name>` (see rails.page-search).
  - A collapsible read-only "_config.yml" code block.
  - Show source and collections dir.
  - A "Register all (N)" button over the discovered candidates, which registers each and lists every refusal with its message.
  - "Detach from its checkout" with a confirm dialog saying no file or page is touched.
  - Checkout and name editable in the registry form.
  - The list badges "never synced" and "last sync failed", the latter from the latest sync job's status. That replaces `unsynced:`/`failing:`.
- Extension: by construction in G10 (the `@zer0/ui` Sites components render in the webview); no file-mode counterpart.
- Tests (re-expressing `site_sync_test.rb` and `admin_routes_test.rb`):
  - `content/tests/sites/test_sites.py::test_the_overview_counts_pages_and_drafts_per_collection`: on the moved fixture `content/tests/fixtures/jekyll-site`, counts equal the catalog's `by_collection`.
  - `::test_the_config_is_shown_read_only_and_never_through_a_symlink`: the text contains `collections_dir: pages`; a symlinked `_config.yml` gives 404.
  - `::test_discover_lists_unregistered_roots_under_sites_dir_only`: copy a second fixture under `SITES_DIR`; it is listed, and a root outside is not.
  - `::test_a_checkout_registered_twice_by_another_spelling_is_refused`: `<parent>/./site`.
  - `::test_changing_the_checkout_resyncs_and_detaching_touches_nothing`.
  - `web/packages/ui/test/sites.test.tsx`: "shows each collection's pages and drafts and opens the filtered list", "registers every discovered site and lists the refusals".
- Milestone: G4 (its open items: "per-collection counts and the read-only `_config.yml` view").

## rails.page-search

**Did** (`app/dashboards/page_dashboard.rb` `COLLECTION_FILTERS`, `app/services/dashboard_search.rb`, `app/controllers/admin/{application,pages}_controller.rb`, `app/models/page.rb`, `app/fields/state_field.rb`; tests `test/integration/admin_routes_test.rb`)

- One search box. Whitespace-separated words of the form `name:` or `name:value`, where `name` is a known filter, narrow the list; every other word is free text. Administrate's parser cannot express a value with spaces, so a term with whitespace fell back to text search (`Term#pages_search`). An unknown `name:` is ignored.
- Free text: case-insensitive substring (SQL `LIKE %term%`, lowercased with `String#downcase`) over title, description, author and source path, combined with OR.
- Filters:
  - `draft:`: `draft: true`, a file in `_drafts/`, or front matter `status: draft`.
  - `live:`: not draft, `published` not false, date not in the future, and `status` ≠ draft.
  - `future:`: date later than the sync time.
  - `error:`: the front matter did not parse, or the file is not valid UTF-8. The file is still indexed, with its error.
  - `collection:<name>`, `site:<id>`, `kind:<page|post|draft|document>`, `author:<name>` (exact).
  - `tag:<name>` and `category:<name>`: exact element of the JSON list.
  - `missing_preview:[site]`: see rails.missing-previews.
- Filters AND together and with the text.
- Each row's state badge is one of error, draft, unpublished (`published: false`), future or live, in that precedence.
- Columns: title, collection, kind, state, date, site.
- Sort: date, newest first, undated last.
- 50 per page by default; `per_page` up to 200.
- A term's page links to "Pages with this tag/category/author": `site:<id> tag:<name>`, or text when the name has whitespace.
- Edge: a search with no text and only filters matches everything (`LIKE '%%'`).

**Platform today**

- main `content/api/pages.py` `PageFilter` on `GET /api/v2/content/pages/`:
  - `site`, `parent`, `type`, `status` (draft, live, changed, scheduled, expired), `q` (title, draft title, slug), `can_have_children`;
  - ordering by `title`, `latest_revision_created_at`, `last_published_at`, `path`, nulls last;
  - 25 per page, at most 100.
- Studio `web/packages/ui/src/PageList.tsx`: Status and Type selects, search box, tree walk.
- Tests (main): `content/tests/api/test_pages.py::test_the_page_list_spans_every_status_and_filters`, `::test_a_page_without_a_revision_sorts_last_and_wagtails_placeholder_is_no_page`; `web/packages/ui/test/editor.test.tsx` ("lists pages, walks into the tree, and filters by status through the platform").
- MCP: `content.search` (read).
- After G4's import the data is there:
  - collection: the parent `CollectionPage.collection`;
  - kind: `ArticlePage` for posts and dated documents, `StandardPage` otherwise, and `BasePage.legacy_path` holding `_drafts/`;
  - `ArticlePage.tags`, `ArticlePage.categories` (`cms.Category`) and `ArticlePage.author`.
- Missing:
  - no `collection`, `kind`, `tag`, `category`, `author`, `future` or `error` filter;
  - `q` misses description, author and source path;
  - no sort by content date;
  - no typed filter language.
- Unreadable files never become pages. They appear only as job log lines and the job result's `errors` count (G4 `content/sites/services.py::run_sync`).

**Verdict:** specified.

**Build**

- API (`api/pages.py` `PageFilter` and `PageSummarySerializer`):
  - `collection` (name): descendants of the site's `CollectionPage` with that `collection`.
  - `kind`: `page` (no `CollectionPage` ancestor), `post` (collection `posts`, `legacy_path` not under `_drafts/`), `draft` (`legacy_path` under a `_drafts/` directory), `document` (any other collection). Any other value is a 422 envelope naming the field.
  - `tag`: `ArticlePage.tags__name__iexact`; may repeat, and repeats AND together.
  - `category`: `Category` name or slug, case-insensitive; may repeat, AND.
  - `author`: exact `ArticlePage.author` or `BookPage.author`.
  - `future=true`: `ArticlePage.date` > now, any status.
  - `live=true`: maps to `live` (status `live` or `changed`).
  - `site` also accepts the managed site key.
  - `q` also searches `search_description`, `ArticlePage.author` and `legacy_path`.
  - `ordering=date` / `-date`: content date, nulls last. `-date` is what the filter language sorts by unless told otherwise.
  - Summary gains `collection`, `date`, `site_id`.
  - `error:` is not a page filter. Sync records each unreadable file as a finding with `check: "sync"`, `rule: "unreadable-file"`, `file`, and the reader's message as evidence. They are stored beside the doctor's findings on `ManagedSite` and replaced by each sync. `GET /api/v2/sites/<id>/findings/?check=sync` lists them.
  - The `content.search` tool takes the same filters (mcp surface).
- Studio:
  - A pure parser `parsePageQuery(text)` in `@zer0/ui` (shared with the extension).
  - Tokens: whitespace splits except inside double quotes; `key:` or `key:value` (or `key:"two words"`) with key in {draft, live, future, error, collection, site, kind, tag, category, author, missing_preview}. Anything else, unknown keys included, is free text joined into `q`. Repeated `tag:`/`category:` accumulate; other keys take the last value.
  - Parsed filters show as removable chips beside the existing selects and are kept in the URL.
  - The list adds Collection and Date columns.
  - `error:` (with a site) shows the site's "files that did not import" from the findings, linking to Sites → Findings.
  - Every tag, category and author shown on a page links to the list filtered by it, which replaces the Terms "Pages with this …" link.
- Extension: by construction in G10. The file-mode page index (`src/core/content/pageIndex.ts`) keeps its own filters until then.
- Owner decisions:
  - Rails counted `status: draft` (5 files: 3 in `sites/irony-works`, 2 in `sites/zer0-pages`) as a draft and excluded future-dated posts from `live:`. The importer (`importers/jekyll.py::_is_draft`) publishes both. Decide whether import maps `status: draft` → draft and a future date → scheduled (`go_live_at` = date), or whether `future=true` and a `status` front-matter view suffice.
- Tests (re-expressing `admin_routes_test.rb` on `content/tests/fixtures/jekyll-site`, imported with `import_site`):
  - `content/tests/api/test_pages.py::test_filters_narrow_the_list_to_exactly_the_matching_pages`: draft, live, future, collection=docs, tag=fixture → exactly `pages/_posts/2026-01-01-hello.md`; plus kind, category and author; each against a queryset computed independently.
  - `::test_text_matches_title_description_author_and_source_path`: `outside-collections` matches by path, `Hello` by title.
  - `::test_ordering_by_date_puts_undated_pages_last`.
  - `content/tests/sites/test_sites.py::test_unreadable_files_are_sync_findings`: `test_front_matter_errors_are_recorded_not_raised`'s file reaches `findings?check=sync`.
  - `web/packages/ui/test/pagequery.test.ts`: the parser table, including quoted values, unknown keys as text and repeated tags.
  - `web/packages/ui/test/editor.test.tsx`: "filters by a typed query and shows the filters as chips".
- Milestone: P4 (content.list: "tag/category/author/errors filters to come"), built on G4's importer.

## rails.page-create

**Did** (`app/controllers/admin/pages_controller.rb` `new`/`create`/`duplicate`/`destroy`, `app/views/admin/pages/new.html.erb`, `app/services/page_editor.rb` `duplicate!`/`destroy!`, `app/models/site.rb#writable_collections`, `app/services/site_path.rb`, `lib/zer0_cms/cms/writer.rb`; tests `test/integration/page_editing_test.rb`, `test/zer0_cms/test_writer.rb`)

- **New page**: pick a site, then a form.
  - Collection: only declared collections whose directory exists and is not a symlink, excluding `data`; `posts` is selected by default.
  - Section: an existing subdirectory of that collection, at most 2 levels deep, each segment matching `[A-Za-z0-9][A-Za-z0-9_-]*`, no symlinks.
  - Title (required), slug (optional; derived from the title), description, author, tags (comma-separated), **Draft** (checked by default), and a body with live Markdown preview.
  - The file is `YYYY-MM-DD-<slug>.md` for posts (today's date) and `<slug>.md` otherwise. Front matter is `title`, `date`, then description, author, tags and `draft: true` when given, with YAML-rule quoting. A body that looks like front matter is kept as body. CRLF becomes LF, a leading newline is stripped, and a trailing newline is ensured.
  - Created with O_EXCL. An existing file or planted symlink is "already exists" or `UnsafePath`; never followed or overwritten. The path is re-synced, then the editor opens on the new page.
  - Refusals re-render the form (422) with the message: "unknown collection", "collection has no directory", "invalid section", "section does not exist", "invalid slug … use a-z, 0-9 and single hyphens".
  - A site with no writable collection says "declares no collection with a directory on disk".
- **Duplicate as draft**: `<stem>-copy.md` beside the original, then `-copy-2` … up to 1000.
  - Title "<title> (copy)"; the title falls back to the file stem.
  - `draft: true` added; `permalink`, `redirect_from` and `preview` removed, so the copy cannot claim the URL, redirects or banner. Every other line is byte-identical (line surgery); the original is unchanged.
  - A symlinked source, or one resolving outside the root, is refused.
  - The edit form of the copy opens. When Jekyll would not read the copy as content it says "Duplicated; Jekyll does not read the copy as content."
- **Delete**: a Turbo confirm. Refused (and the file kept) when the file changed since the last sync. The file is unlinked through `SitePath` (no symlink component, regular file, realpath inside) and the row removed. Flashes "Deleted <path>."

**Platform today**

- Create (main):
  - `POST /api/v2/content/pages/` (parent, type, fields, body) makes one draft revision and publishes nothing. Tested by `content/tests/api/test_pages.py::test_creating_a_page_makes_one_draft_revision_and_publishes_nothing` and `::test_creatable_types_follow_the_tree_rules_and_permissions`.
  - Studio `web/packages/ui/src/CreatePage.tsx` (parent, type, title, optional brief and drafter): `web/packages/ui/test/create.test.tsx` "creates a draft and starts no run once the brief’s topic is cleared".
- The file (G4): `exporters/jekyll.py::path_for` gives a new page in `_posts` `<collections_dir>/_posts/YYYY-MM-DD-<slug>.md`, other collections `<collections_dir>/_<c>/<slug>.md`, and the root `<slug>.md`, with the slug transliterated by `sites.writer.slugify`. The write-back creates it O_EXCL, confined, and never over another page's file:
  - `content/tests/sites/test_sites.py::test_a_new_page_gets_a_file_and_the_job_says_so`
  - `::test_a_new_page_never_takes_another_pages_file`
  - `content/tests/sites/test_writer.py::test_a_new_file_is_created_once_and_never_through_a_planted_symlink`
  - `::test_a_directory_symlinked_away_is_refused_and_nothing_lands_outside`
  - `::test_only_plain_relative_paths`
- Delete:
  - There is no delete endpoint. `api/pages.py` only reports `perms.can_delete()` in the page detail.
  - A page deleted in Wagtail loses its unchanged file at the next write-back; a file changed by hand stays: `content/tests/sites/test_sites.py::test_the_file_of_a_page_deleted_here_goes_unless_it_changed_by_hand` (G4).
- Duplicate: none. G4 lists it as open (content.create "duplicate to come").
- Gaps found:
  - (a) No section: `path_for` always puts a new page at the collection root.
  - (b) A declared collection with no files yet has no `CollectionPage` (`importers/jekyll.py::_container` makes one only when a file is imported), so nothing can be created in it.
  - (c) Fixed: a page that is not live is written back with Jekyll's own `published: false` (Rails wrote `draft: true`) unless its file already holds itself back, so the next Jekyll build skips it — `content/tests/sites/test_sites.py::test_a_never_published_draft_written_back_is_marked_and_jekyll_skips_it`.
  - (d) Slugs are transliterated silently at export. Rails refused an invalid slug, and a title like "!!!" with no usable slug, with a message.

**Verdict:** specified.

**Build**

- API:
  - **Duplicate**: `POST /api/v2/content/pages/<id>/duplicate/` returns 201 with the copy's detail. Needs edit rights on the page and add-child rights on its parent; a lock is a 409.
    - The copy is a sibling, never live, with one draft revision (Wagtail `Page.copy(keep_live=False, copy_revisions=False)`).
    - Title "<title> (copy)"; slug `<slug>-copy`, then `-copy-2` … unique among siblings, giving up after 1000.
    - `front_matter` without `permalink`, `redirect_from`, `preview`; `preview_image` cleared. Date, author, tags, categories and body copied. No suggestions, no revisions.
    - No `ImportedSource`. In a files site its file path is the original file's directory with `<stem>-copy.md` / `-copy-N.md`, so a sectioned post's copy stays beside it.
  - **Delete**: `DELETE /api/v2/content/pages/<id>/`. Needs `can_delete`. 409 when the page has children ("unpublish it, or delete its pages first") or is locked. The response names the file the next write-back will remove.
  - **Create** gains:
    - `section` (files sites): segments matching the Rails regex, an existing non-symlinked directory under the collection's directory in the checkout, confined through `sites.writer`, kept on the page so `path_for` writes `<collection dir>/<section>/<file>`.
    - `GET /api/v2/sites/<id>/collections/` returns `{collection, sections[]}` for the create form.
    - Registration and sync create a `CollectionPage` for every declared collection (not `data`) whose directory exists, so empty collections are creatable.
    - Create returns a `file_path` preview, and refuses with 422 a slug whose file slug is empty ("!!!").
  - **Write-back** (done, gap (c)): a page that is not live carries `published: false` in its file unless the file already holds itself back (`sites.catalog.held_back`). This covers a new draft and a duplicate.
- Studio:
  - "Duplicate as draft" in the page editor's header; it opens the copy.
  - "Delete" with a confirm dialog naming the page and its file.
  - CreatePage gains Section (when the parent is a collection of a files site), Slug with the resulting file path shown live, and Draft (the default).
- Extension: by construction in G10. File mode keeps `zer0Cms.draft.new`.
- Tests (re-expressing `page_editing_test.rb` and `test_writer.rb`):
  - `content/tests/api/test_pages.py::test_duplicate_is_a_draft_sibling_without_url_redirects_or_preview`: the second duplicate's slug ends `-copy-2`.
  - `::test_delete_needs_the_permission_and_refuses_a_page_with_children_or_a_lock`.
  - `::test_create_into_an_existing_section_and_refuse_a_missing_or_traversing_one`: `hacks` ok; `missing` and `../_docs` are 422.
  - `::test_an_empty_declared_collection_can_take_a_page`.
  - `content/tests/sites/test_sites.py::test_a_duplicate_writes_back_beside_its_original_as_a_draft`: on the moved fixture, `pages/_posts/2026-01-01-hello-copy.md` equals the original with `title: Hello (copy)`, no permalink, redirect_from or preview, and `published: false` before the closing fence; the original is byte-identical.
  - `::test_a_never_published_draft_written_back_is_marked_and_jekyll_skips_it` (done).
  - `web/packages/ui/test/editor.test.tsx`: "duplicates a page as a draft and opens the copy", "deletes a page after confirming".
  - `web/packages/ui/test/create.test.tsx`: "creates a page in a section and shows its file name".
- Milestone: P4 (content.create's "duplicate to come"). The section, empty-collection and draft-marker items ride with G4's write-back.

## rails.writer

**Did** (`lib/zer0_cms/cms/writer.rb`; `test/zer0_cms/test_writer.rb`)

- The only two ways the library made a new path, both confined.
- `create(root, collection:, title:, slug:, section:, extras:, body:, date:)`:
  - The collection is `posts`, or a declared collection other than `data`, whose directory exists and is not a symlink.
  - The section must exist, with segments matching `[A-Za-z0-9][A-Za-z0-9_-]*`, confined to the collection's directory.
  - Slug: a given slug is transliterated and lowercased. `LETTERS` maps ß/ẞ→ss, æ/Æ→ae, œ/Œ→oe, ø→o, đ/ð→d, þ→th, ł→l, ı→i, ħ→h, ŀ→l; NFD then strips combining marks. It must match `^[a-z0-9]+(-[a-z0-9]+)*$`, cut at the last hyphen at or before 60 characters (a single long word is cut hard).
  - Posts are `YYYY-MM-DD-slug.md`.
  - `confine!`: the target, or its parent when the target is new, realpaths strictly inside the base.
  - O_EXCL, mode 0644.
- `duplicate(path, root:)`: see rails.page-create.
- Errors are `ArgumentError` (invalid input) or `UnsafePath` (escape).

**Platform today**

- G4 `content/sites/writer.py` ports:
  - confinement: plain relative paths, `lstat` at every component, realpath inside;
  - O_EXCL create, with missing directories made one checked component at a time;
  - the atomic replace re-checked before the rename;
  - `transliterate` / `slugify` / `slug_for` / `truncate`.
- Tests (G4): `content/tests/sites/test_writer.py::test_only_plain_relative_paths`, `::test_reads_a_regular_file_through_no_symlink`, `::test_a_new_file_is_created_once_and_never_through_a_planted_symlink`, `::test_a_directory_symlinked_away_is_refused_and_nothing_lands_outside`, `::test_missing_directories_are_made_one_checked_component_at_a_time`, `::test_a_replace_is_atomic_keeps_the_mode_and_needs_the_bytes_it_checked`, `::test_a_change_that_lands_mid_write_is_refused`, `::test_remove_only_what_is_still_expected`, `::test_slugs_are_validated_after_transliteration`, `::test_slugify_truncates_at_a_word_boundary`.
- The dated post file with a transliterated slug is proven by `content/tests/sites/test_sites.py::test_a_new_page_gets_a_file_and_the_job_says_so`.
- Not ported: duplicate, section placement, "collection must be declared with a directory", and the `Writer.create` front-matter shape. The exporter renders from scratch; YAML-rule quoting is proven by `content/tests/sites/test_frontmatter.py::test_dump_builds_a_block`.
- Note: G4 "missing directories are made" differs from Rails, which refused a missing section. Under the build below a person can only pick an existing section; only the platform's own `path_for` paths create directories.

**Verdict:** specified.

**Build**

- The capability is the file half of rails.page-create's duplicate, section and empty-collection items. Build it there; nothing separate in the API or the studio.
- Tests at the file layer: `content/tests/sites/test_sites.py::test_a_duplicate_writes_back_beside_its_original_as_a_draft` (above) and `::test_a_page_in_a_section_writes_into_that_section`.
- The create from Rails' `test_create_quotes_titles_by_yaml_rules_and_keeps_a_body_that_looks_like_front_matter` should be re-expressed as `content/tests/importers/test_jekyll.py::test_a_new_page_with_a_yes_title_and_a_fenced_body_round_trips`: title `Yes`, body `---\nnot: front matter\n---\n`, export, then `sites.frontmatter.parse(strict=True)` gives title "Yes" and the body intact.
- Milestone: with rails.page-create (P4; the file side with G4).

## rails.assets-terms

**Did** (`app/models/{asset,term}.rb`, `app/dashboards/{asset,term}_dashboard.rb`, `app/controllers/admin/{assets,terms}_controller.rb`, `app/views/admin/terms/show.html.erb`, `app/controllers/files_controller.rb`, `app/fields/preview_image_field.rb`, `app/services/site_sync.rb#asset_row/#rebuild_terms`; tests `test/integration/files_test.rb`, `admin_routes_test.rb`)

- **Images**: every `.png .jpg .jpeg .gif .webp .svg` file (case-insensitive) under the site source's `assets/` and `images/`, plus `preview_images.output_dir` when it is confined inside the root.
  - Symlinked files and directories are skipped (`Catalog.media`).
  - Indexed with path, extension, bytes and mtime.
  - Read-only list, newest first, with a thumbnail column, filters `site:<id>` and `ext:<ext>`, and a show page.
- **Terms**: per site, every tag, category and author with the number of pages carrying it (each page counted once per term), rebuilt on every sync.
  - Read-only list sorted by count, with filters `tag:`, `category:`, `author:` and `site:<id>`.
  - A term's page links to "Pages with this tag/category/author".
- **Thumbnail server** `GET /files/<absolute path>`:
  - Only the image extensions above (else 404 with an empty body).
  - The site is chosen by string prefix of a registered realpath (no site gives 404).
  - The rest is walked with `lstat`: any symlink file or directory gives 403, `..`/empty/`.` segments give 403, missing gives 404.
  - The realpath must be inside the site.
  - Served inline with `Content-Security-Policy: default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; sandbox` (an SVG cannot run script in the app origin) and `X-Content-Type-Options: nosniff`.
  - Every error is a bare status with no trace.
- **Preview thumbnails** (`PreviewImageField.locate`): a page's `preview:` is looked up as `<source>/<value>`, then `<source>/assets/<value>` (the engine writes `/images/previews/x.png` for a file in `assets/images/previews/`, and the theme adds the prefix), then `<root>/<value>`.
  - Query and fragment are stripped, and the value must have an image extension.
  - External `http(s)` values are shown as text, "(external — not loaded)".
  - A missing file reads "(no such image in the site)".

**Platform today**

- main: Wagtail images (`cms.ContentImage`), the public `GET /api/v2/images/` (live content only; `api/urls.py` `PublicImages`), and renditions for thumbnails.
- The importer (`importers/jekyll.py::import_images`) imports only images a page's `preview`/`image` names, into collection "site: <key>", deduplicated by sha256.
- G4 ports `sites/catalog.py::media` (same dirs, symlinks skipped, output_dir confined): `content/tests/sites/test_catalog.py::test_media_ignores_an_output_dir_outside_the_root`, `::test_symlinked_entries_are_skipped_and_counted`. Nothing calls it.
- Tags are taggit on `ArticlePage`, categories the `cms.Category` snippet, author a string field. There is no API or studio view listing terms with counts.
- The studio has no media library (ledger media.library: studio missing).
- Bugs found (main and G4):
  - `import_images` tries only `<source>/<value>` and `<root>/<value>`, not `<source>/assets/<value>`. `sites/zer0-pages` (137 `preview: /images/previews/…` lines; files in `pages/assets/images/previews/`) and `sites/2005` (35 lines; files in `assets/images/previews/`) therefore import without their preview images.
  - `svg` is not in `WAGTAILIMAGES_EXTENSIONS` (unset, so Wagtail's default), while 2005's previews and the image engine's key-free `local` output are SVG.
  - `/media/` has no route in `config/urls.py`. Whatever serves it must also apply the SVG sandbox the Rails file server applied.

**Verdict:** specified.

**Build**

- API:
  - Sync imports every `sites.catalog.media(root)` image into the site's image collection, idempotent by sha256 and keeping the source path in a field or tag. Removing an image from the checkout does not delete it.
  - `GET /api/v2/media/images/?site=<id>&ext=&q=&ordering=-created_at` (people only, images of sites they see) returns title, file name, source path, size, dimensions, and a thumbnail rendition URL (`fill-160x100`).
  - `import_images` (and every preview lookup, see rails.missing-previews) uses the three candidates: source, source/assets, root.
  - `WAGTAILIMAGES_EXTENSIONS` adds `svg`. Every response that serves an original SVG or other media carries Rails' file CSP with `sandbox` and `nosniff`. Either a small media-serving view, or the documented web-server config with a test of the view used in development.
  - Terms: `GET /api/v2/content/terms/?site=<id>&kind=tag|category|author` returns `[{kind, name, pages}]` sorted by pages, descending. Counts are distinct pages per site, from taggit, `Category` and `author`.
- Studio:
  - A Media area (G6's "Media studio menu"): a grid of a site's images with thumbnail, path, type and size; filter by type; open an image to see its use (pages whose `preview_image` it is).
  - Terms as a "Tags & authors" panel in Write: counts, each linking to the page list filtered by it.
  - The page editor shows the preview image's thumbnail, or "(external — not loaded)" or "(no such image in the site)" for the front-matter value.
- Extension: by construction in G10. The file mode has `src/core/media`.
- Tests (re-expressing `files_test.rb` and `admin_routes_test.rb`):
  - `content/tests/importers/test_jekyll.py::test_a_preview_under_assets_is_found_like_the_engine_finds_it`: `preview: /images/previews/x.png` with the file in `assets/images/previews/` sets `preview_image`; an `https://` value sets nothing and keeps the key.
  - `content/tests/sites/test_sites.py::test_sync_imports_every_site_image_once`: catalog.media count equals the images in the collection; symlinked files and directories skipped; a second sync adds none.
  - `content/tests/media/test_library.py::test_the_library_lists_a_sites_images_with_thumbnails` and `::test_an_svg_is_served_sandboxed_and_nosniff`.
  - `content/tests/api/test_terms.py::test_terms_count_pages_per_site_and_kind`: the fixture tag `fixture` → 1.
  - `web/packages/ui/test/media.test.tsx`: "lists a site's images with thumbnails and filters by type".
- Milestone: G6 for images and thumbnails ("the Media studio menu"). The importer's `assets/` lookup is a bug fix for now (it is G4's importer). Terms ride with rails.page-search (P4).

## rails.markdown-preview

**Did** (`app/controllers/admin/markdown_previews_controller.rb`, `app/services/markdown_renderer.rb`, `app/javascript/controllers/markdown_preview_controller.js`, `app/fields/markdown_field.rb`, `app/views/fields/markdown_field/*`, the body field of `admin/pages/new.html.erb`; test `page_editing_test.rb` "the markdown preview returns sanitized HTML")

- Next to every body textarea (edit and new page) a preview pane re-renders 350 ms after typing stops.
  - An in-flight request is aborted when a newer one starts.
  - `POST /admin/markdown_preview` with `markdown=` (CSRF token, same origin) answers with HTML.
- Server side:
  - Input is cut to 1,000,000 characters.
  - kramdown GFM (`hard_wrap: false`).
  - Then an allow-list sanitizer. Tags: p br h1–h6 ul ol li pre code blockquote a img em strong del hr table thead tbody tr th td. Attributes: href src alt title class. No `on*`, no `javascript:` URLs, no other raw HTML.
  - On a renderer error it logs a warning and returns the escaped source.
- The page show view renders the body the same way. The preview pane has `aria-live="polite"`.

**Platform today**

- main `web/packages/ui/src/RichText.tsx`: TipTap with `@tiptap/markdown`. Rich mode is WYSIWYG, so formatting shows as it is typed.
- A block the editor cannot reproduce exactly (Liquid, raw HTML, constructs it would rewrite), or any block switched to Source, is a plain `Textarea` with no rendered view.
- `PageEditor.tsx` links the platform's render of the latest saved revision (`preview_url`).
- Tests (main): `web/packages/ui/test/editor.test.tsx` (`<BodyEditor>` cases). No test covers a preview of source-mode Markdown.
- Python-Markdown 3.11 is pinned in `content/requirements.txt`. There is no HTML sanitizer dependency.
- Jekyll bodies with Liquid or raw HTML are the ones forced into source mode, and they are exactly the ones edited without any preview.

**Verdict:** specified.

**Build**

- API: `POST /api/v2/content/preview/markdown/` with `{markdown}` returns `{html}`. People only, CSRF, throttled per person.
  - Input cut to 1,000,000 characters.
  - Python-Markdown with `tables`, `fenced_code` and `sane_lists`. Liquid tags (`{% … %}`, `{{ … }}`) are shown as literal text, not evaluated.
  - Sanitized with `nh3` (a new pinned dependency; the reason is "an HTML sanitizer, not hand-rolled") using Rails' tag and attribute allow-lists and URL schemes http, https, mailto and relative.
  - On a render error, the escaped source.
  - Once P6's kramdown-compatible pipeline exists in `web/site/`, the studio may render client-side with it and this endpoint goes.
- Studio:
  - In RichText's source mode, a split view with a "Preview" pane (`aria-live="polite"`) fed by the endpoint, 350 ms debounce, the previous request aborted.
  - The same pane under CreatePage's body, if a body is added there (rails.page-create).
- Extension: by construction in G10. File mode has `zer0Cms.draft.preview`.
- Tests:
  - `content/tests/api/test_preview.py::test_markdown_preview_is_sanitized`: `# Hi` gives `<h1`; `<script>alert(1)</script>` and `[x](javascript:alert(1))` give neither `<script` nor `javascript:`; an `onerror=` attribute is gone.
  - `::test_markdown_preview_cuts_huge_input_and_needs_a_person`.
  - `web/packages/ui/test/editor.test.tsx`: "previews a source-mode block after a pause and drops a stale response".
- Milestone: P4 (content.preview).

## rails.missing-previews

**Did** (`app/services/image_engine.rb`, `PagesController#generate_preview`/`#index`, `PageDashboard` `missing_preview:`, `views/admin/pages/show.html.erb`, `views/admin/sites/show.html.erb`, `PageEditor#replace_engine_write!`; tests `test/integration/image_engine_test.rb`, `test/services/image_engine_settings_test.rb`)

- **Settings** come from the site's `_config.yml` `preview_images:` block.
  - `front_matter_key`: default `preview`. It must match `^[A-Za-z_][A-Za-z0-9_-]*$`, else the error "is not a plain key".
  - `output_dir`: default `assets/images/previews`, trailing slash trimmed. It must resolve inside the site source through `Catalog.confine`. Absolute values, `..` and a symlink out are all refused with "resolves outside the site root". It must not be the source itself ("must be a directory below the site source").
- **Missing list**: the image engine walks every collection directory for `*.md` with front matter (the Python engine's `--list-missing --collection all --provider local`).
  - A file is missing a preview when the key is absent or empty, or when its value is not `http(s)://` and no file exists at `<source>/<value>` or `<source>/assets/<value>`.
  - The output gives the root-relative path, title, and "Current preview (not found)"; ANSI colour is stripped and paths outside the root dropped.
  - The `missing_preview:` filter (or `missing_preview:<site id>`) narrows the page list to indexed pages among them. A file the engine walks but Jekyll does not read, such as `_posts/undated.md`, has no row.
  - When the engine cannot run, the list renders without the filter, flashing "missing_preview: is unavailable — <reason>".
  - The site page links to "Missing previews".
- **Generate preview (local)**, per page, one generation at a time per process (mutex):
  - Refused before the engine runs when the file changed since the last sync, or when the settings are refused.
  - The engine (free `local` provider, no credentials) writes the image into `output_dir` and the key into the file.
  - The engine's write is accepted only if it changed nothing but that key, to a string value. The key is then re-applied to the original bytes by line surgery (appended before the closing fence), written atomically, and re-synced. Otherwise the original bytes are restored and "the image engine changed more than <key>: …; its edit was undone" is shown.
  - The site is re-synced so the new image is indexed.
  - Outcomes: "Generated a local preview: <key>: <value>"; "<path> already has a preview (<value>); the engine drew nothing."; "The engine drew nothing for <path>."; "The image engine failed: <last 6 log lines, ≤600 chars>".
  - The button is disabled, with the reason as its title, when the engine is unavailable: no gem, or no python3 with PyYAML.
- **Backends**:
  - Facade: `Zer0ImageGenerator::Facade.missing_previews`/`generate_one`.
  - Python subprocess: the engine run in the site root with `--file F --provider local --output-dir D --front-matter-key K --rasterizer auto|$ZER0_CMS_RASTERIZER --parallel 2`. Only PATH, HOME, LANG, LC_ALL and TMPDIR are passed (no credential reaches it), plus `PYTHONDONTWRITEBYTECODE`/`PYTHONIOENCODING`. It runs in its own process group with a 300 s deadline that kills the group.
  - Without a rasterizer the local provider keeps an SVG, so `.svg` or `.png`.
- Bigger runs link out to `ZER0_IMAGE_GENERATOR_URL`: only an `http(s)` URL is used, default `http://localhost:3000`.

**Platform today**

- Nothing on main, G4 or G5. Ledger media.generate is missing on every surface.
- G4's doctor reads `preview_images:` only to warn ("no-preview-images-config"): `content/tests/sites/test_doctor.py::test_image_engine_check`.
- The engine itself survives the deletion: `packages/zer0-image-generator/lib/zer0_image_generator/preview_generator.py` (`check_preview_exists`, `--list-missing`, `--file`, the local provider) stays until G6. Deleting `rails/` removes only the UI, the bridge and the write-back guard.
- The platform's `BasePage.preview_image` is the page's preview. The importer's lookup bug (rails.assets-terms) would make zer0-pages and 2005 pages look missing.

**Verdict:** specified.

**Build** (inside G6's `content/media/` rewrite)

- API:
  - Preview settings per site: key, output dir and provider defaults. Read from `_config.yml` `preview_images:` at sync and editable through G6's "`preview_images:` site-config editor". Rails' key regex and output_dir confinement are enforced at save and at sync, with Rails' messages.
  - `missing_preview=true` on `GET /api/v2/content/pages/` (with `site`): pages of a site whose `preview_image` is null and whose front-matter key value is absent or empty, or is a local path that does not resolve through the three-candidate lookup. An external `http(s)` value counts as present.
  - `GET /api/v2/sites/<id>/` gains `missing_previews: <count>`.
  - `POST /api/v2/content/pages/<id>/preview/` with `{provider: "local"|…, force?: bool}` returns 202 with an `ImageRun` job (G6), exclusive per site.
    - The provider draws `<slug-of-title>.<svg|png>` into the site's image collection, with source path `<output_dir>/<file>`.
    - The result is a suggestion on the page's preview (proposed `preview_image` plus the front-matter key `/<output_dir minus its leading assets/>/<file>`), accepted by a person in Review. Outcomes `generated`, `skipped` ("already has a preview (<value>)" unless `force`), `nothing drawn` and `failed` (log tail) are on the job.
    - On write-back the key lands by line surgery before the closing fence, and the image file is written into the checkout with the confined writer.
    - Paid providers take credentials only from G6's `ProviderCredential`; the local provider needs none.
    - Unavailable providers are listed with their reason (`GET /api/v2/media/providers/`).
- Studio:
  - Site Overview: "Missing previews (N)", which opens Write's list with `missing_preview:` and the site.
  - Page editor: "Generate preview" with a provider select (local first), disabled with the provider's reason when unavailable. It follows the job's log and shows the proposed image in the suggestion panel.
  - Batch runs, dry run and list-missing for a whole site live in G6's Media area. That replaces the "Image generator ↗" link-out.
- Extension: by construction in G10 (the page editor's button). File mode keeps its own media commands.
- Tests (re-expressing `image_engine_test.rb` and `image_engine_settings_test.rb` on `content/tests/fixtures/jekyll-site`):
  - `content/tests/media/test_missing.py::test_the_missing_list_matches_the_engine_on_the_fixture`: the engine walk gives `pages/_posts/2026-01-01-hello.md`, `2099-01-01-future.md`, `sub/2026-03-03-nested.md` and `undated.md`; the page filter gives those minus `undated.md`; two registered copies of the site give twice as many without `site`.
  - `::test_settings_defaults_and_the_sites_block`: `preview`, `assets/images/previews`; `image`, `img/og/` → `img/og`.
  - `::test_an_output_dir_or_key_that_could_escape_is_refused`: `../outside`, `/img/og`, `.`, a symlink out, and the key `"a: b"`, each with Rails' message and before any provider runs.
  - `::test_a_local_preview_is_proposed_and_writes_back_as_one_line`: accepting it then writing back differs from the original only by `preview: /images/previews/hello.(svg|png)` after `tags: [fixture]`; the image exists under `assets/images/previews/`; the page is no longer missing.
  - `::test_a_second_generation_says_it_already_has_a_preview_and_changes_nothing`.
  - `::test_an_unavailable_provider_is_refused_with_its_reason`.
  - `web/packages/ui/test/media.test.tsx`: "generates a preview, follows the job and shows the proposed image", "disables generation with the provider's reason".
- Milestone: G6.

## rails.access-guard

**Did** (`app/controllers/concerns/access_guard.rb`, `app/services/local_network.rb`, `config/application.rb` (hosts), `config/initializers/content_security_policy.rb`, `config/initializers/filter_parameter_logging.rb`, `docker-compose.yml` `cms`; tests `test/integration/security_test.rb`, `test/services/local_network_test.rb`)

- Without `ZER0_CMS_PASSWORD`, every request is refused unless it comes from this machine: a plain-text 403, "zer0-CMS answers requests from this machine only. Set ZER0_CMS_PASSWORD to allow other clients."
  - Local means the TCP peer (`REMOTE_ADDR`, never `remote_ip`) and every `X-Forwarded-For` hop are loopback (127/8, ::1, `[::1]`, ::ffff:127.x).
  - With `ZER0_CMS_TRUST_DOCKER_GATEWAY=1`, set by compose, the container's default gateway (from `/proc/net/route`) also counts.
- With `ZER0_CMS_PASSWORD`, every surface needs HTTP basic auth (realm "zer0-CMS"), compared in constant time. The user is `ZER0_CMS_USER`, default `zer0`; an empty value means the default.
- Host allow-list: `localhost`, `127.0.0.1`, `::1` and `[::1]`, plus a comma-separated `ZER0_CMS_HOSTS`. Any other Host gets a 403 (DNS-rebinding guard).
- CSP:
  - `default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self' data:; form-action 'self'; frame-ancestors 'none'; img-src 'self' data:; object-src 'none'; script-src 'self'; style-src 'self'`.
  - A fresh base64 nonce per request on `script-src`/`style-src`, carried by the importmap and module scripts and a `csp-nonce` meta tag.
  - No `unsafe-inline` or `unsafe-eval`. Administrate's compiled JS and CSS are not loaded. Flashes are escaped.
- CSRF on every write.
- Logs filter `passw email secret token _key crypt salt certificate otp code state`.
- Compose publishes on 127.0.0.1 only.

**Platform today**

- Sign-in for every studio and API endpoint, and no agents on people's endpoints (main): `content/tests/api/test_pages.py::test_the_studio_endpoints_are_for_signed_in_people_not_agents`.
- CSRF and edit rights: `::test_saving_needs_the_csrf_token_and_edit_rights`.
- Enforced studio CSP with a per-request nonce, `script-src 'self'`, no `unsafe-inline`, `frame-ancestors 'none'`, `object-src 'none'`, `base-uri`/`form-action 'self'`: `content/tests/api/test_studio.py::test_every_studio_path_is_the_index_with_a_fresh_nonce`.
- Security headers: `content/tests/ops/test_security_headers.py::test_html_responses_carry_the_security_headers`.
- Redacted JSON logs: `content/tests/ops/test_logging.py::test_tokens_are_redacted`.
- `ALLOWED_HOSTS` defaults to `localhost`, `127.0.0.1` and `.localhost` from the environment (`content/config/settings/base.py`), with no test.
- Compose publishes the platform on `127.0.0.1:${CONTENT_PORT:-8000}`.
- The Wagtail admin's CSP is report-only. ADR 0006 puts no product screens there.

**Verdict:** specified (test-only). The loopback-or-password and Docker-gateway mechanics are replaced by the platform's sign-in (G3 adds accounts); that half is `dropped` once the owner agrees.

**Build**

- API/ops: nothing new in code.
  - Map `ZER0_CMS_HOSTS` → `ALLOWED_HOSTS` (and `CSRF_TRUSTED_ORIGINS`) in `content/README.md`'s settings table.
  - State in `content/ops/README.md` that no endpoint but the public Wagtail read API, probes and newsletter pages answers anonymously, so a platform reachable beyond loopback relies on sign-in, not on the peer address.
- Studio: none. Extension: none.
- Tests:
  - `content/tests/ops/test_hosts.py::test_an_unknown_host_is_refused`: `HTTP_HOST=attacker.example` gives 400 (DisallowedHost) with the error envelope and no body content.
  - `::test_hosts_named_in_the_environment_are_accepted`.
  - `content/tests/api/test_pages.py::test_a_forwarded_for_header_grants_nothing`: `X-Forwarded-For: 127.0.0.1` without a session is still 401.
- Milestone: G11 (the retirement commit for `rails/`); the accounts half is G3.

## rails.parity-tools

**Did** (`bin/jekyll-parity`, `bin/front-matter-roundtrip`; outputs `test/fixtures/*.expected.json`)

- `jekyll-parity SITE [--json]` needs the `jekyll` gem 4.4.x. It runs Jekyll's reader from the site root the way `jekyll build` would:
  - safe mode, `plugins: []`, `future`/`unpublished`/`show_drafts` true, no incremental, no disk cache;
  - when the theme gem is absent, a note and no theme config;
  - `reader.read_directories` + `read_included_excludes` + `CollectionReader`, with no render or write.
- It lists `[collection|"pages", source-relative path]` for every content-extension page or document, sorted and unique, and counts `non_content_pages`, `non_content_posts` and `non_content_documents`.
- It diffs these against `Catalog.scan`: only in Jekyll, only in the catalog, count mismatches, symlinks skipped. Exit 0 when equal, 1 on any difference or a refused site, 2 on usage or a missing gem.
- `--json` prints Jekyll's lists, with `generator` "Jekyll <v> reader via rails/bin/jekyll-parity" and `notes`. That output is the committed oracle the catalog tests compare against.
- `front-matter-roundtrip SITE…` is read-only. For every catalogued file with a parseable block it checks:
  - noop: `update_keys(text, parsed data)` is byte-identical;
  - re-emit per key: set a sentinel, set it back, the data reads back equal, and deleting the key from either text gives the same bytes.
- It prints per-site counts (`noop_ok/fail`, `keys`, `reemit_ok/fail`, `no_front_matter`, `unparseable`, `skipped_encoding`) and the first 25 failures. Exit 1 on any failure.

**Platform today** (G4)

- The oracle files moved to `content/tests/fixtures/jekyll-site{,-src}.expected.json` with their fixture sites.
- `content/tests/sites/test_catalog.py::test_the_fixture_sites_match_jekylls_reader_byte_for_byte` renders the Python walk in `--json` shape and compares bytes.
- The round-trip property holds over the five front-matter fixtures (`content/tests/fixtures/front_matter/*.md`): `content/tests/sites/test_frontmatter.py::test_every_fixture_round_trips`.
- Import → export byte equality over real sites: `content/tests/importers/test_jekyll.py::test_the_real_sites_round_trip_byte_for_byte` (G4; zer0-pages slow). Unchanged pages are written verbatim, so it does not exercise surgery on those sites.
- Missing:
  - a way to re-record Jekyll's lists when a fixture changes (Ruby with the gem; the ledger note says so);
  - the surgery's re-emit property over whole real sites.

**Verdict:** specified.

**Build**

- Ops (no Ruby in the repository): `tools/jekyll_parity.py --site PATH [--json]`, beside P1's `tools/site_manifest.py`.
  - It copies the fixture to a temporary directory and adds one Liquid page that prints, as JSON, the `relative_path` of every `site.pages` item and every document of every `site.collections` (posts and drafts included).
  - It builds that copy with the pinned Jekyll 4 image P2 uses (`tools/jekyll/Dockerfile`): `--safe --future --unpublished --drafts`, plugins none, the theme option off.
  - Python applies the catalog's content-extension rule, counts the rest, and writes the expected-JSON shape (`generator` "Jekyll <v> reader via tools/jekyll_parity.py"). It diffs against `sites.catalog.scan` with the same exit codes, 0, 1 and 2 (2 when docker or the image is unavailable).
  - Owner decision if the Liquid route cannot reproduce the reader-level counts: freeze the two oracles, and re-record them out of tree.
- `python -m sites.frontmatter --roundtrip PATH…` (stdlib + PyYAML, like `python -m sites.doctor`) implements both properties with the same counters, the first 25 failures and the same exit codes.
- Studio and Extension: none; these are proof tools.
- Tests:
  - `content/tests/sites/test_frontmatter.py::test_every_in_repo_site_round_trips` (marked `slow`): runs the round trip over `sites/*` checkouts and asserts zero failures.
  - `tools/tests/test_jekyll_parity.py::test_the_recorder_reproduces_the_committed_lists`: skips with a reason without docker, and asserts byte equality with `content/tests/fixtures/jekyll-site{,-src}.expected.json`.
- Milestone: G11 (a prerequisite of deleting `rails/bin/jekyll-parity`). The recorder sits with P1/P2's Jekyll tooling.

**Keep:** `content/tests/fixtures/jekyll-site/`, `jekyll-site-src/`, both `.expected.json` files and `front_matter/*.md` (with `zer0-mistakes-post.md` renamed `theme-docs-post.md`). G4 already moved all of these from `rails/test/fixtures/`. Nothing else under `rails/` is a fixture worth keeping for these rows; the inline expectations (for example `image_engine_test.rb`'s `MISSING` list) are copied into the specs above.

## The ABC engine

Read at `d0a572fb` (`git show d0a572fb:<path>`). The ABC wizard (web) and the ABC generator (library + CLI) are one engine with two front ends: `AbcBooksController` and `bin/zer0-cms` both drive `Zer0Cms::Abc::Wizard` + `JekyllExporter`, so the generator section holds the algorithm and the wizard section holds the person's flow. Determinism check, run for this spec: main's `rails/lib` (extracted to a scratch directory, Ruby 2.6 with a `YAML.safe_load_file` shim) regenerates `sites/drsai/_data/abc_books/it-alphabet.json` and `sites/drsai/pages/_books/it-alphabet/index.md` **byte for byte** (`cmp` clean) from `theme "IT systems", slug it-alphabet, art_style isometric-tech-toy, provider deterministic`, so drsai's committed book is the Rails golden output.

## rails.abc-wizard-ui

**Did**

- Routes (`rails/config/routes.rb`): `GET /abc/new` (form), `POST /abc/preview`, `POST /abc/export`, `GET /abc/catalog.json`; a sidebar entry "ABC books" (`rails/app/views/layouts/_zer0_sidebar.html.erb`); behind the app's generic access guard (loopback or password, `rails/test/integration/security_test.rb`).
- Form (`rails/app/views/abc_books/new.html.erb`): theme (text, default "IT systems", datalist of bundled themes with `_` shown as spaces; hint: "Bundled themes generate offline; any other theme uses Claude (needs `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN`)"), art style (select of catalog style names), palette (select with "(style default)" = blank), background, mood (selects from the catalog), slug (placeholder "auto from the title"), audience (Toddler `toddler` / Preschool `preschool` / Early reader `early-reader`), export target (text, prefilled from `DRSAI_SITE_ROOT`, datalist of registered `Site` paths; hint: export writes `pages/_books/<slug>/index.md` and `_data/abc_books/<slug>.json`, preview writes nothing). Two buttons: "Preview book" (posts to preview) and "Export" (`formaction` export). The controller also permits `title`, `subtitle` and `provider` (not on the form); blanks are dropped, `theme` is stripped, `provider` defaults `auto`, `background` `plain`, `mood` `playful` (`rails/app/controllers/abc_books_controller.rb#wizard_params`).
- Preview: runs the wizard, renders the book Markdown with the exporter's `render_markdown` (no file written), shows "Preview — <title>", "<subtitle> · <N> letters · art style `<id>` · nothing was written", the Markdown in a `<pre>`, and a note pointing back to Export (`preview.html.erb`).
- Export: resolves the target (`rails/app/services/abc_export_target.rb`), runs the wizard, writes the bundle, shows both written paths, "<N> illustration(s) still to render" and the next commands `python3 tools/generate_illustrations.py --book <slug> --dry-run` then without `--dry-run` (`export.html.erb`).
- Target rules (`AbcExportTarget.resolve!`), each a `Refused` with this message: blank → "Choose the target site directory (a Jekyll root with _config.yml) to export into."; not absolute → "The export target must be an absolute path."; not a directory → "<path> is not a directory."; realpath has no regular, non-symlink `_config.yml` → "<path> has no _config.yml, so it is not a Jekyll site root."; with `SITES_DIR` set, not strictly inside it (the mount itself refused) → "<path> is not a site inside SITES_DIR (<dir>)."; any `SystemCallError` → "The export target cannot be used: <msg>".
- Errors: `Spec::InvalidSpec`, `ArgumentError` (bad provider name, incomplete plan) and `Anthropic::ProviderError` (and `Refused` on export) redirect to `/abc/new` with the message as a flash alert, status 303. Quirks: `Lexicon::UnknownTheme` (provider `deterministic` with an unbundled theme) is not rescued (a 500); the wizard's warnings (style fallback, auto→Claude) are never shown on the web.
- Catalog: `GET /abc/catalog.json` = `ArtStyles#to_menu` plus `"themes": [<lexicon slugs>]` (shape in the generator section).
- Tests (`rails/test/integration/abc_books_test.rb`): the form renders in the admin layout with an `input[name=target]`; preview renders `layout: book-abc` and writes nothing; export refuses a missing target, a directory without `_config.yml` (and leaves it empty), the `SITES_DIR` mount itself (no `pages/` created); export into a real Jekyll root writes `pages/_books/it-test-book/index.md` and `_data/abc_books/it-test-book.json`; the catalog is JSON with a `themes` key.

**Platform today**

- No ABC endpoint, no catalog, no preview, no export action. The only way to generate is a drafter run: `POST /api/v2/agent-runs/ {agent: "drafter", page_id, input: {theme}}` (`content/api/views.py::_create_run` passes `input`), which on a `BookPage` with `profile="abc"` selects `agents.handlers.abc.draft` (`content/agents/runner.py::apply_profile`, `content/agents/definitions/drafter.yaml`).
- Studio: `web/packages/ui/src/CreatePage.tsx` makes a page of any type its parent allows (a `BookPage` under a `books` collection) and can start the drafter, but only with a brief topic and with no `input`, so the abc handler takes the theme from the page title (works only when the title is a bundled theme, e.g. "IT systems"). `web/packages/ui/src/BodyEditor.tsx` edits `letter` blocks as structured fields. The Books area (`web/packages/ui/src/books/`) holds the library's books only: a Jekyll site's ABC book is a 404 there (`content/tests/books/test_api.py::test_a_jekyll_sites_books_are_not_the_librarys`). No art-style, palette, background, mood, audience or slug choice anywhere; no extension counterpart.
- G4 (`overhaul/sites-jobs`, merged with this change) adds `ManagedSite` (a registered checkout inside the repository or `SITES_DIR`), the write-back job over `exporters.jekyll.site_files` with the confined writer and stale-write guard — the platform's replacement for `AbcExportTarget`. It adds nothing ABC-specific.
- Proofs that exist (all partial for this row): `content/tests/agents/test_drafter.py::test_the_abc_profile_writes_every_missing_letter_from_the_lexicon`, `content/tests/agents/test_drafter.py::test_at_policy_draft_the_abc_drafter_writes_the_revision_itself`, `content/tests/books/test_api.py::test_a_jekyll_sites_books_are_not_the_librarys`.

**Verdict** — `specified`: a person cannot choose a style, preview a book or export it from the studio; `books.abc` is `api: missing, studio: missing`.

**Build**

- API (`content/books/urls.py`, `views.py`, `serializers.py`, in the committed OpenAPI document; thin over the engine in `content/books/abc.py`, see the generator row):
  - `GET /api/v2/books/abc/catalog/` → `{version, styles: [{id, name, summary, default_palette, default_lettering, best_for}], palettes, backgrounds, lettering, moods: [{id, name}], themes: [{slug, theme, title}], audiences: [toddler, preschool, early-reader]}`.
  - `POST /api/v2/books/abc/preview/` with `{theme, title?, subtitle?, slug?, art_style?, palette?, background?, mood?, lettering?, audience?, provider: auto|lexicon|model}` → bundled theme: `200 {spec, markdown, sidecar, warnings, planned_images}`, synchronous and deterministic; otherwise a drafter run (`202 {run}`, `Idempotency-Key` honoured) whose output carries the same body. Writes nothing. Invalid spec → `400` with the Rails messages; `provider: lexicon` with an unbundled theme → `400` (not the Rails 500); an unknown style → `200` with the fallback warning.
  - `POST /api/v2/books/abc/` → creates the book as a draft `BookPage` (`profile="abc"`, `series="abc-language"`) under the chosen site's `books` collection, the spec's knobs on the page and one `letter` block per letter; `201` with the page; refused without add permission on that collection.
  - `POST /api/v2/books/abc/<id>/export/` → starts the site's write-back job (G4) for that book's two files (`<collections_dir>/_books/<slug>/index.md`, `_data/abc_books/<slug>.json`); `202 {job}`; a site without a registered checkout is refused; a hand-edited file is a job conflict, never overwritten. No free filesystem path is accepted (the registry replaces `AbcExportTarget`).
  - List a site's ABC books (`GET /api/v2/books/abc/?site=<id>`: `BookPage` with `profile="abc"` the person may see), so the Books area can show them without putting them on the library's shelf.
- Studio: `web/packages/ui/src/books/AbcWizard.tsx`, routed from the Books area in `web/studio/src/App.tsx` ("New ABC book" and an "ABC books" list per site). Fields as the Rails form plus title/subtitle and lettering; art styles as cards (name, summary, best for); theme as a combobox of bundled themes with the hint that any other theme is written by the model as a run. "Preview" shows the cover and the 26 plates (letter, word, tagline, alt, image path, prompt collapsed), the warnings, and the page Markdown and sidecar JSON as tabs. "Create book" opens the draft in the page editor; "Export to site" follows the job's log and ends with the files written and "<N> illustrations to render" plus the render step (drsai's `tools/generate_illustrations.py --book <slug>` until `media.generate` exists).
- Extension: the same workspace in a webview at G10; until then record `extension: missing` on `books.abc` as the gap.
- Tests: `content/tests/books/test_api.py::test_the_abc_catalog_lists_styles_options_and_themes`, `::test_an_abc_preview_returns_the_spec_and_writes_nothing`, `::test_an_abc_preview_of_an_unbundled_theme_is_a_run` (recorded provider), `::test_an_abc_preview_refuses_an_invalid_spec_with_its_reasons`, `::test_an_abc_book_is_created_as_a_draft_with_26_letters`, `::test_an_abc_export_writes_only_into_a_registered_sites_checkout` (refuses an unregistered path; a hand-edited target file is a conflict; the two files land on success); `web/packages/ui/test/books.test.tsx` cases "the ABC wizard previews 26 plates and creates the book" and "an ABC export shows the files written and the illustrations to render". Proofs for `books.abc` `api:` and `studio:`.
- Milestone: G9 (its gate names "the Rails wizard's fixtures"; the box "The ABC wizard and drsai's story engine as book types and generators" is open). The export action depends on G4's write-back.

**Keep** — nothing under `rails/app` is data. The form's copy (hints, error messages, the next-step commands) is quoted above; the integration tests are mapped into the tests above (git history keeps the Ruby).

## rails.abc-generator

**Did**

- Layout: `rails/lib/zer0_cms/abc.rb` (`SERIES = "abc-language"`), `abc/spec.rb`, `abc/lexicon.rb` + `abc/lexicons/*.yml`, `abc/content_provider.rb`, `abc/providers/{deterministic,anthropic}.rb`, `abc/art_styles.rb` + `data/abc_art_styles.yml`, `abc/wizard.rb`, `abc/jekyll_exporter.rb`; stdlib only. Contract: `rails/schema/abc-book.schema.json`.
- The ABC Book Spec (`spec.rb`, `SPEC_VERSION = 1`): fields and defaults `series` (`abc-language`), `slug`, `title`, `subtitle`, `theme`, `audience` (`toddler`), `language` (`en`), `art_style`, `palette`, `background` (`plain`), `mood` (`playful`), `lettering`, `art_style_prompt`, `generator`, `cover {subject, prompt, image, alt}`, `alphabet [ {letter, word, subject, tagline, alt, prompt, image, status} ]`. Serialised in exactly that key order with `spec_version` first, nil and empty values dropped; `from_json`/`from_yaml` round-trip. `validate!` collects every error and raises `InvalidSpec "invalid ABC Book Spec: <e1>; <e2>…"`: slug required and `^[a-z0-9]+(?:-[a-z0-9]+)*$`; title required; art_style required; audience in `toddler|preschool|early-reader`; alphabet 1–26 entries; each entry has non-blank `letter`, `word`, `subject`, `tagline`; letter is one of A–Z; no duplicate letter.
- The JSON Schema (draft-07): required `spec_version` (const 1), `series`, `slug` (pattern above), `title`, `audience` (enum), `art_style`, `alphabet`; `additionalProperties: false` at every level; `palette` string or null (null = style default); `cover` object of `subject, prompt, image, alt`; `alphabet` 1–26 items, each requiring `letter` (`^[A-Z]$`), `word`, `subject`, `tagline`, optional `prompt`, `image` ("leading slash, site-relative"), `alt`, `status` (`planned|rendered`, default planned). Duplicate letters are a code-only rule (the schema cannot say it). Nothing in Rails validates against the schema file itself; `spec.rb` mirrors it.
- Lexicons (`lexicon.rb`): YAML `{theme, title, subtitle, default_art_style, default_palette, audience, letters: {A..Z: {word, subject, tagline, alt}}}`. Lookup by `slugify(theme)` = lower-case, runs of non-`[a-z0-9]` → `_`, trimmed (so "IT systems", "it_systems" and "IT  Systems" all find `it_systems.yml`); `available` = sorted basenames; a file missing any letter → `ArgumentError "lexicon <theme> is missing letters: …"`; an unknown theme → `UnknownTheme "no bundled lexicon for theme … (looked for <slug>.yml; available: …)"`. One lexicon ships: `it_systems` ("The IT Alphabet", "A is for Automation", `isometric-tech-toy`, `cool-tech`, toddler; Automation, Backup, Cloud, Database, Encryption, Firewall, Gateway, Hardware, Internet, JSON, Kernel, Logs, Memory, Network, Open Source, Password, Queue, Router, Server, Terminal, Update, Version, Wi-Fi, eXit, YAML, Zero Trust), every tagline "<L> is for <Word> — …".
- Providers (`content_provider.rb`): a registry by name (`deterministic`, `anthropic`; an unknown name → `ArgumentError "unknown content provider … (known: …)"`). `plan(theme:, audience:)` returns `{title, subtitle, default_art_style, default_palette, letters: {A..Z: {word, subject, tagline, alt}}}`; every provider runs `validate_plan!` (all 26 letters present as objects, `word`/`subject`/`tagline` non-blank, else `ArgumentError`). Deterministic: the lexicon's title, subtitle, defaults and letters (the lexicon's `audience` is not passed on). Anthropic (`providers/anthropic.rb`): one Messages call, `max_tokens 4096`, default model `claude-opus-5-5`, system "You write gentle, wholesome content for a children's ABC picture book. Every word is text-free and safe for toddlers.", user prompt "Design a <audience> ABC book on the theme "<theme>". For every letter A through Z, choose: word (a real concept from the theme starting with that letter), subject (a concrete, drawable little scene, no text), tagline (one warm read-aloud line, e.g. "A is for Automation — little helpers that do the work!"), alt (a short accessible description). Also give the book a title and a subtitle of the form "A is for <the A word>". Keep every word gentle and never scary. Return all 26 letters.", structured output by JSON Schema (`title`, `subtitle`, `letters` with all 26 keys, each `{word, subject, tagline, alt}` required, no extra properties); `default_art_style`/`default_palette` forced to nil. Errors as `ProviderError`: no credential ("needs ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN (or use the deterministic provider)"), `stop_reason: refusal` ("Claude refused the request; pick a different theme"), no text block, unparsable JSON, non-2xx ("Anthropic API error <code>: <first 300 chars>"). Credentials, headers and the OAuth "You are Claude Code" block are Rails plumbing the platform's provider registry replaces.
- Art styles (`art_styles.rb` over `data/abc_art_styles.yml`): catalog `version: 1`; six styles `isometric-tech-toy` (cool-tech, rounded), `chalkboard-doodle` (bright-primary, chalk), `soft-plush` (nursery-pastel, bubble), `crayon-primary` (bright-primary, slab), `paper-cutout` (warm-earth, rounded), `watercolor-storybook` (warm-earth, rounded), each `{id, name, summary, prompt, default_palette, default_lettering, best_for}`; options `palettes` (cool-tech, bright-primary, nursery-pastel, warm-earth), `backgrounds` (plain, scene, pattern), `moods` (playful, calm, bold), each with a prompt `fragment`, and `lettering` (rounded, bubble, slab, chalk: a hint for the theme's HTML letter, no fragment); `safety_suffix` (no text, toddler-safe). Style ids are a cross-repo contract (front matter `art_style:`, the theme's `abc-style--<id>` class). `render_prompt(letter, word, subject, style, palette = style default, background = plain, mood = playful)` = the parts `[style prompt, background fragment, palette fragment, "Subject: <subject>, standing for the word <WORD upper-cased> (letter <L>).", mood fragment, safety_suffix]`, nils and empties dropped, joined with `". "`, `/\.\s*\./` → `.`, every whitespace run collapsed to one space, stripped. An unknown style raises `UnknownStyle`; an unknown palette, background or mood id silently adds nothing. `to_menu` = `{version, styles: [{id, name, summary, default_palette, default_lettering, best_for}], palettes|backgrounds|lettering|moods: [{id, name}]}`.
- Wizard (`wizard.rb`), given `theme` and optional `slug, title, subtitle, art_style, palette, background (plain), mood (playful), lettering, audience, language (en), provider (auto), assets_prefix (/assets/images/books)`: provider `auto` = deterministic when a lexicon exists, else anthropic with the warning "no bundled lexicon for "<theme>"; using the Anthropic provider"; `deterministic`/`anthropic` forced; anything else `ArgumentError`. Art style = caller's, else the plan's default, else `isometric-tech-toy`; unknown → warning "unknown art style "<id>"; falling back to isometric-tech-toy". Palette resolved once = caller's, else the plan's default, else the style's default, and used for the metadata, every letter and the cover (the regression the Rails test pins). Slug = caller's, else `slugify(plan title || caller title || theme)` with `-` (quirk: the plan's title wins over the caller's for the slug, so the auto IT book is `the-it-alphabet`). Title = caller's, else the plan's, else "The <theme> Alphabet"; subtitle = caller's, else the plan's; audience = caller's, else toddler; lettering = caller's, else the style's default; `art_style_prompt` = the style prompt squished; `generator` = "Text generated by the zer0-CMS ABC wizard from <the bundled <theme> lexicon | Claude (Anthropic)>; illustrations composed for the zer0-image-generator plugin and rendered by drsai." Each letter A–Z: `{letter, word, subject, tagline, alt (lexicon's, else "<word>, illustrated for the letter <L>."), prompt (render_prompt with the resolved palette, background, mood), image "<prefix>/<slug>/<l>-<slugify(word)>.png", status "planned"}`. Cover: subject "a joyful cover for an alphabet book about <theme>, a big friendly letter A and a smiling <first word>", prompt with letter A, the first word, background `scene`, the resolved palette and mood; image `<prefix>/<slug>/cover.png`; alt "Cover of <title>.". Then `validate!`.
- Jekyll exporter (`jekyll_exporter.rb`): validates, then writes `<root>/pages/_books/<slug>/index.md` (collections dir fixed to `pages`, not read from `_config.yml`) and `<root>/_data/abc_books/<slug>.json` (the spec, pretty JSON, trailing newline), creating directories and overwriting without any check; returns both paths and the planned images (every letter not `rendered`, plus the cover: 27 for a new book). Page = YAML front matter in this order, nils dropped: `title, subtitle, layout: book-abc, book: <slug>, series, audience` (label: toddler "Ages 1–4 (toddler board book)", preschool "Ages 3–5 (preschool)", early-reader "Ages 5–7 (early reader)"), `status` (`complete` when every letter is rendered, else `illustrations-planned`), `art_style, art_style_prompt, palette, lettering, cover_image, cover_prompt, preview` (= cover image), `description` ("A <audience id> ABC picture book about <theme>: one letter, one word, one picture per page — from <A's tagline>"), `generator, alphabet: [{letter, word, tagline, image, alt, prompt, status}]` (no `subject` on the page); then `---`, a blank line and one fixed paragraph: "A first alphabet about **<theme>** — one big friendly letter per page, a word to say out loud, and a picture to point at. Read it top to bottom, or jump to any letter."
- Image-generator link: Rails renders nothing. The prompts are complete and text-free; drsai's `tools/generate_illustrations.py` renders every `alphabet` entry with a `prompt` and `image` whose file is missing (and the cover, portrait) and never edits front matter. drsai's `tools/import_abc_book.py --check` (CI `drsai.yml`, "ABC books match their spec") fails when the page and its sidecar disagree on `series, art_style, art_style_prompt, palette`, `cover_image`/`cover_prompt`, or any letter's `word, tagline, image, alt, prompt`, or on duplicate, missing or extra letters. Any exporter must therefore write the page and the sidecar together.
- CLI (`rails/bin/zer0-cms`): `styles` prints "ABC art styles (id — name):", each `id` padded to 22 with its name, `[palette: <default>]` and the summary, then `Options: palette=… | background=… | mood=…`; `themes` prints "Bundled A–Z lexicons (offline themes):", each slug padded to 16 with "<title> — <theme>", then the Claude-fallback note; `new --theme THEME [--slug] [--title] [--subtitle] [--art-style ID] [--palette ID] [--background ID] [--mood ID] [--audience] [--provider auto|deterministic|anthropic] [--out DIR (default .)] [--print]`: no `--theme` → "error: --theme is required (see `zer0-cms themes`)" exit 1; warnings to stderr as "note: …"; `--print` prints the page Markdown and writes nothing; otherwise "✓ wrote <page>", "✓ wrote <spec>", "<N> illustration(s) to render:" with the first three and "…", then "Next: render the plates in drsai —" and the `generate_illustrations.py --book <slug> --dry-run` line. `--out` has none of the web target checks. Unknown command → usage, exit 1. Rake wrappers `abc:styles`, `abc:themes`, `abc:new THEME= STYLE= SLUG= PALETTE= PROVIDER= OUT= PRINT=` (`rails/lib/tasks/abc.rake`).
- Tests (`rails/test/zer0_cms/test_abc_engine.rb`, CI `abc-engine.yml`): the IT lexicon covers A–Z with "<L> is for" taglines; theme lookup is slug-insensitive; an unknown theme raises; the deterministic plan has 26 letters, A = Automation, default style `isometric-tech-toy`; the registry knows both providers; the six style ids exist; `render_prompt` is deterministic, contains "no text" and "AUTOMATION"; the wizard yields a valid 26-letter spec (series, slug, style); every letter has a prompt, an image under `/assets/images/books/it-alphabet/<l>-` and status planned; the cover image is `…/it-alphabet/cover.png`; an unknown style falls back with a warning; `auto` on a bundled theme needs no key; with `watercolor-storybook` and no palette, the palette is `cool-tech` and every letter and the cover prompt contain "sky blue" and none "terracotta"; a bad slug is invalid; the spec round-trips through JSON; the export writes a parseable page (layout `book-abc`, series `abc-language`, 26 letters, every prompt "no text") and a sidecar with `spec_version: 1`, and lists 27 planned images.

**Platform today**

- `content/agents/handlers/abc.py` (the drafter's `abc` profile): lexicon lookup with the same `_` slug and the 26-letter completeness check, from `content/agents/data/abc_lexicons/`; theme from `run.input.theme`, else `front_matter.theme`, else the page title; one `letter` block `{letter, word, tagline, subject, alt, image: None}` per letter the page lacks (letters it has are kept — a platform improvement); at policy `suggest` one Suggestion per letter, at `draft` one revision; output `{theme, provider: "lexicon", letters_added, suggestions | revision_id}`. An unbundled theme falls to `model_loop` with the drafter's generic brief prompt: through the provider registry (`content/agents/llm.py`, `content/ai/providers/`, so no direct SDK call), but with no ABC prompt, no plan schema, no 26-letter validation and no recording (`content/agents/recordings/drafter/` has none for it).
- Model: `BookPage` (`content/cms/models.py`) has `subtitle, author, series, profile (book|abc|story), audience, art_style`; no theme, language, palette, background, mood, lettering, cover or generator. `LetterBlock` (`content/cms/blocks.py`): `letter` `^[A-Z]$`, `word` ≤80, `tagline` ≤250, optional `subject` ≤400, `alt` ≤250, `image` (a Wagtail image); no `prompt`, image path or `status`. The handler sets none of the book fields.
- Import (`content/importers/jekyll.py`): `layout: book-abc` or an `alphabet:` → `profile="abc"`, each entry → a `letter` block (truncated to the field limits), the book fields from front matter. Export (`content/exporters/jekyll.py::_alphabet`, `front_matter_for`): `layout: book-abc` by default, the `alphabet:` rebuilt from the `letter` blocks merged into the source's entries (keeping `image`, `prompt`, `status`; overwriting `word`, `tagline`, `alt`; `subject` only when the entry has no prompt), path `<collections_dir>/_books/<slug>/index.md`; an unchanged page exports verbatim. Missing: the cover, `book/status/art_style_prompt/palette/lettering/cover_*/preview/description/generator` for a book made in the platform, prompts and image paths for a letter or a book made in the platform, the audience labels, the body paragraph, and a sidecar for a book made in the platform.
- Built for an edited letter: `content/books/abc.py` has `render_prompt` (the exact algorithm, over a vendored `content/books/data/abc_art_styles.yml`) and the image path, and the export plans a plate whose word or subject changed again — image `<old folder>/<l>-<word slug>.png`, prompt recomposed, status `planned` — and writes the sidecar, read on import onto `ImportedSource.sidecars`, verbatim while the book is unchanged and otherwise agreeing with the page; the write-back indexes, guards and records it (`content/tests/books/test_abc.py`, golden `content/tests/fixtures/abc/`, drsai's `import_abc_book.py --check` as the oracle).
- Nothing on the platform reads `abc-book.schema.json`; there is no `manage.py` command for styles, themes or a new book.
- Tests that exist: `content/tests/agents/test_drafter.py::test_the_abc_profile_writes_every_missing_letter_from_the_lexicon`, `content/tests/agents/test_drafter.py::test_an_unknown_abc_theme_falls_back_to_the_model` (only that it fails without a recording), `content/tests/agents/test_drafter.py::test_at_policy_draft_the_abc_drafter_writes_the_revision_itself`, `content/tests/cms/test_models.py::test_book_pages_take_chapters_and_letter_blocks`, `content/tests/importers/test_jekyll.py::test_each_file_becomes_the_right_page`, `content/tests/importers/test_jekyll.py::test_an_edited_page_exports_its_edits_over_its_front_matter`, `content/tests/importers/test_jekyll.py::test_the_real_sites_round_trip_byte_for_byte[sites/drsai]` (drsai's `it-alphabet` page round-trips unchanged); the drafter eval `abc-it-systems` (26 inserts). Vendored-copy drift is `bin/zer0 check`'s.

**Verdict** — `specified`: the platform writes the lexicon's letters and plans an edited plate again (its sidecar with it), nothing more — no spec, validation, art direction for a new book, cover, model plan contract or CLI.

**Build**

- Engine: `content/books/abc.py`, pure functions the API, the command and the drafter handler share (move `lexicon()`/`available()` here from `agents/handlers/abc.py`): `catalog()` (the menu above, from `content/books/data/abc_art_styles.yml`), `render_prompt(...)` (the exact algorithm above), `plan(theme, provider)` → `(plan, warnings)`, `build_spec(theme, **choices)` → `(spec, warnings)` with the resolution rules above (fix the slug quirk only by an explicit decision: the golden needs `slug` passed), `validate(spec)` = `Draft7Validator` over `schemas/books/abc-book.schema.json` plus the duplicate-letter rule, with the Rails messages, `render_page(spec)`, `sidecar(spec)` = `json.dumps(spec, indent=2, ensure_ascii=False) + "\n"` (verified byte-identical to the Ruby output on the golden), `planned_images(spec)`. The model path is the drafter's `abc` profile run: the Rails system and user prompts as the profile's prompt, the plan JSON Schema as the run's output `schema` (through `model_loop`/`ai` — the registry, budgets, schema validation), `validate_plan` on the result; refusal, no text and bad JSON fail the run with the Rails messages; a recording under `content/agents/recordings/drafter/abc-model/`. The handler also fills the book's fields (subtitle, series `abc-language`, art style, the knobs) from the plan on a new book.
- Model: the book-level knobs `theme`, `language`, `palette`, `background`, `mood`, `lettering` (and the cover subject) become `BookPage` data the studio edits — typed fields, or one `abc` JSON field validated by the schema's book-level subset; `art_style_prompt`, every `prompt`, `image` path and the cover are derived, never typed by a person.
- Exporter (`content/exporters/jekyll.py`, G4's `site_files`): for `profile="abc"`, the full front matter in the Rails key order with the audience labels, status and body paragraph, and a second file `_data/abc_books/<slug>.json`; a letter whose word or subject, or a book whose style knobs, differ from what its source entry was composed from gets its `prompt` and `image` recomposed, otherwise the source's are kept (so drsai still round-trips byte for byte); `status` stays as imported unless the word changed (`planned`) or the `letter` block has an image (`rendered`). Use the site's `collections_dir`, not a hard-coded `pages`.
- Command: `manage.py abc styles | themes | new` (`content/books/management/commands/abc.py`) with the Rails flags and output; `new` takes `--site KEY` (a registered site: writes through the write-back) or `--out DIR` (only a Jekyll root with a regular `_config.yml`, the `AbcExportTarget` rules) or `--print`; `--provider auto|lexicon|model` (`deterministic`/`anthropic` accepted as aliases); exit 1 on a missing `--theme` or an invalid spec.
- API / Studio / Extension: the wizard row's Build (this row adds no surface of its own beyond the command).
- Tests (`content/tests/books/test_abc.py` unless noted): `test_the_it_alphabet_sidecar_is_byte_identical_to_the_rails_golden` (`content/tests/fixtures/abc/_data/abc_books/it-alphabet.json`; theme "IT systems", slug `it-alphabet`, style `isometric-tech-toy`, lexicon); `test_the_it_alphabet_page_matches_the_rails_golden` (front matter equal as data in key order, body identical — PyYAML and Psych quote `/…` strings differently, so not bytes); `test_every_spec_and_the_golden_validate_against_the_abc_book_schema`; `test_spec_validation_rejects_bad_input` (parametrised: slug "Not A Slug", no title, no art style, audience "adult", 0 and 27 letters, a duplicate A, letter "a", a blank tagline — each with its message); `test_render_prompt_is_text_free_and_deterministic` (equals the golden's A prompt); `test_the_catalog_keeps_the_six_cross_repo_style_ids`; `test_an_unknown_art_style_falls_back_with_a_warning`; `test_the_palette_is_consistent_across_letters_cover_and_metadata` (watercolor-storybook → cool-tech, "sky blue" everywhere, no "terracotta"); `test_a_new_book_plans_a_cover_and_27_images`; `test_lexicon_lookup_ignores_case_and_spacing_and_refuses_a_missing_letter`; `test_auto_uses_the_lexicon_offline_and_the_model_otherwise` (fake provider: the plan schema was sent, 26 letters, the warning); `test_a_model_plan_missing_a_letter_or_refused_fails_the_run`; `content/tests/importers/test_jekyll.py::test_an_abc_book_made_in_the_platform_exports_its_page_and_sidecar`; `content/tests/books/test_abc.py::test_an_edited_word_exports_a_plate_planned_for_it_and_a_sidecar_that_agrees` (built; oracle: drsai's `import_abc_book.py --check`); `content/tests/books/test_commands.py::test_abc_styles_themes_and_new_print`; a drafter eval `abc-model` on the recording. Then `rails.abc-generator` and `imagegen.abc-art-styles` can be `done` on these proofs.
- Milestone: G9.

**Keep** — done when `rails/` was deleted, or recorded here instead of copied:

- The lexicon: `content/agents/data/abc_lexicons/it_systems.yml` was a byte-identical vendored copy of `rails/lib/zer0_cms/abc/lexicons/it_systems.yml`, the only lexicon on either side; the `vendored:` entry is gone and the platform copy is the source.
- The art styles: `rails/lib/zer0_cms/data/abc_art_styles.yml` was itself a vendored copy of `packages/zer0-image-generator/lib/zer0_image_generator/abc/art_styles.yml`, which stays. Copy it into `content/books/data/abc_art_styles.yml` when this is built, and before G11 deletes the package; fix its header there, which still says the Rails copy points back at it.
- The schema: `rails/schema/abc-book.schema.json` is now `schemas/books/abc-book.schema.json` (its description no longer names the Rails module; its `$id` is unchanged and unpublished). Nothing validates against it yet; the generator built here validates every spec it writes, and the golden, against it.
- The goldens: drsai's committed `sites/drsai/_data/abc_books/it-alphabet.json` and `sites/drsai/pages/_books/it-alphabet/index.md` at `d0a572fb` are the Rails generator's exact output (regenerated byte for byte from that commit's `rails/lib` with `theme "IT systems", slug it-alphabet, art_style isometric-tech-toy, provider deterministic`). Freeze them as `content/tests/fixtures/abc/` from that commit when the tests above are written — drsai's own copies change when plates are rendered. More goldens can be recorded from git history: `git archive d0a572fb rails/lib` and Ruby 3.0 or newer.

## Found while writing this spec

User-visible behaviour of `rails/app`, `rails/config` and `rails/lib/zer0_cms` (ABC, LinkedIn and distribution excluded) that no `sources:` row names or that a `done` row hides, and platform bugs the comparison turned up. None of it is fixed by the change that deleted `rails/`:

- **Rails' page edit form edited keys the studio cannot** (`page_dashboard.rb` `FORM_ATTRIBUTES_EDIT`, `page_editor.rb`):
  - `layout`, `permalink`, `status`, `preview` and `published`/`draft` (the last as checkboxes).
  - A "Not editable here (structured values): …" notice for keys holding maps or lists of maps.
  - Emptying a field deleted the key.
  - The studio's editor fields (`cms/models.py` `shared_editor_fields` + `ArticlePage.editor_fields`) cover title, slug, SEO, AI fields, date, author, tags and categories only. `preview_image` is not an editor field, and raw front matter is "to come" (content.edit).
  - G4 marks `rails.page-edit` done. Its proof covers the file write, not these fields. Track them under content.edit (P4), or reopen that row.
- **The page "file facts" view** (`SHOW_PAGE_ATTRIBUTES`): source path; front matter as indexed (pretty JSON); file bytes, mtime, SHA-256; the parse error. The studio shows none of them.
  - Nearest row: content.edit (raw front matter).
  - Proposal: a read-only "Source" tab in the page editor, showing `legacy_path`, `front_matter` and the `ImportedSource` digest.
- **Fixed: unpublishing in the studio unpublishes the Jekyll file.** Every write-back, not only "drafts too", gives a page that is not live `published: false` (what Rails' `published` checkbox wrote) under the stale-write guard and takes it off when the page goes live again — `content/tests/sites/test_sites.py::test_unpublishing_a_live_page_takes_its_file_down_and_republishing_restores_its_bytes`.
- **No producer of `app.user.interaction`.**
  - The graph's behavioural edges (`content/graph/consumers.py`, `build_viewed_together`) consume an event that nothing emits, and Rails never emitted it.
  - The producer belongs to the public site, through the P6 renderer, with an anonymous rotating `anon_id` and a beacon endpoint.
  - No row tracks it. Suggest one under sites.analytics.
- **Future-dated posts and `status: draft` files import as live** (rails.page-search's decision). Rails showed them as `future`/`draft` and kept them out of `live:`. Jekyll does not build a future post unless `future: true`.
- **Fixed: the importer finds previews under `assets/`, and SVG previews** (rails.assets-terms): `importers.jekyll.preview_file` tries the source, `source/assets` and the root, each confined by `sites/writer.py`, and an SVG is a Wagtail image like any other (`content/tests/importers/test_jekyll.py::test_a_preview_under_assets_is_found_like_the_engine_finds_it`).
- **Root `/` redirects to `/admin`; `/up` is Rails' health check.** Covered by platform.ops (`/healthz`, `/readyz`, `/version`; `content/tests/ops/test_health.py`). Nothing to build.
- **The "Image generator ↗" link-out** (sidebar, site page, page page; `ZER0_IMAGE_GENERATOR_URL`, only `http(s)` accepted, default `http://localhost:3000`) is covered by the imagegen.* rows (G6's Media area). Nothing to build.
