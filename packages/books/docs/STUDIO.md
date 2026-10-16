# Studio

`books studio` is the writing surface: a local web app that edits the markdown in `library/` directly, shows validation findings beside the text, and can hand a chapter to Claude with the rest of the book as context.

```bash
pip install -e ".[ai]"        # the assistant needs the Anthropic SDK
export ANTHROPIC_API_KEY=...  # or run `ant auth login`
books studio --open
```

It binds to `127.0.0.1` and serves on port 4321. Without the SDK or a key the editor still runs in full — only the Assist panel is unavailable, and it says so on startup.

---

## The three panes

**Left — the shelf.** Every book, expandable to its chapters. `+ Book` starts a new one from `library/_template/`; `New chapter` at the end of a book's list adds the next one.

**Middle — the chapter.** Front matter as editable fields along the top, then the raw markdown. The word count in the footer counts narrative prose only, ignoring the outline and reference sections, so it agrees with `books stats`. Changes autosave two seconds after you stop typing; `⌘S` / `Ctrl-S` saves immediately.

**Right — Assist and Checks.**

- **Assist** runs a task and streams the result. `Insert at cursor` and `Replace selection` put it into the chapter; nothing is written until you do.
- **Checks** lists `books validate` findings for the open chapter, and runs the AI continuity check on demand.

---

## Tasks

| Task | What it does |
| --- | --- |
| **Draft** | Writes the chapter body from its outline section, the act guide and the neighbouring chapters. |
| **Continue** | Carries on from exactly where the chapter stops, matching voice and pacing. |
| **Revise** | Rewrites the selected passage against an instruction you type. Needs a selection. |
| **Continuity check** | Reads the chapter against the brief and returns structured findings: severity, kind, the exact quote at fault, and a suggested fix. |
| **Outline** | Expands a premise into a three-act outline. Works on a book with no chapters yet. |
| **Critique** | An editor's read: what works, and the two or three changes that would most improve it. |

The same tasks are available from the terminal:

```bash
books ask impairment critique --chapter 7
books ask impairment check --chapter 12 | jq '.findings[] | {severity, problem}'
books ask impairment revise --chapter 4 --instruction "cut the layoff scene; it belongs in ch05"
```

---

## What the assistant is given

Prompt quality is mostly context quality. Every request is built from the book's own material, never from generic craft advice:

| | |
| --- | --- |
| **Brief** (cached) | `book.yml` facts, the full `outline.md`, `notes/characters.md`, `notes/continuity.md`, and a one-line index of every chapter with its status and length. |
| **Nearby** (cached) | The act guide in `guides/` whose filename covers this chapter, plus the full prose of the previous and next chapters. |
| **Task** | The chapter you are working on, the task instruction, and anything you typed in the instruction box. |

See exactly what would be sent, without spending a token:

```bash
books context impairment --chapter 7
```

The brief and the nearby material are marked as cache breakpoints, so a run of tasks against one chapter re-reads them at cache rates rather than paying for the whole book each time. Anything that changes per request sits after the last breakpoint.

## House rules the assistant is held to

These are in the system prompt on every request, and they encode the defects the [`impairment` review](reviews/impairment.md) found:

- Never write `(Chapter 8)` or quote another chapter's title inside narrative prose.
- Never invent a name for something the book left unnamed — say which fact is missing and stop, rather than emitting `[Company Name]`.
- Only use names from the book's `cast`.
- Write in the book's established point of view and tense; if the chapter's front matter disagrees with the book's, follow the chapter and say so.

---

## Model and cost

Defaults to `claude-opus-5` with adaptive thinking at `high` effort. Override per run:

```bash
books studio --model claude-sonnet-5
BOOKSHELF_MODEL=claude-sonnet-5 books ask impairment critique --chapter 3
```

Requests opt into server-side fallbacks, so a request the model's safety classifiers decline is retried on Anthropic's recommended fallback inside the same call instead of coming back empty. If your account does not have that beta — or your installed SDK predates the parameter — the request is transparently retried without it. `--no-fallbacks` turns the opt-in off.

---

## Notes

- **The files are the source of truth.** The editor reads and writes `library/**/*.md` in place. Editing in your usual editor at the same time is fine; reload the browser to pick up outside changes.
- **Localhost only.** The server binds the loopback interface and refuses cross-origin writes. It is a single-user tool, not something to put on a network.
- **Nothing is written by the assistant.** Generated text lands in the Assist panel; it reaches the chapter only when you insert it.
