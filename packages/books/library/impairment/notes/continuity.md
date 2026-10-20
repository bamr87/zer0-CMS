# Continuity ledger — The Impairment

Open questions and settled facts. A fact only counts as settled once it is written here; until then, treat it as up for grabs and do not build a scene on it.

## Settled

| Fact | Value | Source |
| --- | --- | --- |
| Acts | 3 — chapters 1–5, 6–9, 10–14 | `guides/` |
| Era | Early 2020s | `book.yml` |
| Narrative POV | Third person limited, past tense | 13 of 14 chapters |
| Kareem's surname | Hassan | ch11 |
| Contaminated region | Tarna Valley | ch11, ch12, ch14 |
| Foreign customer | Al-Madina Holdings | ch01, ch02 |
| Kareem's award plaque | "Outstanding Systems Integration" | ch04, ch05 |

## Open questions

Each of these has to be answered before the draft can be revised past a first pass. They are ordered by how much rewriting the answer forces.

1. **What is the company called?** ch14 ships the literal string `[Company Name]` in the exposé Kareem sends to Elena — the emotional climax of the book turns on a document that names nobody. Naming it also decides what the plant's signage, the stock ticker and the press release in ch13 say.
2. **What is the CFO called?** Same problem, same chapter (`[CFO's Name]`). The antagonist is referred to only by job title across all fourteen chapters.
3. **Is the homeland contact one person or two?** ch02 has Kareem phoning a *cousin*; ch06, ch08 and ch09 use an unnamed *old colleague*; ch12 has letters signed *Omar*, described as an old friend. If they are one person, ch02's cousin and ch06's colleague both need renaming to Omar. If they are two, ch06 and ch09 need to say which.
4. **Which chapter contains the layoff?** ch04 and ch05 both stage it, and both send Kareem home with the same box: "a photo of his children / family, a mug from his first day, a plaque for 'Outstanding Systems Integration.'" The act-1 guide assigns the layoff to ch05 and gives ch04 the KPI memos and the fruit basket. Cutting the duplicate from ch04 is the smaller edit.
5. **Is ch01 first person or third?** ch01 is written in first person; every other chapter is third person limited. The copilot guidance in the repository asked for first person throughout, so the draft drifted away from its own brief rather than the other way round. Pick one and convert.
6. **When does ch02 happen?** Its front matter says "Early 2000s" while the rest of the book says early 2020s. If the intent was a flashback, the chapter needs to say so; if not, it is a typo for 2020s.
7. **Where does Al-Madina Holdings go?** The buyer is named in the first two chapters and never again, even though the export thread is what ties the acquisition to the Tarna Valley. Act II and III should name it at least once each.
8. **Where is ch12 in the sequence?** ch11's outline says it draws on "the emotional weight of 'Letters from Home' (Ch. 12)" — a chapter that has not happened yet. Either swap ch11 and ch12, or cut the dependency from ch11.

## Housekeeping

- Several chapters carry outline bookkeeping inside the narrative — ch04 and ch05 have "(Chapter 8)" and "(Chapter 14)" in the prose, and ch12 puts "(Ch. 2)" and "(Ch. 9)" inside a letter written by a character. `books validate` lists every occurrence under the `meta-reference` code. They are notes to self, not text a reader should see.
- Several chapters end with a "Suggested Minor Updates to Other Chapters" section left over from drafting. These are worklists, not content; act on them and delete them, or move them here.
