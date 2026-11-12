# Continuing the series with the book assistant

How this book is wired to zer0-CMS's AI layer, and the instructions to give each task. Every task is a run of the `books` agent (`content/agents/definitions/books.yaml`, policy `suggest`): it reads this book's own files and proposes its writing as suggestions on the chapter, which a person accepts or rejects. Nothing is published by the agent.

## What every run is given

The platform assembles it from this directory (`content/books/context.py`):

- the brief — `book.yml`'s facts, `cast` as the only names to use, `outline.md`, `notes/characters.md`, `notes/continuity.md` (including the content rules and timeline), `notes/style-guide.md`, and the chapters so far;
- the act guide whose file name covers the chapter (`act-1-chapters-01-03.md` for chapters 1–3, and so on);
- the prose of the chapters either side, the chapter's whole file, and your instruction.

To change what the model knows, change these files; to see what it will be given, run `python manage.py books context cost-line --chapter <n> --task draft` or open the chapter's context in the studio's Books area.

## Tasks and instructions

Run them from the studio's Books area (or `POST /api/v2/books/<id>/assist/`). Paste the instruction into the task's instruction field.

| Task | When | Instruction to give |
| --- | --- | --- |
| Outline | Book | "Keep the eight-chapter frame: crash open, four flashbacks in order, two present chapters, a near-future close. Do not rename characters." |
| Draft | A chapter with an outline | "Draft the chapter from its outline and the act guide. Plain, direct voice; dark comedy from precision; no corporate language in the narration. Keep June specific. Obey the content rules in the continuity ledger." |
| Continue | A chapter mid-scene | "Continue the scene where it stops. Keep the euphemisms in characters' mouths and let the narration state what they mean." |
| Revise | A selected passage | "Cut any sentence that explains the joke. Replace any abstract noun with the concrete thing." |
| Continuity check | Any chapter | "Check names against the cast, times against the timeline, and every line against the content rules." |
| Critique | Any chapter | "Read as an editor: where does the narration slip into the voice it is satirising, and where does June become a device?" |

## The brand guard

The platform's built-in banned phrases were written for marketing copy. A satire of corporate language needs some of them in characters' mouths. If a suggestion is blocked for a phrase a character says on purpose, switch the book's **Built-in bans** off in the Books overview; the markup check and the site's own bans still apply.

## A new book in the series

Each book of **Business as Usual** is its own directory in this library. Start the next from the template (`python manage.py books new <slug>`), copy this book's `notes/` and `guides/ai-prompts.md` across, and update the timeline.
