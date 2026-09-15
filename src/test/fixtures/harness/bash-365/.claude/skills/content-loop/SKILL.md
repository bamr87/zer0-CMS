---
name: content-loop
description: Run one cycle of the BASH content loop — turn a deterministic plan (a story from the practice's own recent work, or a page the same work made stale) into ONE on-voice article or improvement, gate it, record it in the ledger, and open ONE pull request. Use when asked to "run the loop", "write from recent work", "/loop-run", or on the daily schedule. Never merges.
---

# The content loop — one piece, from real work, one PR

The loop turns what the practice actually did — commits, pull requests, AI sessions, tools built — into content for the people BASH serves. A script decides *when* and offers *what*; you decide *the angle* and write it. Every run ends in exactly one pull request that a human merges. Operator's guide: [`docs/content-loop.md`](../../../docs/content-loop.md).

**The directive:** write about work that happened, for the reader who signs the checks. The work is the evidence; the article is the lesson. If there is no honest lesson in the offered work, say so and stop — never manufacture one.

## Hard guardrails

1. **Never push to `main`. Never merge or approve.** Branch `loop/<run-id>`, one pull request, stop.
2. **Never re-decide the plan.** `scripts/loop/plan.py` chose the mode and the cadence deterministically. You choose among what it offers (a story, a section it lists, a candidate page) — you do not invent a fifth option.
3. **Never invent.** No metrics, client names, logos, certifications, or outcomes that are not in the diff, the pull request, or the page. Real counts from the work (files, lines, days, the number of checks) are fine; ranges for everything else.
4. **Never expose** a secret, a token name's value, an internal hostname, a private client detail, or the contents of an unpublished draft. The repository is public and so is the article; the practice builds in the open, which is exactly why the line matters.
5. **Byline is `Amr Abdel-Motaleb`.** Agents draft, the human approves and owns the byline — the operating model the site describes at `/ai-operations/`.
6. **One story per piece.** A day-story may hold several unrelated commits; pick one thread, name it in the ledger's `signals`, leave the rest for another run.

## Sources of truth (read, don't restate)

- Voice and mechanics: [`content-style.instructions.md`](../../../.github/instructions/content-style.instructions.md) · brand: [`brand.instructions.md`](../../../.github/instructions/brand.instructions.md)
- Post rules and skeleton: [`posts.instructions.md`](../../../.github/instructions/posts.instructions.md) and [`article-write.prompt.md`](../../../.github/prompts/article-write.prompt.md); section voices: [`_data/taxonomy.yml`](../../../_data/taxonomy.yml)
- Toolkit pages: the `toolkit-doc` skill · cross-links: the `wikilinks` skill (pipeless, collection docs only) · identity: the `brand` skill
- The plan: `.loop/plan.md` (decision, ring, stories, candidates) and `.loop/digest.md` (every story's commits, files, changelog lines, session intent, and how to dig in)

## The run

### 1. Get the plan

In CI the plan is already in `.loop/`. Locally, produce it:

```bash
python3 scripts/loop/plan.py --out .loop            # decide today (add --no-remote without gh)
python3 scripts/loop/plan.py --out .loop --mode new --section erp   # operator overrides
```

Read `.loop/plan.md` and `.loop/digest.md`. If the decision is `IDLE`, report the reason and stop — an idle day is a correct outcome, not a failure.

### 2. Read the story for real

Pick the story: the best-scored one you can serve honestly in the section offered first, or the first section in the ring for which any offered story yields an honest angle (record the section you actually served — the ledger, not the plan, is the rotation's truth). Then read the work, not the headline:

```bash
git show --stat <sha>                 # what changed, how much
git show <sha> -- <path>              # the diff that matters
git log --format='%s%n%b' -1 <sha>    # the commit's own reasoning
```

Read the changed files as they are now. Read the pull-request line and changelog lines in the digest. For a sister-repository story, the digest is all you have — no network — so write from it or pick another. Extract: what changed, why, what broke or was decided, what it cost, and what a business could copy.

### 3. Translate it for the reader

The reader is not a maintainer of this repository. Per section (`_data/taxonomy.yml`): an owner or CFO (corp), a controller or operations manager (erp), a mixed practitioner audience (muses), an in-house IT lead (tech). Every piece answers *what this means for your business* — the practice's own work is the worked example ("we run this on our own site"), the pattern is the deliverable. Lead with the outcome, then the mechanism, then the reader's next step. Link the pull request or commit on GitHub as the primary source of the work; add one external primary source (vendor docs or a regulator) where a claim needs it.

### 4a. NEW — draft the article

- File: `pages/_posts/<section>/YYYY-MM-DD-<slug>.md`, today's date (`date -u +%Y-%m-%d`), the slug from the title by the house rule (lowercase, non-alphanumeric runs to `-`, 50 chars). Never overwrite an existing file.
- Front matter: the template below. `categories: [<section>]`, plus `ai` only when artificial intelligence is the main subject. Tags 3–8 from the common vocabulary in `taxonomy.yml`. `preview:` follows the slug rule; the image is generated later (the PR notes it).
- Body: the post skeleton (hook → why now → what we'd do → how it plays out → watch-outs → next step), sentence-case headings starting at H2, every acronym expanded on first use, no banned phrases, exactly one CTA to a `/services/…` page or `/contact/`. One paragraph per line (the house markdown rule).
- Length: 700–1,100 words for tech and corp; erp pieces run 800–1,200 and are performed, never labeled; muses essays 900–1,400.
- Cross-link with pipeless `[[Exact Page Title]]` to collection docs; root pages (`/tools/`, `/ai-operations/`) get a markdown link.

### 4b. IMPROVE — expand the page

- Take the first candidate unless a later one is the better reader outcome (say why in the PR).
- Add the substantive section the recent work justifies — a decision the page left open, a step that changed, a fact that moved — and refresh anything the work made wrong. Do not pad, do not rewrite what is good, do not retitle (the preview image is derived from the title), keep the single CTA.
- Bump `lastmod` (never `date`). Toolkit docs keep their front matter contract from the `toolkit-doc` skill; services keep theirs from `services.instructions.md`.

### 5. Gate it

```bash
python3 scripts/content_lint.py                 # zero errors in your file
python3 scripts/doctrine_check.py               # DRY / SSOT
python3 tools/unwrap-prose.py --check <file>    # one paragraph per line
```

Then the checks scripts cannot make: the section voice, enact-don't-announce, BASH in full caps, no invented claims, one CTA, wikilink titles that exist exactly. The final read-through is the strongest model's job, not a subagent's.

### 6. Record the run

```bash
python3 scripts/loop/ledger.py --record --mode <new|improve> --section <section> \
  --path <file> --title "<title>" --signals <story-id>[,<sha>…] --summary "<one line>"
```

The run file lands under `_data/loop/runs/` and is committed **with** the content — it is how the loop remembers the cadence, the rotation, and which stories are spent.

### 7. Open the pull request and stop

```bash
git checkout -b loop/<run-id>          # the run id the ledger printed
git add <file> _data/loop/runs/<run-id>.yml
git commit -m "content(<section>): <new|improve> — <subject>"
git push -u origin loop/<run-id>
gh pr create --base main --title "content(<section>): <new|improve> — <subject>" --body-file <body.md>
python3 scripts/loop/ledger.py --set-pr <run-id> <pr-url>   # then commit + push that one-line change
```

Write `loop-result.json` at the repo root: `{"pr": "<url>", "branch": "loop/<run-id>", "file": "<path>", "mode": "<mode>", "section": "<section>", "run": "_data/loop/runs/<run-id>.yml"}`. Then stop. A human merges.

## Front-matter template (new post)

```yaml
---
title: "Sentence-case title, no trailing period"
sub-title: "One line that sharpens the promise"
description: "120–155 chars, one sentence, outcome first, no trailing period"
excerpt: "One or two sentences for listings"
author: "Amr Abdel-Motaleb"
layout: article
date: YYYY-MM-DDT12:00:00.000Z
lastmod: YYYY-MM-DDT12:00:00.000Z
draft: false
categories: [tech]
tags: [ai, automation, smb]
keywords: [five to ten real search phrases]
preview: /images/previews/<slug>.png
---
```

## Pull-request body

State the mode and the planner's reason; name the story (link the pull request or commits it came from) and the section you served and why; list what changed; add the reviewer's checklist (generate the preview image at the `preview:` path for a new post; confirm wikilinks resolve; merge). Optional `## Backlog ideas` bullets for threads you left in the story.

## When there is nothing honest to write

If every offered story is trivial, already covered, or would need invented specifics, do not write. Put the reason in `loop-result.json` as `{"pr": "", "reason": "…"}` and stop. The planner will widen its window and the next run will look again.
