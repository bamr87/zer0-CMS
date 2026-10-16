# Review — The Impairment

An audit of the outline and the fourteen drafted chapters as they stood before the restructure, plus what the restructure changed and what it deliberately left alone.

**Summary.** The outline is strong and the prose is competent, but the draft is carrying a lot of its own scaffolding. Three defects would be visible to a reader; the rest are consistency problems that get more expensive the longer they sit. Nothing here requires rethinking the book.

Every finding below is reproducible: run `books validate impairment`.

---

## What was there

| | |
| --- | --- |
| Outline | `impairment/README.md` — synopsis, 8 key themes, a three-act structure in 11 numbered sections, a 5-phase protagonist arc, 14 suggested chapter titles |
| Chapters | `impairment/book/chapters/ch1.md` … `ch14.md`, ~10,100 words of narrative prose |
| Guidance | `impairment/.github/copilot-instructions.md` plus five `*.instructions.md` files |

---

## Findings

### 1. The climax names nobody — `error`

`ch14.md` ships two unresolved placeholders inside the exposé Kareem sends to the journalist:

> …a systematic scheme of asset stripping, financial manipulation, and deliberate environmental negligence by **[Company Name]** and its executive leadership, particularly CFO **[CFO's Name]**.

This is the emotional payload of the whole book, and it accuses a blank. The cause is upstream: neither the employer nor the antagonist is ever named in any of the fourteen chapters. The CFO is "the CFO" throughout; the century-old manufacturer is "the company". Naming both is the single highest-value edit available, and it unblocks the ch13 press release, the plant signage and the ticker symbol at the same time.

Tracked in `library/impairment/notes/continuity.md`, questions 1 and 2.

### 2. Outline bookkeeping is inside the prose — `warning` ×117, in 13 of 14 chapters

The narrative repeatedly cites its own chapter numbers, mid-scene, in the reader's line of sight. From `ch03.md`:

> …where the real "deal no one understood" (Chapter 2) had been orchestrated. This was the inner sanctum, far removed from "the last day in the plant" (Chapter 1) and its raw emotions.

And from `ch12.md`, inside a letter written by a character:

> The one with the vague specs you once asked me about, remember? (Ch. 2) … We are a "country on fire" (Ch. 9) and no one outside seems to care.

These read as an author's continuity notes that were never taken back out — Omar has no way to cite chapter nine. The pattern is not incidental: it appears 117 times across every chapter but ch01, usually alongside a chapter title quoted verbatim, so removing the citation often means rewriting the sentence that hosted it rather than just deleting a parenthesis. This is the largest single body of revision work in the draft.

`books validate` lists every occurrence under `meta-reference`.

### 3. ch04 and ch05 stage the same layoff — `manual`

Both chapters lay Kareem off, and both walk him out with the same props:

- `ch04.md` — "He was handed a cardboard box … a photo of his children, a mug from his first day, a plaque for 'Outstanding Systems Integration.'"
- `ch05.md` — "Packing his things, he paused at his desk — a photo of his family, a mug from his first day, a plaque for 'Outstanding Systems Integration.'"

The act-1 guide is unambiguous about the intent: ch04 is KPI memos, reorganisation and the performative fruit basket; ch05 is the layoff. ch04 has absorbed ch05's climax. Cutting the layoff from ch04 is the smaller of the two possible edits and restores the guide's pacing.

### 4. The point of view flips after chapter one — `warning`

ch01 is first person. ch02 through ch14 are third person limited. The repository's own Copilot instructions asked for first person observational throughout, so the draft drifted away from its brief rather than the brief being wrong. Thirteen chapters against one makes third person the cheaper convergence, but that means rewriting the book's strongest chapter — worth a deliberate decision rather than a default.

Surfaced automatically as `pov-drift`, because `pov` is now a first-class front matter field.

### 5. ch02 is set two decades early — `warning`

Its front matter said `era: Early 2000s` while every other chapter said early 2020s, in one of four different spellings (`Present Day`, `Contemporary`, `2020s, Post-Acquisition`, `Early 2020s`). The restructure normalised the four spellings to `Early 2020s` and **left ch02 alone**, because "Early 2000s" is either a deliberate flashback the chapter never signals or a typo — and that is the author's call. It now shows up as `era-drift`.

### 6. Named entities are introduced and then abandoned

- **Al-Madina Holdings**, the government-linked buyer, is named in ch01 and ch02 and never again. Acts II and III discuss "the export" without naming who bought it, which weakens the link between the acquisition and the disaster.
- **Tarna Valley**, the contaminated region, is named in ch11, ch12 and ch14 — but not in ch06 or ch09, the two chapters actually set there.
- **Kareem's surname, Hassan**, appears exactly once, in ch11.
- The **homeland contact** is a cousin in ch02, an unnamed "old colleague" in ch06/ch08/ch09, and Omar in ch12. One person or two is undecided.

There was nowhere to record any of this, which is why it drifted: the act guides demanded name consistency but no file held the names. There is now a character bible and a continuity ledger.

### 7. ch11 depends on a chapter that has not happened

ch11's own outline says it draws on "the emotional weight of 'Letters from Home' (Ch. 12)". Its navigation footer also skipped ch12 entirely, linking straight to ch13 — the footer is fixed; the ordering question is not, and is logged as continuity question 8.

### 8. The outline duplicates itself

`README.md` carried both a "Key Themes" list of 8 and a "Themes to Build On" list of 5, overlapping on all 5. Its 11 numbered act-sections also do not map cleanly onto the 14 chapters, so there was no single answer to "which chapter covers outline section 6". The themes are now recorded once, in `book.yml`.

### 9. Drafting exhaust was committed as content

Nine chapters end with a "Suggested Minor Updates to Other Chapters" section — worklists addressed to whoever writes the next chapter. They are not part of the book. They are now excluded from word counts and stripped from the compiled manuscript, but they should be actioned and deleted.

### 10. Structural problems that the restructure fixed outright

- **Chapter files sorted wrongly.** `ch1.md` … `ch14.md` sorts as ch1, ch10, ch11, ch12, ch13, ch14, ch2 … Any tool listing the book got the wrong order. Now zero-padded.
- **The guidance was inert.** `impairment/.github/` did nothing — GitHub only reads the repository-root `.github/`. The instructions that were supposed to govern the draft were never loaded by anything.
- **Front matter had no stable shape.** `character:` was a bare string in five chapters and a list in nine; `tone` was a comma-joined string everywhere; `setting` mixed both. Nothing could read it reliably.
- **No chapter knew its own number or act.** Both were implicit in the filename and the guide filenames.

---

## What the restructure changed

Metadata and structure only. **No narrative prose was edited** — the sentences in every chapter body are byte-for-byte what they were.

| Before | After |
| --- | --- |
| `impairment/README.md` | `library/impairment/outline.md` |
| `impairment/book/chapters/chN.md` | `library/impairment/chapters/chNN.md` |
| `impairment/.github/instructions/book-chapters-*.md` | `library/impairment/guides/act-*.md` |
| `impairment/.github/instructions/{README,book-chapter-*}.instructions.md` | `.github/instructions/` (repository root, where GitHub reads them) |
| `impairment/.github/copilot-instructions.md` | `.github/copilot-instructions.md`, rewritten for the new layout |
| — | `library/impairment/book.yml` |
| — | `library/impairment/notes/characters.md`, `notes/continuity.md` |

Front matter was normalised to the schema in [`../SCHEMA.md`](../SCHEMA.md): `character` → `characters`, scalars → lists for `setting` and `tone`, and new `number`, `act`, `status` and `pov` fields. Era vocabulary was unified except for ch02 (finding 5). Prev/next links were repointed at the correct neighbours with their real titles — ch04's "Next Chapter: The Impairment" pointed at ch05, which is "The Layoff Letter", and ch11 skipped ch12.

## What was deliberately left alone

Everything in findings 1 through 7 is an authorial decision, not a mechanical fix, so the tooling reports it rather than guessing:

- Names for the company and the CFO — inventing them would silently commit the book to them.
- Whether ch02's "Early 2000s" is a flashback or a typo.
- Which of ch04 or ch05 keeps the layoff.
- Whether the book is first person or third.
- Whether the homeland contact is one person or two.
- The ch11 / ch12 ordering.

## Suggested order of work

1. Name the company and the CFO (finding 1) — unblocks the most other edits.
2. Cut the duplicate layoff from ch04 (finding 3).
3. Settle POV and convert ch01 or the other thirteen (finding 4).
4. Strip the inline chapter citations (finding 2) — the largest job, best done once the sentences above have settled.
5. Work through `notes/continuity.md` and delete each question as it is answered.
