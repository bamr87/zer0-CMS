# Architecture

## The one idea

The library is plain markdown and YAML on disk. `bookshelf` is a read model over it, not a database that owns it.

Every book remains editable, diffable and readable with nothing but a text editor — delete `src/` and no content is lost. That constraint is what picks the design: no index to rebuild, no migration to run, no state that can disagree with the files. The tool derives everything it reports, every time.

## Layout

```
library/            content — the only thing that matters long term
  _template/        seeds `books new`; edit it to change what new books look like
  <slug>/
    book.yml        manifest: identity, status, targets, cast, themes
    outline.md      the pitch, the acts, the chapter plan
    chapters/
      chNN.md       front matter + outline scaffolding + prose
    guides/         per-act drafting guidance for this book
    notes/          character bible, continuity ledger
src/bookshelf/      the app
tests/
docs/
dist/               generated; gitignored
```

A directory under `library/` is a book when it contains `book.yml`. Names starting with `_` or `.` are reserved, which is how `_template` stays off the shelf.

## Modules

Each one does a single job, and they stack in this order:

| Module | Responsibility |
| --- | --- |
| `frontmatter` | Split a markdown file into a metadata mapping and a body. PyYAML when available, a documented subset parser when not. |
| `models` | `Book`, `Chapter`, `Issue`. Normalises legacy keys, locates narrative prose, counts words. |
| `library` | Finds the repository root and discovers books under it. |
| `validate` | Every check, returning `Issue` values. Knows nothing about output. |
| `build` | Compiles chapters into a manuscript; serialises the library to JSON. |
| `dashboard` | Renders the library as one self-contained HTML page. |
| `scaffold` | Creates new books and chapters from `library/_template`. |
| `server` | The studio's JSON API and SSE endpoint. Request handling lives in a plain class so every endpoint is testable without a socket. |
| `editor` | The studio page: one self-contained HTML document, no bundler and no CDN. |
| `ai` | Assembles the book's own material into a request and talks to Claude. The only module with a dependency, and it is optional. |
| `cli` | Argument parsing and formatting. The only module that prints. |

Nothing below `cli` writes to stdout, and nothing below `library` knows where the repository is. That is what makes the validator usable from a test, a hook or an editor integration without capturing output.

## Decisions worth knowing about

**Prose is located by heading, not by convention.** Word counts and the compiled manuscript both need to know which part of a chapter is the story and which part is planning scaffolding. `models.prose_spans` answers that from the heading tree: the `Chapter Body` section plus everything nested under it, or — for a file that has not adopted the skeleton — everything not under a known scaffold heading. It returns character ranges rather than stitched text, so a finding at "line 62" is really at line 62 of that file.

**No required dependencies.** The shared CI gate installs the package with `pip install -e . || true`, so a dependency that fails to install would surface as an unexplained wall of import errors. Parsing the documented front matter subset with the standard library means `books validate` works in a bare checkout, which is the normal state of a prose repository. PyYAML is used automatically when present and both paths are tested against the same fixture.

**The assistant is the one exception, and it is contained.** `ai.py` needs the Anthropic SDK, declared as the `ai` extra and imported inside the function that builds a client — so importing `bookshelf.ai` costs nothing and the studio, the validator and the CLI all run without it. `books studio` says on startup when AI features are unavailable rather than failing at the first click.

**Context beats prompting.** Most of `ai.py` is not prompt text; it is the code that assembles the book's outline, act guide, character bible, continuity ledger and neighbouring chapters into a request. That material is stable across a run of tasks against one chapter, so it carries the cache breakpoints and the per-request task sits after them. `books context` prints exactly what would be sent, which is also how the assembly is inspected without spending a token.

## Where the checks came from

`validate.py` is not a generic linter. Every check in it exists because the `impairment` draft tripped over it — unresolved `[Company Name]` placeholders in a finished chapter, outline bookkeeping leaking into a character's letter, a point of view that flipped after chapter one, prev/next links pointing at the wrong file. [`reviews/impairment.md`](reviews/impairment.md) is the audit; the validator is that audit made repeatable.

That is the intended way to grow the tool: find a problem by reading, then encode it so it is never found by reading again.
