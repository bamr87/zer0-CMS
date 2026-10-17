# The Impairment

A financial thriller about the wars fought on a balance sheet. A laid-off systems engineer discovers that the goodwill impairment that cost him his job was cover for a covert transfer of technology to a foreign military regime — one his own work helped arm.

Succession meets Syriana. Fourteen chapters across three acts, roughly 10,000 words drafted against a 90,000-word target.

## Where things are

| | |
| --- | --- |
| [`book.yml`](book.yml) | Manifest — status, themes, cast, targets. |
| [`outline.md`](outline.md) | Synopsis, three-act structure, character arc, chapter list. |
| [`chapters/`](chapters/) | `ch01.md` … `ch14.md`. |
| [`guides/`](guides/) | Per-act drafting guidance: beats, hooks and continuity rules for each chapter group. |
| [`notes/characters.md`](notes/characters.md) | Who everyone is. Add a row before using a name in prose. |
| [`notes/continuity.md`](notes/continuity.md) | Settled facts, and the eight open questions blocking a revision pass. |

## Before you write

1. Read [`outline.md`](outline.md), then the act guide covering your chapter, then the chapters either side of it.
2. Check [`notes/characters.md`](notes/characters.md) for any name you are about to use. If it is not there, decide it and add it.
3. Check [`notes/continuity.md`](notes/continuity.md) — several facts the draft appears to assert are still undecided.
4. Run `books validate impairment` when you are done.

## Current state

`books validate impairment` reports 3 errors and 120 warnings. These are known and catalogued in [`../../docs/reviews/impairment.md`](../../docs/reviews/impairment.md), which also gives a suggested order of work. The short version: the company and the CFO are never named (ch14 still carries literal `[Company Name]` placeholders), ch04 and ch05 stage the same layoff twice, chapter one is first person while the rest of the book is third, and 117 outline citations like `(Chapter 8)` are sitting in the narrative prose where a reader can see them.
