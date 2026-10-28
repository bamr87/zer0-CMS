# `books/` — books in the platform

Books are written in the platform, with AI assistance, and each book's `library/<slug>/` is the statically generated set of files it exports to ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decisions 13 and 14, [TARGET.md](../../docs/plan/TARGET.md) § Books, PLAN G9). This app absorbs `packages/books` — the bookshelf CLI, its validator, statistics, manuscripts and dashboard, its local studio and its Claude-backed tasks — onto the platform's pages, the AI content layer and the studio.

## The pieces

| File | What |
|---|---|
| `../cms/models.py` | `BookPage` and `ChapterPage` hold what the files hold: the manifest's fields (`book_status`, `logline`, `genre`, `pov`, `tense`, `era`, `protagonist`, `acts`, `planned_chapters`, `target_word_count`, `themes`, `cast`), the `outline`, `character_notes`, `continuity_notes`, `style_guide` and the book's other files (`documents`); a chapter's front matter (`number`, `subtitle`, `act`, `chapter_status`, `pov`, `era`, `characters`, `setting`, `tone`, `style`) and its body as blocks. Every other key stays in `front_matter`, in source order. |
| `models.py` | `LibraryFile`: what the platform last read from or wrote to each file of a library directory — its digest, its page, that page's content hash then — so the import and the export can tell each other's changes apart |
| `files.py` | The generated file set: a book's tree rendered from its latest revisions or its live content (`render_book`, `book_tree`), the importer (`import_library`) and the exporter (`export_library`) |
| `library.py` | The read model over a book's files — chapters, prose, narrative-only word counts, the validator with bookshelf's codes, the manuscript, `library.json`'s shape |
| `context.py` | The book tasks (`TASKS`) and what their model is given: the brief, the act guide, the neighbouring chapters, the chapter, the task |
| `services.py` | Every command: the library's shelf, a book's overview, statistics, validation, the manuscript, the library's data and dashboard, a new book from the template, a chapter, a book's other files, running a task, a book from a premise, the bundled AI setup |
| `handlers.py` | What a run of the `books` agent does in the worker (`../agents/definitions/books.yaml` points here) |
| `serializers.py`, `views.py`, `urls.py` | `/api/v2/books/` for the studio |
| `management/commands/` | `import_books`, `export_books`, `roundtrip_books`, `books <command>` |
| `data/` | The bundled assistants (bookshelf's house rules and one role per task), the book-outline and continuity-findings output schemas and a pipeline, seeded after every migrate |
| `templates/books/dashboard.html` | The static shelf `books dashboard` writes |

## The library as a generated file set

| In `library/<slug>/` | In the platform |
|---|---|
| `book.yml` | the `BookPage`'s title, subtitle, author and manifest fields; every key in `front_matter` |
| `outline.md`, `notes/characters.md`, `notes/continuity.md`, `notes/style-guide.md` | `outline`, `character_notes`, `continuity_notes`, `style_guide` |
| `chapters/chNN.md` | a `ChapterPage` under the book: front matter as fields, the body as blocks |
| anything else (`README.md`, `guides/*.md`, `chapters/.gitkeep`, an empty notes file) | the book's `documents`, verbatim |

The file a page was read from is kept beside it (`importers.ImportedSource`: `book.yml` for a book, the chapter's file for a chapter), and a page renders over it: a YAML key is rewritten only when its value changed — line surgery, so comments, quoting and every other line stay — and a chapter body that still has the blocks it was read as is written as it was. An unchanged book exports exactly the files it was imported from: `manage.py roundtrip_books` imports the library into a throwaway transaction, exports it and compares every file (26 of 26 identical on `packages/books/library`, `impairment` and `_template`). A book made in the platform renders a manifest from its `front_matter` and fields.

Two chapters never share a file. A chapter keeps its own file while that file's name carries its number and otherwise takes `chNN.md`; when two chapters want one name — a person renumbering chapters in the studio passes through that — the later keeps its own file, or takes a longer name for its number (`ch002.md`). Both stay in the book, the manuscript and its statistics, and validation reports `chapter-duplicate` until the numbers are fixed.

**Neither command loses what the other side changed.** Every file the platform reads from or writes to a library directory is recorded per directory (`LibraryFile`), so an export to a scratch directory never makes the library's own files look changed:

- `export_books` writes what is live (`--include-drafts`: the latest revisions, which is what a person sees in the studio). It writes a file only when the file is missing or still exactly what the platform last read or wrote there; a file changed by hand since is kept and reported as a conflict (exit status 1; `--force` overwrites it). A file the platform no longer has there — a renumbered chapter's old name, a deleted or unpublished chapter's file, a removed document, a deleted book's directory — is removed while it is unchanged since, and kept as a conflict otherwise. Files the platform never held are listed (`--prune` deletes them).
- `import_books` matches each file to the page last read from or written to it (else to the file the page was read from, else to the name the page wants now), so a chapter renumbered in the studio keeps its old file until an export moves it, and nothing is created twice. A file unchanged since leaves the platform's newer content alone. A changed file updates its page only while that page has not changed in the platform since — otherwise it is a reported conflict (`--force` takes the file). An update is published, by `legacy:import` as the other importers publish, only over a live page with no draft; over a draft, or over a person's unpublished draft, it is a new draft revision. A new book is published; a new chapter is published only under a live book. A page deleted in the platform is not brought back (its file is a conflict once changed by hand; `--force` reads it in again), and a chapter whose file is gone is reported, never deleted.

A directory whose name starts with `_` is a template (`_template`): it round-trips like a book, is never on the shelf, and `books new` (and the studio's "New book") starts a book from it — its manifest, its outline with `{{title}}` and `{{slug}}` filled, its other files — stamped with the slug, title, `status: idea` and today's date.

The library lives at `packages/books/library/` for now (`BOOKS_LIBRARY_DIR`, under the site root `BOOKS_SITE_KEY`, default `library`, with its Wagtail site `library.localhost`); PLAN G11 decides its permanent home. The image carries only `content/`, so under Docker Compose the `content` service bind-mounts the library from the checkout. The Books workspace holds the library's books; a Jekyll site's books (drsai's picture books, the ABC books) stay that site's pages until the ABC wizard and the story engine become book types (`books.abc`).

## The bookshelf's commands

`manage.py books list | show | new | add-chapter | validate | stats | build | dashboard | context` are bookshelf's `books` commands with their output. Everything is computed from the book's rendered files, so the platform says what bookshelf said: on the real library the findings, `library.json`, both manuscripts and the assistant's context are identical (`../tests/books/golden/bookshelf.json`, recorded from `packages/books/src`). The validation codes are the books package's (`packages/books/docs/SCHEMA.md`); a relative link that leaves the book's directory is the one thing not checked, because the generated set is the book's files and nothing else. `build` writes `dist/<slug>/manuscript.md` beside the library, `dashboard` writes `dist/index.html` and `dist/library.json`. `books studio`, `serve` and `ask` are the studio's Books area now.

## AI-assisted writing

Every task is a run of the GitOps `books` agent through the AI content layer — the provider registry, the runner's loop, the output schema validated — and every result is reviewed by a person:

| Task | On | What a person gets |
|---|---|---|
| Draft | a chapter | the chapter's prose replaced — as suggestions |
| Continue | a chapter | the prose carried on where it stops, in its voice — a suggestion |
| Revise | a chapter and a passage | the passage rewritten to an instruction — a suggestion on the block that holds it |
| Continuity check | a chapter | structured findings (severity, kind, quote, problem, suggestion) and a summary, in the bundled continuity-findings schema |
| Critique | a chapter | an editor's read |
| Outline | a book | a structured outline rendered as `outline.md`, which the person may apply to the book |

The prose is found as the read model finds it (`library.prose_spans`): what is under "Chapter Body", else what is outside the outline scaffolding — whether the sections are heading blocks or `#` headings inside one Markdown block (`impairment`'s ch03 and ch05) — so Draft and Continue never touch a chapter's outline, references or navigation. The brand guard judges a suggestion on what it adds (`suggestions/guard.py`): a banned phrase the author already wrote does not block Continue or Revise on that chapter; the model using one does.

A run is given the book's own material, assembled as bookshelf's assistant assembled it (`context.py`): the brief (facts, the cast as the only names to use, the outline, the character bible, the continuity ledger, the style guide, the chapters so far), the act guide covering the chapter, the prose of the chapters either side, the chapter's whole file, and the task with the person's instruction and selection. The bundled assistants carry bookshelf's house rules and the books package's authoring guidance; a person may run a task with an assistant of their own. Suggestions are proposed through the tool registry (`content.propose_edit`, as `agent:books`, on behalf of the person who asked), so their edit right on the chapter is checked again in the worker. A book's notes reach a model only in a book task's request: they are not copied into the agents' `Memory`, whose `memory.recall` checks no page rights.

A book from a premise is an `ai.Brief` the bundled outliner generates — the structured outline, rendered, with its metadata — followed on its run; when the person accepts it, `create_from_brief` makes the book as a draft with its facts and outline and a stub per planned chapter. The model's values go into the person's draft revisions (they read the outline before accepting it; a suggestion's `meta` op covers the title and SEO fields only), each cut to its field so one long or empty value never costs the book; the brief records the book it made. Applying the same brief through the AI layer's generic endpoint makes the same book (`BookPage.from_brief`). Nothing is published.

## The API (`/api/v2/books/`)

| Path | |
|---|---|
| `GET /` | the library's shelf (`?templates=true`: the templates); `POST /` a new book from the template |
| `GET tasks/` | the tasks |
| `POST premise/` | a premise → an outline brief, generated as a run (`202`); `POST premise/<brief>/create/` makes the book from the ready brief |
| `GET <id>/` | a book's overview: facts, chapters in order, statistics, findings counts, its file paths |
| `GET <id>/issues/` | its findings |
| `POST <id>/chapters/` | the next chapter, as a draft stub |
| `GET`, `POST <id>/documents/` | its other files (act guides, README) and the revision they are from; add, change or (`text: null`) remove one, as a draft revision over that revision (`409` when a newer one exists) |
| `GET <id>/manuscript/` | the compiled manuscript (`?include_outline=true`) |
| `GET <id>/context/` | what a task's model would be given (`?chapter=<id>&task=…`) |
| `POST <id>/assist/` | run a task (`202` with the run, `Idempotency-Key` honoured) |

A book's own fields — its manifest, outline, notes and style guide — and a chapter's are edited through the generic page endpoints (`/api/v2/content/pages/<id>/`), as draft revisions with the stale-write guard. Only people use these endpoints; a book is found among the library's books they may open, else a 404.

## Tests

`../tests/books/`: the round trip on the real library and the import's and the export's rules — a hand edit kept, no draft published, nothing created twice or brought back, two chapters with one number (`test_files.py`) — every validation code on fixtures and the parity with bookshelf (`test_library.py`), every task on the scripted fake provider including the real book's `#`-sectioned chapters and a banned phrase in its own prose, the premise flow, the worker's re-checks (`test_ai.py`), the API with a book's other files and a Jekyll site's books kept off the shelf (`test_api.py`) and the commands (`test_commands.py`). The `books` agent's evals replay `../agents/recordings/books/`.

## Not here yet

The ABC wizard and drsai's story engine as book types and generators (the Rails ABC wizard and generator are specified in [`docs/plan/rails-cms-spec.md`](../../docs/plan/rails-cms-spec.md), drsai's story engine is in `sites/drsai`; the drafter's `abc` and `story` profiles exist); parts between a book and its chapters (open decision P-D8: today a book's parts are its acts); pipelines and conversations over a book's own material (the bundled premise-to-critiqued-outline pipeline runs on a premise from the AI area); a hand edit to a generated file arriving as a suggestion rather than an update or a conflict; the export committed by a job (G4's jobs); the manuscript fields of a Jekyll site's book or chapter in that site's export (the studio edits them, `export_jekyll` does not write them); prompt caching of a book's brief (the adapters' job); and the extension's Books counterpart (G10).
