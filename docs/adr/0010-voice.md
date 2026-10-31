# ADR 0010 — Voice: one scoped, versioned voice per site, resolved for every piece and pushed to every writer and every gate

> A site's voice — who it writes for, how it sounds, what it never says or claims — becomes one platform model with scopes below the site (section, content type, book, channel), resolved by one pure function into what a writer is told and what a gate checks, pushed into every AI run, recorded on every result, round-tripped through the site's files, and managed from a Voice area in the studio; the platform itself ships no brand.

- **Status:** proposed 2026-10-30; the open decisions are VD1–VD5 below. V0 landed the same day (read-only: `content/voice/`, the endpoints `voice/resolved/` and `voice/test/` under `/api/v2/sites/<id>/`, and the Voice tab of a site's page, `web/packages/ui/src/voice/`, proved in a browser by `verify/scenarios/studio-voice-resolve.yml`); PLAN § 3 Phase V tracks the rest.
- **Inputs:** the owner's direction of 2026-10-30 — zer0-CMS to run, maintain and manage bash-365.com as its content system, portable, extendable and production ready, with voice, brand and tone and their scope and distribution the first feature explored; the bash-365.com sources of its voice (`.github/instructions/brand.instructions.md`, `.github/instructions/content-style.instructions.md`, `_data/taxonomy.yml`, the `linkedin-share` skill, `scripts/content_lint.py`); P-D7 (the brand guard on fiction), the first site that needed out of the built-in bans.
- **Where (proposed):** a new app `content/voice/`; `content/ai/handlers.py` (`generate`), `content/agents/tools.py` (`brand.rules`), `content/suggestions/guard.py`, `content/agents/handlers/reviews.py`, `content/distribution/services.py`, `content/aieo/`, `content/books/context.py`; the studio's Voice area (`web/packages/ui/src/voice/`) and its extension counterpart through `WORKSPACES`; the site exporter and importer; the ledger row `sites.voice` in [`../plan/capabilities.yml`](../plan/capabilities.yml).

## Context

### Where a voice lives today

Five stores in the platform and a sixth in the extension, none of them scoped below a site, none composed with the others:

| Store | Scope | Read by | Not read by |
|---|---|---|---|
| `suggestions/guard.py` `BANNED_PATTERNS` (13 errors) and `FILLER` (9 warnings) | every site, "built-in" | the guard at propose and accept, the brand review, the `brand_clean` eval, the distribution guard, `brand.rules` | — |
| `cms.BrandRules` snippets (`style_guide`, `banned_patterns`) | every site at once (each active row) | the guard, `brand.rules` | AIEO's agents, the AI panel |
| `sites.SiteSettings.brand_voice`, `banned_patterns`, `chapter_builtin_bans` | one site | `brand.rules` (as a style guide), the guard | the editor's AI panel, assistants, pipelines, briefs and conversations (unless the model happens to call `brand.rules`), AIEO's agents |
| `aieo.BrandContext.brand_voice`, `style_guide`, `writing_examples` | one site | AIEO's agents | everything else |
| `cms.BookPage.style_guide`, `builtin_bans`; `ChapterPage.tone`, `style` | one book | the book's AI context (pushed: `books/context.py`), the guard's switch | — |
| `src/core/governance/guard.ts` | a site's files (file mode) | the extension's distribution lane | — |

The 13 bans are one house list copied three times: bash-365.com's `content-style.instructions.md`, mechanised in its `scripts/content_lint.py`, ported to the extension's `guard.ts` and from there, rule for rule, to `guard.py`.

### What is wrong with that

1. **It is not portable.** The platform's "built-in" bans are one site's brand — BASH Consulting's plain-English marketing rules — applied to every site the platform serves. P-D7 was the first site that needed out (fiction needs "revolutionary"); 1987 (encyclopedic, third person, neutral) and irony-works (satire, whose subject *is* corporate jargon) are the next. A switch per case does not scale; the default is wrong.
2. **The voice is pulled, not pushed.** The editor's AI panel runs an assistant with `system = persona.instructions` and nothing else (`ai/handlers.py`, `_page` → `generate`). The settings field labelled "How the site writes; AI help reads it" reaches a model only when the assistant lists the `brand.rules` read tool *and* the model chooses to call it — and no bundled assistant lists it (`content/ai/data/bundled.yaml`). The one surface that pushes a voice is books, which puts the style guide in every chapter prompt.
3. **It is flat.** bash-365.com writes in a site voice, four section voices (`_data/taxonomy.yml`: corp sharp and strategic for owners and CFOs, erp performed comedy whose device is never labelled, muses essayistic, tech crisp how-to), a register per content type (a service page a buyer reads before hiring, a toolkit guide by track, a post), a channel voice (LinkedIn: the hook before the 140-character fold, two or three hashtags, one call to action, never restating the card) and a visual tone (pixel art for posts, an isometric professional look for services, toolkit and about). None of the five below-site scopes has a home in the platform; each lives in a file an agent has to know to read.
4. **It is duplicated.** A site's voice is in two site settings that can disagree (`SiteSettings.brand_voice` and `BrandContext.brand_voice`), and its bans in three repositories.
5. **It is unversioned and unattributed.** Changing a voice is a settings save with no revision, no diff and no review; no run, suggestion or distribution post records which voice it was written under, so a reviewer cannot tell a draft written before the voice changed from one written after.
6. **The site's own agents cannot reach it.** bash-365.com's Claude Code skills, its Copilot instructions and its scheduled content lanes read the repository's files; the platform exports a site's pages but not its voice.

### What distributing a voice by copying costs: bash-365.com today

bash-365.com keeps its voice in three files of record and distributes it to about twenty-five consumers — six skills (each also hand-copied, byte for byte, into `.agents/skills/`), five agents (mirrored again in `.codex/agents/`), three commands, two prompts, two file-scoped instructions, four scheduled workflows, the lint, the content loop's section picker, the preview-image styles and `llms.txt`. Most link to the source and then restate part of it, and the restatements have drifted:

- The LinkedIn skill gives the sections voices the taxonomy does not: "erp = back-office wry", "tech = practitioner" (`linkedin-share/SKILL.md`), against "performed comedy with a real business lesson underneath" and "crisp, actionable how-to" (`_data/taxonomy.yml`).
- The words a piece must never use to name its own device are five different lists (the taxonomy, the content style, the editorial skill, the review prompt, an agent's memory).
- Exclamation marks are banned outright by the content style, allowed in performed dialogue by the review prompt, an error only in a title or description for the lint, and a warning for the platform's guard.
- The writing prompt bans a bare "fast-paced" no other list has, and asks every post to link to a service page *and* the contact page — two calls to action where the content style allows one.
- `llms.txt`, the file AI engines read, carries a different positioning line from the brand's canonical one.
- The lint does not read `tools.md` or `ai-operations.md`, which the editorial skill says it covers.

Each copy was right when it was made. A voice that is resolved from one source at the moment of writing cannot drift this way; a voice that is copied to each writer always will.

## Decisions

| # | Decision | Mechanism that enforces it |
|---|---|---|
| 1 | **One model, `voice.VoiceProfile`**, with a UUID `public_id`, a row per scope: `platform` (at most one, shipped empty), `site`, `section` (a site and a category, or a site and a page subtree — VD3), `type` (a site and a page type or collection), `book` (a `BookPage`) and `channel` (a distribution `Channel`, or a channel kind on a site). Its fields are structured, not one text: `summary` (the register in a sentence), `audience`, `guidance` (Markdown: do), `avoid` (Markdown: do not), `claims` (what may never be claimed), `vocabulary` (`[{term, expansion}]` — the terms to prefer and the acronyms to spell out on first use), `bans` (`[{name, pattern, flags, level}]`, `level` error or warning), `lifts` (names of inherited bans this scope switches off), `limits` (a channel's length, fold and hashtag count) and `examples` (pages, each with why it works). A profile has revisions and a draft state: a change is a draft until a person who may manage the site publishes it, and the publish is logged. | `content/tests/voice/test_models.py`; `content/tests/api/test_public_ids.py` |
| 2 | **One pure resolver**, `voice.resolve(site, *, page=None, channel=None) -> ResolvedVoice`: the layers in order platform → site → section → type → book → channel; text fields joined in that order under a heading naming each layer; bans merged by name (a later layer's ban of the same name replaces the earlier one; `lifts` remove one); a channel's limits win. The result carries every item's layer (its provenance) and a `digest`, the sha256 of its canonical JSON. Nothing else composes a voice. | `content/tests/voice/test_resolve.py`, including a golden resolution of bash-365.com's imported voice for one page of each section and the LinkedIn channel |
| 3 | **The voice is pushed into every run that writes for a site.** `generate` puts the resolved voice before the persona's instructions in the system prompt of a run on a page, a brief with a target, a conversation about a page and a book's chapter (the page text stays data, as now); `brand.rules` answers with the resolved voice and its layers; AIEO's agents read it in place of `BrandContext.brand_voice` and `style_guide`, which move into the site's profile; the book context reads it. An assistant may opt out (`voice: false`, for a translator or a parody desk's own persona — VD4), and the run records that it did. | `content/tests/ai/test_voice_push.py` on the `fake` and `recorded` adapters: the system prompt carries the resolved voice and its digest; an opted-out assistant's does not |
| 4 | **The gates read the same resolution.** The guard (`page_findings`, `guard_text`), the brand review, the `brand_clean` eval and the distribution guard take a `ResolvedVoice`. The built-in lists leave the code: they become a starter profile, *Plain-English marketing*, that a site adopts (VD1). On the day this lands, a migration attaches the starter as the platform layer of an existing deployment, so no site's behaviour changes; a new deployment starts empty. P-D7's switches become data — a `lifts` on the book's or the site's layer — and the markup check stays code, because it is the page's safety, not the brand's. | `content/tests/voice/test_gates.py`; the P-D7 tests (`content/tests/books/test_ai.py`) pass unchanged on the migrated data |
| 5 | **Every result records the voice it was written under:** `AgentRun.voice_digest`, `Suggestion.voice_digest`, `DistributionPost.voice_digest`. The review inbox and a post's panel say when a suggestion or a draft was written under a voice that has since changed. | `content/tests/voice/test_attribution.py`; `web/packages/ui/test/voice.test.tsx` |
| 6 | **A site's voice round-trips through its files**, like its pages: export writes one YAML file per profile under `.zer0/voice/` and a generated `VOICE.md` that agents and people outside the platform read; import reads them back; the round trip is byte-stable. It follows `ManagedSite.content_source`: a site still on files is imported on sync, a site on the platform is exported on write-back. A first `import_voice` maps a site's existing voice files into profiles (bash-365.com's mapping is below). | `content/tests/voice/test_roundtrip.py` |
| 7 | **The studio has a Voice area per site**, and the extension has it through `WORKSPACES` with no host code: the scope map, the profile editor, the resolved voice for any page and channel, a tester, history and coverage (below). The editor's AI panel and the Distribute dialog show the voice a run or a post will be written under. | `web/packages/ui/test/voice.test.tsx`; a browser scenario `studio-voice-resolve` in `verify/scenarios/` |

## The studio

The Voice area answers three questions a person running a site has: *what does this site sound like, where does each rule apply, and what exactly is each writer told?* It lives at `/studio/sites/<id>/voice[/:section]`, a tab of the site's page beside Settings, and replaces the Brand voice box and the Banned phrases table there (and the brand voice and style guide of AIEO's Context tab).

| Section | What a person does there |
|---|---|
| **Map** | The scope tree — Site, then its sections, content types, books and channels — each node marked as having its own layer, inheriting, or lifting a ban, with how many pages it governs; a node opens its profile |
| **Profile** | Edit one layer's fields; beside each field what it inherits and from where, so a person sees "adds two bans, lifts *revolutionary*" before saving; save a draft, publish, discard |
| **Resolve** | Pick a page (or a section and a type) and, optionally, a channel: the composed voice with each line coloured by its layer, its digest, the exact preamble a model receives and the rules the guard will hold it to — the voice's distribution made visible |
| **Test** | Paste text or pick a page: the guard's findings under that resolution, at once and without a model; optionally ask a voice-review assistant, which answers as findings or suggestions in a run like any other |
| **History** | The revisions of every layer with a diff, who published each, and the runs, suggestions and posts written under each digest |
| **Coverage** | Pages by scope; guard findings by section over time; drafts and suggestions written under a voice that has since changed |

```
 bash-365.com › Voice                                    [Map] Profile  Resolve  Test  History  Coverage
 ┌───────────────────────────────┐ ┌─────────────────────────────────────────────────────────────────┐
 │ ● Site — BASH Consulting      │ │ erp — section                    published · a draft is open      │
 │   sections                    │ │ Summary   Performed comedy with a real business lesson underneath │
 │   ├ ● corp               5    │ │ Audience  Controller, operations manager                          │
 │   ├ ● erp                5    │ │ Guidance  Scenes, characters and running bits that dramatize how  │
 │   ├ ● muses             10    │ │           ERP projects actually go …                  ↳ adds      │
 │   └ ● tech               8    │ │ Bans      parody · satire · sketch · musical number  ↳ adds 4    │
 │   types                       │ │           (reader-facing text names the device)                   │
 │   ├ ○ post  (inherits)  28    │ │ Inherits  Site: 13 bans, 9 warnings, claims, vocabulary            │
 │   ├ ● service            8    │ │                                  [Save draft]  [Publish]  Resolve →│
 │   └ ● toolkit doc       28    │ │                                                                   │
 │   channels                    │ │                                                                   │
 │   └ ● LinkedIn                │ │                                                                   │
 └───────────────────────────────┘ └─────────────────────────────────────────────────────────────────┘
```

The counts are bash-365.com's pages today (`pages/_posts/<section>/`, `pages/_services/`, `pages/_toolkit/`, section indexes left out).

In Write, the AI panel names the voice it will write in — *Writing as: BASH › erp › post* — with the resolved layers a click away; the Distribute dialog and a post's panel show the channel's layer and limits beside the guard's findings. Every screen is `@zer0/ui` under the host contract (`web/README.md`), so the extension's dashboard renders the same Voice tab and its page view the same chip.

## What it means for bash-365.com

| bash-365.com today | Profile | Fields |
|---|---|---|
| `brand.instructions.md` — name and capitalization, positioning, doctrine, verbal identity, never-claim rules | site | `summary`, `guidance`, `claims` |
| `content-style.instructions.md` — reader profile, voice and tone, words to use and avoid, numbers and claims, localization | site | `audience`, `guidance`, `avoid`, `vocabulary`, `claims` |
| The 13 bans (`content-style`, `content_lint.py`) | site, from the *Plain-English marketing* starter | `bans` |
| `_data/taxonomy.yml` — corp, erp, muses, tech (voice and audience) | four sections | `summary`, `audience`, `guidance` |
| erp's rule that no reader-facing text names the device ("parody", "satire", "sketch", "musical number") | the erp section | `bans` — a rule no store can hold today, because none is scoped below a site |
| `services.instructions.md`; the toolkit's business and partner tracks | types | `audience`, `guidance` |
| The `linkedin-share` skill's LinkedIn rules | the LinkedIn channel | `limits` (3,000 characters, the 140-character fold, two or three hashtags), `guidance` |
| `_config.yml` `preview_images` styles | not in this ADR | a `visual` field per scope is the natural next step for the media pipeline |

While bash-365.com is on files (VD2), its voice files stay the source: the platform imports them on sync and every studio surface shows them read-only with "edit in the repository". Once it moves to the platform, the platform exports `.zer0/voice/` and `VOICE.md`, `scripts/content_lint.py` reads its bans from there instead of its own list, and the skills point at `VOICE.md` — one list, not three.

## Order of work

Each step is useful alone and leaves the platform working.

| Step | What lands | Changes behaviour? |
|---|---|---|
| V0 — make today visible | A resolver over today's stores (built-in → `BrandRules` → `SiteSettings` → `BrandContext` → book), `GET /api/v2/sites/<id>/voice/resolved/?page=&channel=`, and the studio's Resolve and Test views, read-only — which shows exactly which writer reads what, and corrects the "AI help reads it" label | No |
| V1 — the model | `VoiceProfile` with the site, section, type and channel scopes, revisions, the Map and Profile views; the voice fields of `SiteSettings` and `BrandContext` migrated into site profiles; `import_voice` for bash-365.com | No (the resolver reads the new rows) |
| V2 — push | `generate`, `brand.rules`, AIEO and books read the resolution; `voice_digest` on runs, suggestions and posts | Yes: every page-bound run is told the voice |
| V3 — gates | The guard and the reviews read the resolution; the built-in lists become the starter profile; P-D7's switches become lifts; the extension's guard reads the exported bans or the API | No for existing sites (the migration attaches the starter) |
| V4 — files | Export and import of `.zer0/voice/` and `VOICE.md`; bash-365.com's lint and skills read them | bash-365.com's side only |
| V5 — judgment | A voice-review agent at policy `suggest` (comments and findings, never blocking a publish) and adherence evals on recorded fixtures | Advisory only |

## Open decisions

- **VD1 — the built-in bans.** Proposed: they become the opt-in *Plain-English marketing* starter, attached to existing deployments by migration so nothing changes for a site that does not ask. The alternative is to keep them as the platform's default and give every site P-D7's switch.
- **VD2 — bash-365.com's source of truth during the move.** Proposed: its files, imported on sync, until its `content_source` is `platform`; the studio edits its voice only from then. The alternative is to move the voice to the platform first and export it.
- **VD3 — what a section is.** Proposed: a category or a page subtree, whichever the site uses; bash-365.com's primary category is also its folder, so either works there, and a newsroom's desks are subtrees.
- **VD4 — push by default.** Proposed: every run that writes for a site is told its voice unless its assistant opts out. The alternative, opt-in per assistant, keeps today's behaviour and today's gap.
- **VD5 — who edits a scope.** Proposed: `sites.manage_site` for every scope of the site at first; per-scope permissions (a desk editor owns the desk's voice) when the newsroom needs them.

## Consequences

- Every page-bound run's prompt grows by its resolved voice. The resolver reports its size; the studio warns above a threshold, and the run's cost already shows it.
- The guard's behaviour is data, not code, so a broken profile must never brick it: a malformed ban is skipped, as a malformed `banned_patterns` entry is today, and the markup check stays in code.
- AIEO keeps `BrandContext` for what is AIEO's (keywords, competitors, the internal-links map, SEO and CRO notes); only its voice fields move.
- The extension's file mode reads the exported bans, so its guard and the platform's say the same thing from the same file, not from two copies of one list.
- A site's voice is reviewable like its pages: drafted, diffed, published by a person, and visible on everything written under it.
