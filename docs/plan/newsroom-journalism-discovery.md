# Newsroom and journalism platform — discovery

> Discovery for epic [#92](https://github.com/bamr87/zer0-CMS/issues/92) (a full journalism and media-agency platform, centred on journalist workflow UX): the gap against today's studio, user stories and one journey, low-fidelity UX, the format model, the confidentiality model, Design for Failure and a phase plan. It is a plan, not a spec: nothing here is built, and it mints no FEAT ids or PRD requirements.

Governed by: [constitution](../constitution.md) § 3 (precedence), § 4 (an agent invents no features or requirements; unknown means TBD) and § 6 (FEAT ids and `FRn` rows come with the change that builds a feature); [AGENTS.md](../../AGENTS.md); [`PRD.md`](../../PRD.md); [`features/features.yml`](../../features/features.yml); [`TARGET.md`](TARGET.md); [`capabilities.yml`](capabilities.yml); [`PLAN.md`](PLAN.md) G15 and G14.

**Status:** discovery, 2026-11-15, written against `origin/main` at `3abeb8c`. Sources: the issue body of #92, the [discovery comment](https://github.com/bamr87/zer0-CMS/issues/92#issuecomment-6731816074) (2026-11-08) and [Amr's decisions](https://github.com/bamr87/zer0-CMS/issues/92#issuecomment-6732088739). This PR does not close #92 and does not amend `TARGET.md`, `PRD.md`, the feature catalog or the ledger.

## 0. Decisions this document rests on

**Decided by Amr (2026-11-08):**

| Q | Decision |
| --- | --- |
| Q2 | Budget lines are money budgets as well as the existing slot board. |
| Q4 | A confidential source's identity is visible only to the reporter and one named standards or managing editor, and never to AI, MCP or logs. A legal hold blocks all publishing and distribution. |
| Q6 | Fact-checkers propose edits. `TARGET.md` needs a later amendment to allow fact-check proposals. |
| Q8 | A `taken_down` state serves a 410 or a redirect. A retraction is a kind of correction on a live page. |
| Q11 | Print/PDF is in the MVP for magazines and journals. |

**Provisional defaults, not overridden by Amr and open to change:**

| Q | Default |
| --- | --- |
| Q1 | Formats are overlays on `Story`/ArticlePage plus desks. The only new types are Edition and a classified listing. |
| Q3 | Journals are separate from Books: a journal desk, a paper format, the shared Edition type and peer-review stage tasks. |
| Q5 | Fact-check and standards/legal become official workflow stages that each desk opts into. |
| Q7 | A `ready` state sits before schedule/publish. |
| Q9 | One "what needs me" home. Roles are desk memberships and permissions; a freelancer is a restricted reporter. |
| Q10 | Accessibility and RTL are owned by a separate frontend-platform issue that #92 depends on. |
| Q12 | FEAT ids and new PRD requirements wait for the phase plan's numbering step (§ 10). |
| Q13 | This file is the in-repo copy of the discovery. |

**Out of scope:** payments (classifieds, subscriptions) stay a later, separately approved scope; no implementation, new service, publishing automation or child issue is authorised here. Related but separate, mentioned and not touched: [#58](https://github.com/bamr87/zer0-CMS/issues/58) (project site and Newsroom screenshots), [#86](https://github.com/bamr87/zer0-CMS/issues/86) (directives become briefs) and [#88](https://github.com/bamr87/zer0-CMS/issues/88) (shared voices).

## 1. What exists (extend, do not replace)

PLAN G15 landed the newsroom in `content/newsroom/` and `/studio/newsroom/`: desks (site, section, editors, copy editors, a writer), `Story` as the planning record behind a page (status, priority, assignee, deadline, slot date, embargo, brief, wire item, bylines) with `StoryEvent` history, a budget board by status, calendar filters, assignments, editing and copy as Wagtail `StageTask`s, embargoes enforced on every publish path, a breaking-news fast path that skips copy and keeps its reason, fronts, bylines and author pages, a corrections log that publishes nothing else, and newsletters. Around it: Write (ZER0-040), the review inbox and revisions (ZER0-041), briefs and the AI panel (ZER0-042 to 044), Research with sources, quotes, citations and fact-check suggestions (G14), the claim desk (ZER0-045), voice (ZER0-046) and distribution with web, newsletter, LinkedIn, X, WordPress, GitHub PR and, since #90, a cadence queue. AI is propose-only; a person accepts; AI is never the last reviewer and cannot publish a story still being made.

Today's `Story.Status` values: pitch, assigned, drafting, editing, copy, scheduled, published, updated, corrected.

**Drift since the discovery comment (2026-11-08) — checked on a fresh clone:**

- Distribution scheduling is richer than the comment said: #90 added a cadence queue (weekly slots, gaps, blackout dates, phased shares, revisions). The distribution row below is updated.
- #82 keeps unsaved page edits across newer revisions and navigation, which narrows (does not close) the lost-edit gap in § 9.
- PLAN G14 still lists the propose-versus-read-only fact-check question as an open owner decision, and PLAN G15 still lists the taken-down status as an open owner decision. Q6 and Q8 now decide both; PLAN is not edited here, and the follow-up in § 11 covers it.
- No newsroom FEAT ids or `FRn` rows exist: the catalog stops at ZER0-046 (plus ZER0-030 to 033) and `PRD.md` holds FR1, FR2, NFR1, NFR2.
- Everything else in the comment's table still matches `capabilities.yml`.

## 2. Gap analysis

"Partial" means a real foundation exists; the phases extend it.

| Area | Gap | What exists, and what does not |
| --- | --- | --- |
| Assignment desk | partial | `news.desk`: board, calendar filters, assignments, pitch from a wire item. No desk-create UI (waits on G3), **no money budget lines (Q2)**, no desk home. |
| Story workspace | partial | Write, the Research tab, the story panel and revisions are separate surfaces. No interview notes or attachments as story objects. |
| Editorial pipeline | partial | G15 stages, embargoes, fast path. No fact-check stage, no standards/legal stage, no `ready`, no `taken_down`. `content.workflow` has no studio screen. |
| Collaboration | partial | Suggestions and revision compare. Locks are held but have no UI; human comments, mentions and presence are "to come" (`content.collaboration`). |
| Sources and citations | partial | G14 sources, quotes, citations, fact-check suggestions; the claim desk. Sharing is coarse: no confidential sources. No citation styles. Wire formats (NewsML-G2, ninjs) unread. |
| Planning | partial | Story calendar, `news.fronts`, `distribution.schedule`. No Edition object, no section story-count or money budgets. |
| Review queues | partial | Suggestion inbox and board columns, not role queues with visible blockers. |
| Media | partial | Wagtail admin only; `media.library` has no studio surface. No rights, credits or photo desk. |
| Corrections | partial | `news.corrections` log publishes nothing else. Public display waits on P6/P2. **No retraction, no takedown (Q8).** |
| Search | partial | `content.search` has no studio surface across stories, sources and assets. |
| A11y and RTL | missing | `content.localization` missing; no ledger row for keyboard-first, screen-reader or RTL studio UX. Owned elsewhere (Q10). |
| AI assistance | have | Propose-only, person accepts. Keep as stages are added; see § 8 for sources. |
| News, features | partial | Pages, `Story`, a news-article schema; not per-format fields and rules. |
| Magazines, issues | missing | No Edition. |
| Opinion, editorials | missing | |
| Blogs, columns | partial | Posts work; no column franchise. |
| Classifieds | missing | No listing type or workflow. Payments out of scope. |
| Journals, peer review | missing | Not part of Books (Q3). |
| Briefs, newsletters | have | ZER0-044, `news.newsletters`. "Brief" in the studio means an AI request, not a news brief. |
| Multimedia, live updates | missing | The fast path is not a live blog. |
| Distribution | partial | Web, newsletter, LinkedIn, X, WordPress, GitHub PR, cadence queue. **No print/PDF channel (Q11)** and no classified channel. |
| Role homes, permissions | partial | TARGET's Home is one attention list. `platform.permissions` has no studio screen (G3 Admin). |
| Embargoes | have | Enforced on every publish path. |
| Legal holds | missing | Distinct from embargoes (Q4). |
| Standards policies | partial | Voice and brand (ZER0-046) and agent brand review; no legal desk. |
| Audit log | partial | Wagtail's log exists; no studio or `platform.audit` API. |
| Editor analytics | missing | No time-to-publish or queue age; `sites.analytics` missing. |
| Contributors | partial | `news.bylines` only. |

## 3. Roles

A role is a set of desk memberships plus permissions, not a separate account type (Q9, provisional). One "what needs me" home lists, for the signed-in person, every story, task, review, correction, hold and deadline that is theirs, filtered by what their memberships allow. Roles from the epic: reporter, staff writer, contributor/freelancer, editor, section editor, managing editor/editor-in-chief, copy editor, fact-checker, photo/media editor, opinion editor, classifieds/ads desk, journal/peer-review editor, standards/legal reviewer, publisher/distribution manager. A freelancer is a reporter whose permissions are narrowed: their own assignments only, no desk-wide board, no other people's sources, no distribution.

## 4. User stories

Format: As a *role*, I want … so that …. Acceptance hints are provisional; real acceptance criteria come with the requirements in § 10.

**Reporter / staff writer**
- I want my home to show my assignments, due dates and what editors have sent back, so that I start from what needs me.
- I want one workspace with draft, notes, sources, interviews and attachments, so that I do not hunt across tools.
- I want to link a claim to a source and mark a source confidential, so that the fact-check and the standards editor see support without exposing the person.
- I want to see that my edit conflicts with someone else's before I overwrite it, so that no work is lost.

**Contributor / freelancer**
- I want to pitch and be assigned, and see only my own stories, so that my access matches my engagement.

**Assigning / section editor**
- I want a desk board with deadlines, owners, slots and budget (slots and money), so that I see load and overspend at a glance.
- I want a review queue with each story's blocking reason, so that I clear what is actually blocked.

**Copy editor**
- I want a copy-only queue with the edit history and suggestions, so that I do not review twice.

**Fact-checker**
- I want a checklist of claims with linked sources and a way to propose an edit that the writer accepts or rejects (Q6), so that corrections are traceable and the writer keeps the byline's voice.

**Standards / legal reviewer; managing editor**
- I want a stage that can hold a story and a legal hold that blocks all publishing and distribution (Q4), so that nothing goes out under review.
- As the one named standards or managing editor on a confidential source, I want to see the source's identity, so that I can verify it without widening the circle.

**Photo / media editor**
- I want rights, credit, caption and alt text on every asset, so that nothing publishes without them.

**Opinion editor**
- I want opinion kept visibly apart from news, with its own byline and label, so that readers are not misled.

**Publisher / distribution manager; edition planner**
- I want an Edition with its sections, story counts, money budget and print/PDF output (Q11), so that a magazine or journal issue ships as a unit.
- I want each channel's schedule, status and published link on the story, so that I see what went where.

**Classifieds manager**
- I want to review and publish classified listings without payments in the product, so that the desk works before any billing exists.

**Journal / peer-review editor**
- I want a paper to move through reviewer tasks into an Edition, so that peer review is a stage of the same pipeline (Q3).

**Everyone**
- I want AI help to arrive as suggestions I accept, so that no AI result is ever published unreviewed.

## 5. Journey map: one story, pitch to correction

A reporter pitches an investigation that relies on one confidential source, runs it in a magazine issue and is later corrected and partly retracted.

| Step | Who | Surface | Existing foundation | New |
| --- | --- | --- | --- | --- |
| Pitch | Reporter | Home, Pitch | Ideas, Research, wire pitch, `news.desk` | Desk home entry |
| Assign | Section editor | Desk board | Assignments, calendar | Money budget line (Q2) |
| Draft | Reporter | Story workspace | Write, Research tab, AI suggestions | Source directory, confidential flag (Q4), notes, attachments |
| Edit | Editor | Review queue | Editing stage | Human comments, conflict handling |
| Copy | Copy editor | Review queue | Copy stage | Copy-only queue |
| Fact-check | Fact-checker | Review queue, claim checklist | G14 fact-check, claim desk | Official stage; proposals the writer accepts (Q5, Q6) |
| Standards/legal | Standards editor | Review queue | Embargo refusals | Official stage; legal hold (Q4, Q5) |
| Ready | Section editor | Desk board | | `ready` (Q7) |
| Schedule, publish | Publisher | Story panel, Edition planner | `content.publish`, fronts, newsletters, cadence queue | Edition, print/PDF (Q11), hold check |
| Monitor | Editor | Desk | `distribution.stats` | Queue age, time-to-publish |
| Correct | Standards editor | Story panel | Corrections log | Fast correction with public note |
| Retract / take down | Managing editor | Story panel | | `taken_down` serving 410 or redirect (Q8) |

## 6. Low-fidelity UX (internal; written, not pixel)

Every screen is a React studio workspace (AGENTS.md); the extension counterpart or a recorded gap comes with it. Every screen is keyboard-operable and every state is announced to a screen reader; the frontend-platform dependency (Q10) supplies the shared primitives, and a screen does not ship a private substitute.

**Home: "what needs me."** One list, grouped by urgency: due today, sent back to me, waiting on me (review, fact-check, standards), blocked (with the reason), scheduled to go out. Each row shows the story, the stage, who holds it, the due time and the one action available to me. A role's view is the same list filtered by desk membership and permission.

**Assignment desk.** Per desk: a board by status (today's board) with a second lens by week; each card shows headline, owner, deadline, slot date, priority, the next stage and a money line (budgeted, committed, spent, in the desk's currency). A header shows slots filled versus planned and money remaining. Pitches arrive in a left column; assigning is a keyboard-reachable menu as well as drag. Overspend is a visible warning, not a blocker. Budget editing needs a desk permission distinct from editing a story. Freelancer rows show only their own.

**Story workspace.** One page with a main column and a side rail. Main: the draft in the existing editor. Rail tabs: Notes and interviews, Sources (linked to the source directory, with the confidential flag), Claims (claim-to-source links and the fact-check checklist), Attachments, Comments, History (revision compare, corrections), Distribution. A status bar shows stage, owner, due, embargo, hold and lock state. Opening a story someone else is editing says who, since when, and offers read-only or a suggestion, never a silent overwrite.

**Review queues.** Per role (editing, copy, fact-check, standards/legal, peer review): rows sorted by oldest and due, each with a plain-language blocking reason (waiting for an editor, claim without a source, legal hold, embargo until 18:00, channel not set). Actions: approve the stage, send back with a note, propose an edit (fact-check). A story under a legal hold shows the hold and no publish action anywhere.

**Edition planner.** An Edition has sections, a story count and a money budget per section, a close date and an output (web issue, print/PDF). Stories are placed by drag or menu; the planner flags missing `ready` stories before the close date.

**AI and sources.** AI help in the workspace uses the same suggestion mechanism as today. It never receives, quotes or logs a confidential source's identity (§ 8).

## 7. Format model (Q1, provisional)

Formats are overlays: a format is a named set of fields, allowed stages and publishing rules attached to a `Story`/ArticlePage and a desk, not a new page type. Only two things need their own type.

| Format | Base | What the overlay or type adds |
| --- | --- | --- |
| News article, feature | `Story` | Today's fields; desk-level stage opt-ins |
| Opinion, editorial | `Story` + opinion desk | Required label, opinion editor stage, no fact-check opt-out unless the desk says so |
| Blog, column | `Story` | Column franchise (author, cadence, byline rule) |
| Brief, newsletter | `Story` / existing newsletter | Unchanged |
| Multimedia | `Story` + media | Rights, credit, caption and alt text enforced |
| Live updates | `Story` | Timestamped updates as a log on the story; distinct from the fast path |
| Corrections, retractions | log on the live page | Q8: a retraction is a kind of correction |
| Citations, references | Research `Source`, `Citation` | Citation styles; no new type |
| Paper (journal) | `Story` + journal desk | Peer-review stage tasks, versions, Edition membership |
| **Edition** (new) | | Magazine or journal issue: sections, order, budget, close date, print/PDF output |
| **Classified listing** (new) | | Short, dated, category, contact, expiry; review then publish; no payment |

Citations are not a story format: they are Research objects the story links to. Journals stay separate from Books (Q3, provisional) because peer review, versioned submissions and issue membership are not a book's chapter workflow.

## 8. Permissions and confidentiality

**Principles.** Least privilege by desk membership. The identity of a confidential source is the most restricted datum in the platform. A hold is stronger than a schedule.

**Confidential source (Q4).**
- A source has a visibility of *open* or *confidential*. For a confidential source the identity (name, contact, location, notes that identify them) is visible only to the reporter who owns it and one named standards or managing editor, recorded on the source.
- Everyone else sees a stable pseudonym ("Source C-7") and the claims it supports, not who it is. Fact-checkers check the claim against the pseudonymous source's description and the named editor's attestation.
- Never to AI, MCP or logs: the identity fields are excluded from every prompt, tool result, MCP resource, run step, suggestion payload, structured log line, error report, search index and export. Redaction is enforced where data leaves the store, not in each caller, and a test proves each egress. This is a security-sensitive requirement for the phase plan and a follow-up below.
- Viewing an identity is itself a recorded event visible to the named editor, with no identity in the record.
- Open question for the later design: what happens when the named editor leaves (re-designation by whom).

**Embargo.** Exists today and stays: a story may not go live before its embargo on any path. The role that can lift one remains the editors, not the reporter.

**Legal hold (Q4).** A hold is placed by a standards/legal reviewer or managing editor on a story, an Edition or a source. While a hold is active, publishing, scheduling, distribution to any channel (including newsletter, social and print/PDF) and newsletter inclusion are all refused on every path, as embargoes are today. Only the person with hold-release permission lifts it, with a recorded reason. A hold does not itself take anything down; `taken_down` (§ 9, Design for Failure) is separate.

**Roles and permissions.** Desk membership grants queue and board access; a separate permission set covers budgets, hold placement and release, correction and retraction, takedown, and distribution. A freelancer sees only assigned stories. Studio screens for permissions wait on the G3 Admin area (`platform.permissions`).

**Audit.** Every stage move, hold, release, correction, retraction, takedown and identity view is attributable. The platform audit log has no API or studio screen today (`platform.audit`); this plan needs one, under the same redaction rule.

## 9. Design for Failure

| Failure | Design |
| --- | --- |
| Lost edits | Autosave drafts on the server; local copy kept until the server acknowledges (extends #82); the workspace shows unsaved state and last save time. |
| Conflicting edits | Lock plus presence in the status bar; a second editor opens read-only or as a suggestion; on a conflicting save, show a side-by-side compare and require a choice. Never silently last-write-wins. |
| Failed scheduled publish | The failure is shown on the story, home and desk; the story stays `scheduled`, not `published`; one retry rule with backoff; a person is notified; a failed publish never partially distributes. Cadence-queue behaviour from #90 is reused. |
| Wrong-channel publish | A channel is chosen explicitly per story and shown in the confirmation; a confirmation names the live site and channel; distribution is a draft until a person approves it (today's rule); unpublish and recall paths per channel are documented, noting that a sent newsletter or social post cannot be recalled and so is gated hardest. |
| Fast correction | A correction on a live page publishes with a public note and an audit entry through a path that skips the full pipeline but not the standards editor's name; the correction log stays beside the page. |
| Takedown (Q8) | A `taken_down` state serves a 410 or a redirect, set per story; it removes the page from fronts, feeds, sitemaps and newsletters going forward, keeps the audit trail and the text for the record, and states the reason. A retraction is a correction on the live page and may precede or accompany a takedown. Restoring needs the same permission. |
| Hold during a scheduled publish | The hold wins; the schedule is paused, not deleted; release resumes it only if the person confirms. |
| Confidential source leakage | Egress redaction tests for AI, MCP, logs, search and exports; failing closed (a redaction error blocks the call). |

Each row becomes a test in the phase that builds it; recorded fixtures only, no live models.

## 10. Phase plan

Phases describe scope, dependencies and follow-ups. They are ordered by dependency, not by calendar, and each is a candidate for its own PRD requirements and child issues. **FEAT ids and PRD requirements are not assigned here:** they will be assigned later through the repo's numbering process (constitution § 6), after the owner accepts this plan. No catalog edit, no `FRn` row and no child issue is part of this PR.

| Phase | Scope | Depends on |
| --- | --- | --- |
| 0. Foundations (outside this epic) | Studio accessibility, RTL and keyboard primitives (Q10, the separate frontend-platform issue); the G3 Admin area for desks and permissions | frontend-platform issue, G3 |
| 1. Workflow and states | Stage opt-ins per desk; fact-check and standards/legal stages (Q5); `ready` (Q7); `taken_down` with 410 or redirect (Q8); retraction as a correction | TARGET amendment (below); G15 |
| 2. Desk, home and queues | One "what needs me" home; role-filtered queues with blocking reasons; desk money and slot budgets (Q2); contributor restriction (Q9) | Phase 1; G3 permissions |
| 3. Story workspace | One workspace; notes, attachments, claims, human comments, mentions, presence, conflict handling; fact-check proposals (Q6) | Phase 1; TARGET amendment |
| 4. Sources and confidentiality | Source directory, confidential sources (Q4), citation styles, legal hold, egress redaction from AI, MCP and logs; audit screen | Phases 1 and 3 |
| 5. Editions and print | Edition type; magazine and journal formats; paper format and peer-review tasks (Q3); print/PDF (Q11); classified listing without payments | Phases 1 to 4 |
| 6. Media, search and analytics | Media library with rights, credits and alt text; cross-object search; queue age and time-to-publish | Phase 2; `media.library`, `sites.analytics` |
| 7. Distribution and live | Per-channel status and links on the story; live updates; classified channel | Phases 1 and 5 |

Phase 4's redaction work is security-sensitive and must be designed and reviewed before any confidential source can be stored; Phase 3 does not store one.

## 11. Follow-ups (not started)

1. **`TARGET.md` amendment** (an amendment record under `docs/amendments/`, ratified when Amr merges it; not made in this PR): allow fact-check proposals (Q6, which also resolves PLAN G14's open decision), and add the new workflow stages: fact-check and standards/legal (Q5), `ready` (Q7) and `taken_down` (Q8; resolves PLAN G15's open decision).
2. **Confidential-source redaction from AI, MCP and logs** (Q4) as a security-sensitive requirement in the later phase plan.
3. **FEAT ids and PRD requirements** through the repo's numbering process, once the plan is accepted (Q12).
4. **Child issues per phase**, after (3).
5. **Frontend-platform issue** for accessibility and RTL (Q10): confirm it exists, or open it, and link #92 as dependent.
6. Visual-evidence validation of the low-fidelity UX, per the epic's checklist item 3; this document is the written form only.

## 12. Open questions

- Money budget: currency, one per desk or per story, and whether committed amounts come from contributor rates (which touches payments scope).
- Who re-designates the named editor on a confidential source (Q4)?
- Whether the opinion desk may opt out of fact-check (a desk-level setting, per Q5).
- Whether `taken_down` redirects need a destination picker or a default (the redirect manager, `content.redirects`, is missing today).
- The G14 and G15 PLAN lines that Q6 and Q8 now settle should be updated when the amendment lands.
