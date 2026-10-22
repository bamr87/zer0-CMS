# `books/` — books in the platform

Books are written in the platform, with AI assistance, and each book's `library/<slug>/` is the statically generated set of files it exports to ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decisions 13 and 14, [TARGET.md](../../docs/plan/TARGET.md) § Books, PLAN G9). This app absorbs `packages/books` — the bookshelf CLI, its validator, statistics, manuscripts and dashboard, its local studio and its Claude-backed tasks — onto the platform's pages, the AI content layer and the studio.

## The pieces

| File | What |
|---|---|
| `../cms/models.py` | `BookPage` and `ChapterPage` hold what the files hold: the manifest's fields (`book_status`, `logline`, `genre`, `pov`, `tense`, `era`, `protagonist`, `acts`, `planned_chapters`, `target_word_count`, `themes`, `cast`), the `outline`, `character_notes`, `continuity_notes`, `style_guide` and the book's other files (`documents`); a chapter's front matter (`number`, `subtitle`, `act`, `chapter_status`, `pov`, `era`, `characters`, `setting`, `tone`, `style`) and its body as blocks. Every other key stays in `front_matter`, in source order. |
| `files.py` | The generated file set: a book's tree rendered from its latest revisions (`book_tree`), the importer (`import_library`) and the exporter (`export_library`) |
| `library.py` | The read model over a book's files — chapters, prose, narrative-only word counts, the validator with bookshelf's codes, the manuscript, `library.json`'s shape |
| `context.py` | The book tasks (`TASKS`) and what their model is given: the brief, the act guide, the neighbouring chapters, the chapter, the task |
| `services.py` | Every command: the shelf, a book's overview, statistics, validation, the manuscript, the library's data and dashboard, a new book from the template, a chapter, running a task, a book from a premise, the agents' memory of a book, the bundled AI setup |
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
| anything else (`README.md`, `guides/*.md`, `chapters/.gitkeep`) | the book's `documents`, verbatim |

The file a page was read from is kept beside it (`importers.ImportedSource`: `book.yml` for a book, the chapter's file for a chapter), and a page renders over it: a YAML key is rewritten only when its value changed — line surgery, so comments, quoting and every other line stay — and a chapter body that still has the blocks it was read as is written as it was. An unchanged book exports exactly the files it was imported from: `manage.py roundtrip_books` imports the library into a throwaway transaction, exports it and compares every file (26 of 26 identical on `packages/books/library`, `impairment` and `_template`). A book made in the platform renders a manifest from its `front_matter` and fields.

`import_books` is idempotent and never overwrites what was changed in the platform: a file that is what the platform would write now is in sync; a file unchanged since the last import leaves the platform's newer content alone; a changed file updates its page — unless the page was changed here since (or was made here and never imported), which is a reported conflict (`--force` takes the file). Imported pages are published by `legacy:import`, as the other importers do; a chapter whose file is gone is reported, never deleted. `export_books` writes only files that differ, removes a renumbered chapter's old file when it is still exactly what the platform last read or wrote, and lists every other file it does not hold (`--prune` deletes them).

A directory whose name starts with `_` is a template (`_template`): it round-trips like a book, is never on the shelf, and `books new` (and the studio's "New book") starts a book from it — its manifest, its outline with `{{title}}` and `{{slug}}` filled, its other files — stamped with the slug, title, `status: idea` and today's date.

The library lives at `packages/books/library/` for now (`BOOKS_LIBRARY_DIR`, under the site root `BOOKS_SITE_KEY`, default `library`, with its Wagtail site `library.localhost`); PLAN G11 decides its permanent home.

## The bookshelf's commands

`manage.py books list | show | new | add-chapter | validate | stats | build | dashboard | context` are bookshelf's `books` commands with their output. Everything is computed from the book's rendered files, so the platform says what bookshelf said: on the real library the findings, `library.json`, both manuscripts and the assistant's context are identical (`../tests/books/golden/bookshelf.json`, recorded from `packages/books/src`). The validation codes are the books package's (`packages/books/docs/SCHEMA.md`); a relative link that leaves the book's directory is the one thing not checked, because the generated set is the book's files and nothing else. `build` writes `dist/<slug>/manuscript.md` beside the library, `dashboard` writes `dist/index.html` and `dist/library.json`. `books studio`, `serve` and `ask` are the studio's Books area now.

## AI-assisted writing

Every task is a run of the GitOps `books` agent through the AI content layer — the provider registry, the runner's loop, the output schema validated — and every result is reviewed by a person:

| Task | On | What a person gets |
|---|---|---|
| Draft | a chapter | the chapter's prose (the blocks under "Chapter Body", else outside the scaffolding) replaced — as suggestions |
| Continue | a chapter | the prose carried on where it stops, in its voice — a suggestion |
| Revise | a chapter and a passage | the passage rewritten to an instruction — a suggestion on the block that holds it |
| Continuity check | a chapter | structured findings (severity, kind, quote, problem, suggestion) and a summary, in the bundled continuity-findings schema |
| Critique | a chapter | an editor's read |
| Outline | a book | a structured outline rendered as `outline.md`, which the person may apply to the book |

A run is given the book's own material, assembled as bookshelf's assistant assembled it (`context.py`): the brief (facts, the cast as the only names to use, the outline, the character bible, the continuity ledger, the style guide, the chapters so far), the act guide covering the chapter, the prose of the chapters either side, the chapter's whole file, and the task with the person's instruction and selection. The bundled assistants carry bookshelf's house rules and the books package's authoring guidance; a person may run a task with an assistant of their own. Suggestions are proposed through the tool registry (`content.propose_edit`, as `agent:books`, on behalf of the person who asked), so their edit right on the chapter is checked again in the worker.

A book from a premise is an `ai.Brief` the bundled outliner generates — the structured outline, rendered, with its metadata — followed on its run; when the person accepts it, `create_from_brief` makes the book as a draft with its facts and outline and a stub per planned chapter. Nothing is published. The continuity ledger and the character bible are the agents' memory of the book (`memory.recall` with scope `page`, the book's id, keys `book.continuity` and `book.characters`), refreshed on every saved revision.

## The API (`/api/v2/books/`)

| Path | |
|---|---|
| `GET /` | the shelf (`?templates=true`: the templates); `POST /` a new book from the template |
| `GET tasks/` | the tasks |
| `POST premise/` | a premise → an outline brief, generated as a run (`202`); `POST premise/<brief>/create/` makes the book from the ready brief |
| `GET <id>/` | a book's overview: facts, chapters in order, statistics, findings counts, its other files |
| `GET <id>/issues/` | its findings |
| `POST <id>/chapters/` | the next chapter, as a draft stub |
| `GET <id>/manuscript/` | the compiled manuscript (`?include_outline=true`) |
| `GET <id>/context/` | what a task's model would be given (`?chapter=<id>&task=…`) |
| `POST <id>/assist/` | run a task (`202` with the run, `Idempotency-Key` honoured) |

A book's own fields — its manifest, outline, notes and style guide — and a chapter's are edited through the generic page endpoints (`/api/v2/content/pages/<id>/`), as draft revisions with the stale-write guard. Only people use these endpoints; a book is found among the pages they may open, else a 404.

## Tests

`../tests/books/`: the round trip on the real library and the import's rules (`test_files.py`), every validation code on fixtures and the parity with bookshelf (`test_library.py`), every task on the scripted fake provider, the premise flow, the worker's re-checks and the memory (`test_ai.py`), the API (`test_api.py`) and the commands (`test_commands.py`). The `books` agent's evals replay `../agents/recordings/books/`.

## Not here yet

The ABC wizard and drsai's story engine as book types and generators (`rails/` and `sites/drsai`; the drafter's `abc` and `story` profiles exist), parts between a book and its chapters, a hand edit to a generated file arriving as a suggestion rather than an update (today it updates the page, or is a conflict), the export committed by a job (G4's jobs), prompt caching of a book's brief (the adapters' job), and the extension's Books counterpart (G10).
