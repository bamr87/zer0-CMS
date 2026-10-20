# library

One directory per book. A directory is a book when it contains `book.yml`; names starting with `_` are reserved, which is how `_template` stays off the shelf.

## What is here

| Directory | Status | About |
| --- | --- | --- |
| [`impairment/`](impairment/) | drafting | The Impairment — a financial thriller about the wars fought on a balance sheet. |
| `_template/` | — | The skeleton `books new` copies. Edit it to change what every future book starts as. |

## Anatomy of a book

```
<slug>/
  book.yml      manifest — title, status, acts, targets, cast, themes
  outline.md    synopsis, three-act structure, character arc, chapter plan
  chapters/
    chNN.md     zero-padded so files sort in reading order
  guides/       per-act drafting guidance for this book
  notes/        character bible, continuity ledger
```

`book.yml` and chapter front matter are both validated — see [`../docs/SCHEMA.md`](../docs/SCHEMA.md) for every field and check.

## Adding a book

```bash
books new <slug> --title "..." --logline "..."
```

Then fill in `outline.md`, set `status` to `outlining` once the acts are sketched, and start adding chapters with `books add-chapter <slug> --title "..."`.

A book can sit at `status: idea` indefinitely with nothing but a `book.yml` and a logline. That is the point of having a shelf — an idea does not have to be a manuscript to be worth keeping.
