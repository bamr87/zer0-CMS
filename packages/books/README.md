# books

A shelf for book ideas, an editor to write them in, and an assistant that knows what is already on the page.

Each book lives in `library/<slug>/` as plain markdown and YAML — a manifest, an outline, numbered chapters, drafting guides and continuity notes. The `books` command reads that directory and gives you the things a folder of markdown cannot: a status view across every project, schema and continuity checks, word counts that ignore your outline scaffolding, a compiled manuscript, and a static dashboard.

Nothing is locked up. Delete `src/` and every book is still there, still readable, still editable in any text editor.

---

## Quickstart

```bash
pip install -e ".[ai]"     # omit [ai] for everything except the assistant
export ANTHROPIC_API_KEY=...

books studio --open       # the editor
books list                # what is on the shelf
books show impairment     # one book, chapter by chapter
books validate            # schema + continuity checks
books dashboard && open dist/index.html
```

No dependencies are required for anything except the assistant. PyYAML is used if it happens to be installed; otherwise the documented front matter subset is parsed with the standard library, so `books validate`, `books build` and the editor all work in a bare checkout. See [`docs/SCHEMA.md`](docs/SCHEMA.md).

## Commands

| Command | What it does |
| --- | --- |
| `books list [--status S] [--json]` | Every book with status, chapter count, word count and progress. |
| `books show <slug> [--json]` | One book: metadata, cast, and a chapter table. |
| `books new <slug> --title "..."` | Scaffold a new book from `library/_template`. |
| `books add-chapter <slug> --title "..."` | Add the next chapter file, pre-filled from the book's defaults. |
| `books validate [slug...] [--strict]` | Schema, numbering, links and continuity. Exits non-zero on errors. |
| `books stats [slug...]` | Word counts, chapter status breakdown, longest and shortest. |
| `books build [slug...]` | Compile chapters into `dist/<slug>/manuscript.md`, scaffolding stripped. |
| `books dashboard` | Render the whole library as one self-contained `dist/index.html`. |
| `books serve [--port N]` | Build the dashboard and serve it locally. |
| `books studio [--open]` | The editor: write, manage the shelf, and get AI help. |
| `books ask <slug> <task>` | Run one assistant task from the terminal. |
| `books context <slug>` | Print what the assistant would be given, without calling it. |

`--root PATH` overrides repository detection; otherwise the nearest parent containing `library/` wins.

## Starting a new book

```bash
books new the-quiet-part --title "The Quiet Part" --logline "A speechwriter starts telling the truth."
books add-chapter the-quiet-part --title "Opening Remarks"
books validate the-quiet-part
```

`books new` copies `library/_template/`, so editing that directory changes what every future book starts as.

## The studio

`books studio` opens a local web app: the shelf on the left, the chapter's markdown in the middle, and Assist plus Checks on the right. It edits the files in `library/` directly — nothing is imported, and your usual editor keeps working.

The assistant is given the book's own material, not generic craft advice: the outline, the act guide covering that chapter, the character bible, the continuity ledger, and the full text of the chapters either side. It can draft, continue, revise a selection, critique, or run a structured continuity check that returns the exact quote at fault. Nothing it writes touches the chapter until you insert it.

```bash
books context impairment --chapter 7   # exactly what would be sent, no tokens spent
books ask impairment critique --chapter 7
```

Full guide: [`docs/STUDIO.md`](docs/STUDIO.md).

## What validation catches

Beyond schema and numbering, the checks encode editorial problems that are cheap to catch and expensive to leave: unresolved `[Company Name]` placeholders still sitting in finished prose, outline bookkeeping like `(Chapter 8)` leaking into the narrative, prev/next links pointing at the wrong chapter, a character named in a chapter but not in the book's cast, and a point of view or era that drifts away from the rest of the book.

Each check exists because a real draft in this repository tripped over it — see [`docs/reviews/impairment.md`](docs/reviews/impairment.md).

## The shelf

| Book | Status | Chapters | About |
| --- | --- | --- | --- |
| [The Impairment](library/impairment/) | drafting | 14 | A laid-off systems engineer discovers that the goodwill impairment that cost him his job was cover for a covert transfer of technology to a foreign military regime. |

`books validate impairment` currently reports 3 errors and 120 warnings. They are real, and they are catalogued in the [review](docs/reviews/impairment.md) — the tool is reporting the draft's actual state, not failing.

## Layout

```
library/            books — the content, and the point of the repository
  _template/        what `books new` copies
  impairment/       book.yml · outline.md · chapters/ · guides/ · notes/
src/bookshelf/      the app — CLI, validator, studio server, editor, assistant
tests/              pytest suite
docs/               studio guide, schema, architecture, editorial reviews
dist/               generated output (gitignored)
```

## Contributing

- Read the nearest `README.md` before changing a directory, and update it after.
- Conventional Commits: `type(scope): description`.
- Branch from `main` and open a PR; never push to `main` directly.
- Markdown is one paragraph per line. Fix with `python3 tools/unwrap-prose.py --write`.
- Run `python3 -m pytest` and `books validate` before pushing.

More detail in [`CLAUDE.md`](CLAUDE.md) and [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).
