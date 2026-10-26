# `newsroom/` — operating a news site

Desks, the story budget and the editorial calendar, assignments, the newsroom workflow with embargoes and a breaking-news fast path, home and section fronts, bylines and author pages, a corrections and updates log on every story, and newsletters — [TARGET.md](../../docs/plan/TARGET.md) § The newsroom, built in PLAN G15. parodynews (barodybroject) runs here as a newsroom with a **Parody desk**. The studio's Newsroom workspace (`web/packages/ui/src/newsroom/`) is where people use all of it.

## The pieces

| File | What |
|---|---|
| `models.py` | `Desk`, `Story` (+ `StoryEvent`, its history), `StageTask` (a Wagtail workflow task), `Author` (a snippet) and `Byline`, `Correction`, `Front` and `FrontSlot`, `Newsletter`, `Issue` (+ `IssueStory`, and `IssueDelivery`: who has had it), `Subscriber`; `visible_to(user, site)` |
| `services.py` | Every command: pitch, plan, assign, move through the workflow, release, correct, fronts, subscriptions, issues, AI help, the bundled AI rows, and what the page API and the export show; `publish_refusal`, the rule every publish path is held to |
| `workflow.py` | Where Wagtail meets the stories: `WAGTAIL_FINISH_WORKFLOW_ACTION`; the receivers for a stage sent back, a workflow cancelled and a page gone live (which refuses a publish the story holds back); Wagtail's workflow email kept away from the newsroom's stages |
| `wagtail_hooks.py` | The Wagtail admin's editor saying why a story's page was not published |
| `tasks.py` | Email on the worker: an issue to its confirmed subscribers (once each, resumable), a subscription's confirmation |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/newsroom/`, and the pages a newsletter's links open under `/newsletters/` |
| `data/bundled.yaml` | The newsroom's assistants, schemas and pipeline in the AI content layer |
| `templates/newsroom/` | An issue as text and as HTML; the confirmation email; the page a confirm or unsubscribe link opens |
| `management/commands/seed_parody_desk.py` | parodynews as a newsroom |

## Desks and stories

A **desk** is a section of a site (`section`: the page its stories' pages go under, a site root or a collection) and the people who run it: its **editors** assign, approve the editing stage, publish breaking news and correct published stories; its **copy editors** clear copy (its editors do, when it has none). A desk may name its writer: an assistant or a pipeline of the AI content layer. Setting a desk up is a Django permission (`newsroom.add_desk`, `change_desk`); seeing one is anyone's who works on its site.

A **story** is the planning record behind a page: headline, slug (unique on its desk), the pitch (`summary`), priority, assignee, deadline, slot date (the day it runs), **embargo** (the earliest it may go live), its page once it has one, the brief an AI draft came from, the wire item it was pitched from (`source`), and its bylines. Its priority, deadline, slot and embargo are the desk's decisions: its editors change them, its reporter reads them (`services.DESK_DECIDES`). The headline, the pitch and the bylines are the reporter's too, and a pitch is also its pitcher's until it is assigned. The **story budget** and the **editorial calendar** are the story list's filters: status (several at once), desk, site, `assignee=me`, `my_desks`, slot and deadline ranges, text, and an ordering (`-page__first_published_at`: the newest published first). Every assignment, move, fast path, change of embargo, correction and update is a `StoryEvent` — the story's history, and with it the assignment history.

## The newsroom workflow

```text
pitch ─► assigned ─► drafting ─► editing ─► copy ─► scheduled ─► published ─► updated / corrected
                        ▲           │  └──────────────────────────┘ ▲  (breaking: copy skipped, with a reason)
                        └─ sent back ┘ (from editing or copy)
```

| Move | Who | What happens |
|---|---|---|
| pitch → assigned | the desk's editors | the assignee is set (a person who works on the site) |
| assigned → drafting | the editors or the reporter | the page is created as a draft under the desk's section (`cms.services.create_draft`, so the person needs Wagtail's add right there) — or the AI draft's page becomes it (`apply-draft`) |
| drafting → editing | the editors or the reporter | the page enters the **Newsroom** Wagtail workflow (Editing, then Copy); a story sent back resumes at the stage that sent it back |
| editing → copy | the desk's editors | they approve the Editing stage in Wagtail |
| editing/copy → drafting | that stage's approvers | Wagtail's "request changes", with the comment |
| copy → scheduled | the copy editors | the Copy stage approved, and the page scheduled through `cms.services.schedule` for the time given, or the embargo |
| copy → published | the copy editors | the Copy stage approved, and the page published through `cms.services.publish_now` — refused while the embargo is in the future |
| editing → published | the desk's editors | **the breaking-news fast path**: a reason is required, Wagtail records the Copy stage as *skipped* with it, the story keeps it (`breaking`, `fast_path_reason`), and the page is published now |
| scheduled → published | Celery beat, or the copy editors once the embargo has passed | the scheduled publish (`cms.tasks.publish_scheduled`) |
| published → updated/corrected | the desk's editors (with the page's publish right) | a `Correction` on the page's log, shown at once by the page API and the export; it publishes nothing else — not a page taken down, not a draft saved since the page went live: a fix goes live from the editor's Publish, where the person sees what goes with it |

Editing and copy are Wagtail's own workflow machinery: `StageTask` is a `Task` whose approvers are the story's desk, so while a page is at a stage only they may change it (Wagtail's workflow lock, which `cms.services.writable` honours), the Wagtail admin's moderation sees them, and every decision is in Wagtail's log. Reaching a stage moves the story there (`StageTask.start`). Approving the last stage publishes nothing: `WAGTAIL_FINISH_WORKFLOW_ACTION` (`workflow.finish_workflow`) leaves a newsroom workflow's page to the newsroom, which publishes or schedules it through `cms.services` under the person's Wagtail publish permission — a person without it gets a 403 and the approval is rolled back with it. Every other workflow still publishes when approved. A stage sent back in the Wagtail admin, or a newsroom workflow cancelled there (the requester and the page's owner may), moves the story back to drafting, from where it is submitted again. The newsroom's stages send none of Wagtail's workflow email (`workflow.not_for_the_newsroom`): people follow them in the studio, and Wagtail would mail from inside the request — even an approval whose publish was then refused and rolled back.

**A story's page goes live only through the newsroom, by any route.** A page can go live from Write's Publish and Schedule, the Wagtail admin, an agent's `content.publish`, an importer, or the scheduled publish on Celery beat; Wagtail sends `page_published` from inside each of them (and for a page's first schedule), and `workflow.on_page_published` holds them all to `services.publish_refusal`: a story still being made (pitch through copy) goes live only through the moves above — so copy is never skipped without the fast path's reason — and no story's page goes live, or is scheduled to, before its embargo. A refusal is a 409 (`story.in_workflow`, `story.embargoed`) that rolls the publish back with the transaction each of those paths runs in; the Wagtail admin's editor says why (`wagtail_hooks.py`). A scheduled story's page, or a published story's fix, goes live from Write as any page does once its embargo has passed, and the story is recorded as published. One exception: an importer replaying a source still canonical for the site (a revision by the legacy-import principal — a post barodybroject published after its desk adopted it as a draft) publishes the story's page and moves the story on; the embargo holds even then.

## Bylines, author pages and corrections

`Author` is a snippet (name, slug, bio, email, the person if there is one); a story's bylines are ordered authors. One author may write for several sites, so an author is seen by the people of the sites their stories are on (and, while no story carries them, by every desk), and changed or deleted by staff or by someone who edits a desk on every one of those sites — never by one site's editors for another's bylines; an author with bylines is not deleted (409). An author's page (`authors/<id>/`) lists their published stories. A **correction** or an **update** is a `Correction` on the page — date, kind, text — kept beside the page rather than in its revisions, so a revert never loses one. Both reach the site: the page API (`/api/v2/pages/<id>/`) carries `bylines` and `corrections` on every page, and `export_jekyll` writes `authors` and `corrections` into the front matter (an imported page that has them is rendered rather than written back verbatim; a page without them exports exactly as before).

## Fronts

A **front** is a site's home front (no desk) or a desk's section front: ordered slots, each **pinned** to a story (shown while its page is live) or filled by a **rule** — the next latest published story of a desk (any desk on the site, without one) that is not already on the front. `fronts/<id>/stories/` is the front as a reader finds it. The site's desk editors curate fronts.

## Newsletters

A **newsletter** belongs to a site. Subscribing is double opt-in: `newsletters/<id>/subscribe/` (public, for a site's own form) answers the same either way and emails a confirmation link — at most once an hour — and nothing else is sent to the address until the subscription is confirmed. Every emailed link (confirm, and unsubscribe in each issue and its `List-Unsubscribe` header) opens a page under `/newsletters/` that says what the link does and does it only when its button is pressed: a GET changes nothing, so a mail scanner or a link prefetcher cannot confirm or end a subscription, while a mail client's one-click unsubscribe (RFC 8058, a POST) works. A confirm link is signed, valid seven days, good only while the address waits to confirm and only for the latest request — so one still in a mailbox does nothing after the address unsubscribes. An **issue** is a subject, an introduction and stories of its newsletter's site in order (it stays on its newsletter); its preview is exactly what is sent (Django templates, text and HTML); sending it is a job (`202`) that the worker sends to the confirmed subscribers, each message with its own unsubscribe link and the one-click `List-Unsubscribe` headers. Every story in an issue is published first. Each subscriber gets an issue once: one worker at a time holds it (a lock in the shared cache), and every message the backend accepts is recorded (`IssueDelivery`) before the next — so a send that fails part way (an ESP throttling, say) is failed with how far it got and is sent again to the rest only, and an issue a worker left sending, or a task the broker delivers twice, resumes without mailing anyone twice. Mail goes through Django's mail API to `EMAIL_BACKEND`: a django-anymail ESP backend in production (Amazon SES, Mailgun, Postmark, SendGrid …; each message an `AnymailMessage` with tags and metadata), configured by `ANYMAIL_*` variables; Django's SMTP backend when it is unset (it fails loudly with no server; never the console, which would print every address and link into the logs); the console in development; Django's locmem backend in tests.

## AI help

Through the AI content layer only (`ai.services`): every generation is a run of the `assistant` agent, answered `202` and followed on `/api/v2/agent-runs/<id>/stream/`, and every result is something a person applies or accepts. The newsroom's assistants, schemas and pipeline are bundled (`data/bundled.yaml`, shared, seeded after every migrate, left alone once edited).

| `ai/` kind | Assistant | What a person gets |
|---|---|---|
| `pitch` | Pitch editor (schema *Story pitch*) | a headline, angle, why now, questions and sources from the story's wire item — applied to the story by hand |
| `draft` | the desk's writer, else the *Story from a pitch* pipeline (Reporter → Copy editor, the bundled *news article* schema) | a brief from the pitch; `apply-draft` makes it the story's page, its text arriving as suggestions |
| `headlines` | Headline editor (schema *Headlines and summary*) | the best headline and the summary as suggestions on the page (title, description), the alternatives in the rationale |
| `correction` | Corrections editor (schema *Correction or update note*) | a note drafted from what the editor says changed, to edit and post |

A wire or feed item is a pitch's `source` (`services.WireItem`: url, title, summary, text, feed, published at): pitching from one is creating a story with it. Research's sources (PLAN G14) become pitches through the same interface.

## parodynews as a newsroom

`manage.py seed_parody_desk [--editor USERNAME …]` makes, once, the parodynews site (as `import_parodynews` makes it, served at parodynews.localhost), the **Parody desk** whose writer is barodybroject's parody news writer (its prompt and parody news article schema, seeded by the AI layer), the newsroom workflow, a home front of the desk's latest five stories, and *The Parody Weekly*. Imported posts become the desk's stories. barodybroject's generate → review → publish is then the desk's draft (a brief from the parody writer) → editing and copy → publish.

## The API (`/api/v2/newsroom/`)

| Path | |
|---|---|
| `desks/` | list, retrieve; with the permission, create and change; `people/`: who its stories may be assigned to |
| `stories/` | the budget and the calendar (filters above); pitch (`source`: a wire item); retrieve (history, corrections, AI runs); change planning fields and bylines; spike a pitch; `move/`, `assign/`, `ai/` (`202`, `Idempotency-Key`), `apply-draft/` |
| `authors/` | the authors a person may see; create (a desk's editors); change and delete (the editors of every site their bylines are on); retrieve is the author's page |
| `fronts/` | CRUD with their slots; `stories/` |
| `newsletters/`, `issues/` | CRUD; an issue's `preview/` and `send/` (`202`; again for a failed or stalled send) |
| `newsletters/<id>/subscribe/`; `subscriptions/confirm/`, `subscriptions/unsubscribe/` (POST, the token) | public |
| `/newsletters/confirm/`, `/newsletters/unsubscribe/` (not under `/api/`) | the pages the email's links open: GET says what the link does, POST does it |

## Tests

`tests/newsroom/`: the workflow, with every publish path held to the story's rules and no Wagtail email from its stages (`test_workflow.py`), the API with visibility and permissions (`test_api.py`), fronts and newsletters with locmem email — the subscription pages, a send that fails part way and one that resumes, and production's email default (`test_fronts_and_newsletters.py`), AI help on the fake provider, the parody desk seed and a re-import after it (`test_ai_and_seed.py`), and the export (`test_export.py`). None reaches a model or a mail server.

## Not here yet

A "most read" front rule (needs analytics, PLAN G12), wire and feed subscriptions on a schedule (Research, G14), newsletter sends batched through an ESP's merge features rather than a message per subscriber, rendering bylines and corrections on the public site (the renderer, P6, and the Jekyll-theme option, P2), the extension's move-a-stage and add-a-correction (G10), setting a desk up in the studio (G3's Admin area), and a status for a story whose page was taken down (barodybroject's `archived`; it still reads published — an owner's decision). A message the backend accepted just before a worker died is sent again when the issue resumes: the record is written after each accepted message, so at most that one subscriber gets it twice.
