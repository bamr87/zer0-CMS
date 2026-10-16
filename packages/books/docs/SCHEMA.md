# Schema

Two file formats carry all the metadata in the library: `book.yml` (one per book) and the YAML front matter at the head of each chapter. `books validate` checks both.

---

## `library/<slug>/book.yml`

### Required

| Key | Type | Notes |
| --- | --- | --- |
| `title` | string | The book's title. |
| `status` | enum | `idea`, `outlining`, `drafting`, `revising`, `complete`, `archived`. |

### Recommended

| Key | Type | Notes |
| --- | --- | --- |
| `slug` | string | Must equal the directory name. Validated when present. |
| `subtitle` | string | |
| `logline` | string | One sentence: who wants what, and what stands in the way. Shown by `books list`. |
| `genre` | string | |
| `pov` | string | The book's default point of view. Seeds new chapters. |
| `tense` | string | |
| `era` | string | Seeds new chapters. |
| `protagonist` | string | |
| `acts` | int | Default `3`. Bounds the `act` a chapter may declare. |
| `planned_chapters` | int | Drives progress when no word target is set. |
| `target_word_count` | int | Drives progress when set. |
| `tags` | list | |
| `themes` | list | |
| `cast` | list | Every name a chapter may list under `characters`. A chapter naming someone outside it gets a warning — that is how a misspelling or an accidental second name for one character gets caught. Leave `cast` empty to switch the check off. |
| `alt_titles` | list | Working titles. |
| `comparables` | list | "X meets Y". |
| `created` | date | Stamped by `books new`. |

---

## `library/<slug>/chapters/chNN.md`

Filenames are zero-padded (`ch01.md`, not `ch1.md`) so lexical order matches reading order. Numbers must be contiguous from 1.

### Required

| Key | Type | Notes |
| --- | --- | --- |
| `title` | string | |
| `number` | int | Must match the filename. Falls back to the filename when absent. |

### Recommended

| Key | Type | Notes |
| --- | --- | --- |
| `subtitle` | string | |
| `act` | int | Must be within the book's `acts`. |
| `status` | enum | `stub`, `outline`, `draft`, `revised`, `final`. Defaults to `draft`. |
| `pov` | string | Checked for drift against the rest of the book. |
| `era` | string | Checked for drift against the rest of the book. |
| `characters` | list | Checked against the book's `cast`. |
| `setting` | list | |
| `tone` | list | |
| `style` | string | |

`character` (singular) is read as `characters`, `settings` as `setting`, and `theme` as `themes`, so older files still parse.

### Body structure

A chapter body is markdown. Two heading families are meaningful to the tools:

- **`## Chapter Body`** opens the narrative, and everything nested under it counts as prose. This is what word counts measure and what `books build` compiles.
- **`## Outline and Contextual Alignment`**, **`## References & Contextual Alignment`**, **`## Links and References`** and **`## Suggested Minor Updates`** are scaffolding. They are excluded from word counts and stripped from the compiled manuscript.

A chapter with no `Chapter Body` heading still works: everything outside a scaffold heading is treated as prose.

---

## The YAML subset

`bookshelf` uses PyYAML when it is installed. When it is not, it falls back to a small parser so `books validate` works in a bare checkout with no virtualenv. The fallback accepts:

- `key: value` — strings, integers, floats, `true`/`false`/`yes`/`no`, `null`/`~`/empty
- `key: [a, b, c]` — inline lists, with quoted items allowed to contain commas
- `key:` followed by indented `- item` lines — block lists
- `"double"` and `'single'` quoted strings
- `# comment` on its own line, or after a value when it sits outside quotes and brackets

It rejects anything deeper, including nested mappings, with the offending line number.

**Quote any value containing `: `** — `logline: "One sentence: who wants what."` PyYAML rejects the unquoted form, and the fallback rejects it too, on purpose: the fallback is kept a strict subset so a file cannot pass `books validate` in a bare checkout and then fail in CI where PyYAML is installed. A colon with no space after it, as in a URL, needs no quoting.

Both parsers are tested against the same fixture, so a file that parses one way parses the other way identically. Stay inside this subset and the library stays readable without dependencies.

---

## Validation codes

Errors fail `books validate`; warnings are reported and do not. `--strict` fails on both.

| Code | Level | Meaning |
| --- | --- | --- |
| `book-config` | error | `book.yml` is missing or unparseable. |
| `book-missing-key` | error | A required `book.yml` key is absent. |
| `book-status` | error | `status` is not a known value. |
| `book-slug` | error | `slug` disagrees with the directory name. |
| `book-logline` | warning | No logline. |
| `book-no-chapters` | warning | Past the `idea` stage with no chapters. |
| `outline-missing` | error / warning | No `outline.md`. Warning only while `status: idea`. |
| `front-matter` | error | Chapter front matter will not parse. |
| `chapter-missing-key` | error / warning | Required key absent (error) or recommended key absent (warning). |
| `chapter-number` | error | No usable chapter number. |
| `chapter-filename` | error | Filename is not the zero-padded form. |
| `chapter-number-mismatch` | error | Front matter `number` disagrees with the filename. |
| `chapter-duplicate` | error | Two chapters claim the same number. |
| `chapter-gap` | error | Chapter numbers are not contiguous. |
| `chapter-status` | error | `status` is not a known value. |
| `chapter-act` | error | `act` is outside the book's act count. |
| `placeholder` | error | An unresolved `[Something Name]` placeholder is still in the file. |
| `meta-reference` | warning | Outline bookkeeping such as `(Chapter 8)` appears in the narrative prose. |
| `unknown-character` | warning | A `characters` entry is not in the book's `cast`. |
| `nav-wrong` | error | A prev/next link points at the wrong chapter. |
| `nav-missing` | warning | A neighbouring chapter exists but is not linked. |
| `nav-dangling` | warning | A prev/next link exists where no such chapter does. |
| `broken-link` | error | A relative link does not resolve on disk. |
| `pov-drift` | warning | A chapter's `pov` differs from the majority. |
| `era-drift` | warning | A chapter's `era` differs from the majority. |
