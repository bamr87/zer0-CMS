# Campaign — Badwill Impairment

One story told across a book, two sites, X and LinkedIn, and the tools that publish them, and kept growing from the work itself. This is the charter: what each place carries, the rules every piece follows, and the beats so far.

## Two strands

| Strand | What it is | Truth rule |
| --- | --- | --- |
| The book | *Badwill Impairment: Corporate Cache Compromised*, a financial thriller | Fiction stays fiction: invented people and companies, never a real one. |
| The journey | The true account of writing it, and of building the tools that write and publish it | Only what the record shows: commits, drafts, sessions, decisions the author made. Nothing about the author's life that the author has not written. |

## Where it lives

| Place | Carries | How it gets there | Approval |
| --- | --- | --- | --- |
| zer0-CMS book library, `packages/books/library/badwill-impairment/` | The book: outline, notes, chapters | The studio's Books area. Every AI draft, continuation or revision arrives as a suggestion | The author accepts each suggestion |
| bamr87.github.io, `pages/_posts/badwill-impairment/` and `pages/_posts/quest-log/` | The journey's home: one post per beat, and one Quest Log article per repository | A pull request per post | Merging the pull request |
| bash-365.com, `pages/_posts/muses/` | Only a piece that carries a finance-and-IT lesson a business owner can use | bash-365's content process and gates | Merging the pull request |
| X, @bamr87 | A short post per journey post, linking to it | zer0-CMS, an X channel for bamr87.github.io | Approving it in the studio's queue |
| LinkedIn, Amr's profile | The journey for a professional audience, linking to the post; each Quest Log article, pasted into LinkedIn's article editor by hand (LinkedIn has no API for articles) | zer0-CMS, a LinkedIn channel for bamr87.github.io | Approving it in the studio's queue |
| LinkedIn, the BASH company page | The bash-365.com cross-posts, and one link card per Quest Log article | bash-365's LinkedIn lane, `drafts/linkedin/` | Merging the draft |

Every piece carries the tag `badwill-impairment`; posts on X and LinkedIn carry #BadwillImpairment. Each channel's ledger keeps a page from going to it twice.

## How it keeps building

1. A beat starts from a real event in the work: an open question answered in `notes/continuity.md`, a chapter moving from stub to draft to revised, a tool built or fixed for the book.
2. The journey post says what happened and why, from the record.
3. X and LinkedIn carry it out, each in its own form, after approval.
4. Once a month, the channels' statistics (zer0-CMS → Distribution → Statistics) and the replies feed the next beat. A change they cause is itself a beat.

## Beats

| # | Date | Event | Journey post | X | LinkedIn | Cross-post |
| --- | --- | --- | --- | --- | --- | --- |
| 01 | 2026-11-01 | A fresh draft from The Impairment's premise, under the new title | bamr87.github.io#51, merged | Drafted below | Drafted below | None: no business lesson yet |
| 02 | 2026-11-01 | Three years since the noise stopped: Amr's own post, and its long version | bamr87.github.io#52 | Drafted below | Drafted below | bash-365.com#63, the muses essay "Badwill impairment: three years of building without the meeting" |

### Beat 01 — drafts for approval

X, as @bamr87, with the journey post's link after it:

> Starting my thriller over: same premise, new title. Badwill Impairment: Corporate Cache Compromised. One deal, a write-down on one ledger and a bargain on another. Written in the open from here. #BadwillImpairment

LinkedIn, Amr's profile, with the journey post's link:

> My thriller is starting over, under a new title: Badwill Impairment: Corporate Cache Compromised.
>
> The first draft, The Impairment, reached fourteen chapters before a review showed it had been written ahead of its own decisions: the company and its chief financial officer were never named, the layoff was written into two chapters, and the point of view changed after chapter one. The premise survives. A systems engineer loses his job in his company's first layoff and finds that the goodwill impairment behind it covered a transfer of technology to a foreign military regime, through systems he built.
>
> The title is where finance and information systems meet. A goodwill impairment is the write-down when an acquisition is worth less than was paid; badwill is the gain a buyer books on a bargain. A cache is what a company keeps in its systems, and it sounds like cash.
>
> The book is fiction. The making of it is not: I am writing it in the open, with the decisions, drafts and tools posted as they happen. First up: naming the company and the CFO.
>
> #BadwillImpairment #Writing #Finance

### Beat 02 — three versions, one story

Amr's post is the short version (bamr87.github.io#52). The long version is a bash-365.com muses essay (bash-365.com#63): the meeting, goodwill and badwill, and a ledger of six projects (fredgar-ai, law-ai, zer0-CMS, lifehacker.dev, CSV Grid Editor and the bamr87/bamr87 control plane), each with a screenshot and an auditor's note on what is still a plan. Both posts link to the essay. Facts were checked against each project on 2026-11-01; the unbuilt parts are named as plans in all three versions.

X, as @bamr87, with the essay's link after it (274 of 280 characters):

> Three years ago I wasn't invited to the cash flow imperative meeting. Since then: an SEC filings analyst, a lawyer that keeps prompts local, a CMS that never skips approval, a control plane over 44 repos. No stand-ups were harmed. #BadwillImpairment

LinkedIn, Amr's profile, with the essay's link: the text is in bash-365.com#63's description, from "Three years ago, I missed a meeting about the cash flow imperative" to "#BadwillImpairment #GovernedAI #EnterpriseSoftware".

## The Quest Log series

Beat 02's post ends on the Quest Log: eight levels and more than thirty side quests, one per repository. The series walks it one repository at a time, riding the hub's daily deep dive (bamr87/bamr87 `docs/DEEP-DIVE.md`; cycle 1 runs from 2026-10-30 to 2026-12-10). Every repository the deep dive reviews gets five pieces, each a pull request a person merges:

| Piece | Where | How it reaches LinkedIn |
| --- | --- | --- |
| Article with screenshots | bamr87.github.io, `pages/_posts/quest-log/`, listed at `/quest-log/` | Pasted into LinkedIn's article editor on Amr's profile |
| Personal post | bamr87.github.io, `.zer0/drafts/linkedin/` | Amr's profile, through the studio once LinkedIn is connected |
| Company post | bash-365.com, `drafts/linkedin/`, carded with the article's own screenshot (`image:`) | Merging the draft, after the article is live and at most one company post a day |
| Presentation | The repository itself: README first screen, link card, a proposal for its GitHub About box | Not a post |
| Record | The hub ledger, `_data/deep-dive.yml` | Not a post |

The procedure is the hub's `deep-dive-showcase` skill and `docs/SHOWCASE.md`. Days 1–3 (it-journey, bamr87, bamr87.github.io) were caught up on 2026-11-02: the series page bamr87.github.io#54; articles bamr87.github.io#55, #56 and #57; presentations it-journey#901 and bamr87#579; company posts bash-365.com#64, #65 and #66; the procedure bamr87#580. The truth rule holds here too: every figure is dated and sourced, built things are called built and plans are called plans, and a score appears only once the deep dive records one.

## Next

- Connect: register bamr87.github.io in zer0-CMS, give it an X channel for @bamr87, and connect LinkedIn for Amr's profile. Each needs the account's owner to sign in once.
- Beat 02: the first open questions answered, the company and the CFO named, written up from the author's own decisions.
- First cross-post: beat 02's essay (bash-365.com#63); once it is live, share it on the BASH company page through bash-365's LinkedIn lane.
- Quest Log: point the routine that runs the daily deep dive at the `deep-dive-showcase` skill, so days 4–42 ship their five pieces the day each repository is reviewed.
