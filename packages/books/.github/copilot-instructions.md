# AI agent instructions

This repository is a shelf of book projects plus a small Python app that manages them. Most work here is prose; some is code. Know which one you are doing.

## Layout

```
library/<slug>/     a book — book.yml, outline.md, chapters/chNN.md, guides/, notes/
library/_template/  what `books new` copies
src/bookshelf/      the app — cli, validate, server + editor (the studio), ai (the assistant)
tests/
docs/               STUDIO.md, SCHEMA.md, ARCHITECTURE.md, reviews/
```

Chapter files are zero-padded (`ch01.md`) so they sort in reading order. `book.yml` and chapter front matter are validated — the field list and every check code are in [`../docs/SCHEMA.md`](../docs/SCHEMA.md).

## Working on prose

1. **Read before writing.** The book's `outline.md`, the act guide in `guides/` covering your chapter, and the chapters either side of it. Continuity is the thing that breaks first.
2. **Check the notes.** `notes/characters.md` is the only place a name is decided; `notes/continuity.md` holds settled facts and open questions. If you need a name that is not in the character bible, add it there in the same change.
3. **Follow the chapter skeleton.** Front matter, then `## Outline and Contextual Alignment`, then `## Chapter Body`, then `## References & Contextual Alignment`, then `## Links and References`. The templates in [`instructions/`](instructions/) spell out each section.
4. **Keep planning out of the prose.** Never write `(Chapter 8)` or quote another chapter's title inside the narrative. The reader cannot see your outline. This is the single most common defect in the existing draft — 117 instances, catalogued in [`../docs/reviews/impairment.md`](../docs/reviews/impairment.md).
5. **Never ship a placeholder.** `[Company Name]`, `[TBD]` and friends are validation errors, not TODOs. If a fact is undecided, add it to `notes/continuity.md` as an open question rather than writing around it.
6. **Cross-reference honestly.** If your change affects an earlier or later chapter, say so in the PR body with the specific file and section. Do not silently rewrite neighbours.

## Working on code

- No required runtime dependencies. `bookshelf` parses the documented YAML subset with the standard library so `books validate` works in a bare checkout; PyYAML is used when present. Do not add a hard dependency without a good reason.
- Only `cli.py` prints. Everything below it returns values.
- A new check belongs in `validate.py` as an `Issue`, with a code, a test, and a row in `docs/SCHEMA.md`.
- A new assistant task is an entry in `ai.TASKS`. What the model is given comes from `build_brief` / `build_local`; verify a change with `books context <slug> --chapter N`, which makes no API call. Tests use a stub client and must never hit the network.
- Do not suppress type errors or leave empty exception handlers.

## Before you finish

```bash
python3 -m pytest
books validate                      # or: PYTHONPATH=src python3 -m bookshelf validate
python3 tools/unwrap-prose.py --check
```

Markdown in this repository is **one paragraph per line** — no soft wrapping. CI enforces it; `--write` fixes it.

## Commits and PRs

- Conventional Commits: `type(scope): description`. Scope is the book slug for prose (`feat(impairment): draft ch07`) or the module for code (`fix(validate): ...`).
- Branch from `main`; never push to it directly.
- PR body: what changed, which files, and any continuity follow-ups other chapters now need.
