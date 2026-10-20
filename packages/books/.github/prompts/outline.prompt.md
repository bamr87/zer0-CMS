---
mode: agent
---

Draft the outline for a new book from the idea below, and scaffold it into the library.

**Idea:** <one or two sentences — premise, protagonist, or just a theme>

Steps:

1. Run `books new <slug> --title "<title>" --logline "<one sentence>"` to scaffold `library/<slug>/`.
2. Fill in `library/<slug>/outline.md` following [`../instructions/book-outline.instructions.md`](../instructions/book-outline.instructions.md): synopsis, key themes, a three-act structure, the protagonist's arc as a phase table, and a chapter plan.
3. Fill in `library/<slug>/book.yml`: `genre`, `pov`, `tense`, `era`, `protagonist`, `acts`, `planned_chapters`, `target_word_count`, `tags`, `themes`, and `cast` for every character the outline names.
4. Set `status: outlining`.
5. Run `books validate <slug>` and fix anything it reports.

Do not draft any chapter prose in this task — the outline and the manifest only.
