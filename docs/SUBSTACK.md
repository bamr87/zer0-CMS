# Substack

> Carrying a book's chapters — a serial such as the books library's `cost-line` pilot — to a Substack publication: the sanctioned routes (an RSS feed for Substack's importer, a paste-ready copy), the unofficial adapter that is off by default, and how a sync detects, contains, recovers from and logs failure.

## User story

As an author publishing a serial (one book of a series, chapter by chapter) from the books library, I want each chapter carried to my Substack publication — as a draft while I am still working on it, as a post once I mark it published — keyed by its canonical URL, so that re-running the sync never makes a second post, a failure on one chapter never loses the others, and I never have to hand Substack a password the platform stores.

## What Substack allows (researched 2026-11-01)

| Route | Sanctioned? | What it does | Limits |
|---|---|---|---|
| **Post importer reading an RSS feed** (Settings → Import/Export → Import posts) | Yes — Substack's help centre documents it for any platform with an RSS feed | Imports every item in the feed; **"Update existing posts"** on a re-import updates instead of duplicating | A person starts each import in the dashboard; imported posts arrive **published** (not drafts) and are not emailed unless chosen; some feeds are rejected without a reason; no per-post selection. Support articles: [import from another platform](https://support.substack.com/hc/en-us/articles/360037830351), [move to Substack](https://support.substack.com/hc/en-us/articles/34558456517396) |
| **Copy and paste into the editor** | Yes — Substack's documented manual import | A person makes the draft, sets its date and audience | Manual, one chapter at a time |
| **Substack Developer API** | Yes, but read-only | Public profile and publication data only ([API terms](https://substack.com/api-tos)) | Cannot create, update or publish posts |
| **Email to publication** | — | Substack has no post-by-email address | Not a route |
| **Undocumented web endpoints** (`/api/v1/drafts`, as `python-substack` uses) | **No** | Create and update drafts, publish | Undocumented; may change or break without notice; authenticates with a person's browser session cookie; automated use may breach Substack's Terms of Use (the API terms forbid circumventing access controls). Off unless the operator arms it |

So the platform defaults to the feed and the copy package, and keeps the unofficial route behind the same adapter interface, off.

## Using it

```bash
cd content
# Sanctioned: a feed of the book's published chapters for Substack's importer — serve or host it, then paste its URL
SUBSTACK_CANONICAL_BASE=https://example.com/books python manage.py substack feed --book ../packages/books/library/cost-line --out /tmp/cost-line.xml --ledger ~/.zer0/substack/cost-line.json
# Sanctioned: a paste-ready .html and .md per chapter (drafts too)
python manage.py substack copy --book ../packages/books/library/cost-line --out /tmp/substack-copy --ledger ~/.zer0/substack/cost-line-copy.json
# Unofficial, off by default: drafts (and, when armed, publishes) through Substack's undocumented endpoints
ZER0_SUBSTACK_UNOFFICIAL=1 SUBSTACK_PUBLICATION_URL=https://you.substack.com SUBSTACK_SESSION_COOKIE=… python manage.py substack sync --book ../packages/books/library/cost-line --ledger ~/.zer0/substack/cost-line.json [--dry-run] [--force]
```

A chapter is **published** when its front matter says `status: published` (or `final`); any other status is a **draft**. Its canonical URL is its front matter's `canonical_url`, else `<SUBSTACK_CANONICAL_BASE>/<book slug>/<chNN>/`. The feed carries only published chapters (the importer publishes what it imports); the copy package and the unofficial adapter carry drafts too, and the unofficial adapter publishes only a published chapter, only when `ZER0_SUBSTACK_PUBLISH` is on, and without emailing subscribers (`send: false`). It never rewrites a post that is already live.

## Configuration (environment only)

| Variable | Default | What |
|---|---|---|
| `SUBSTACK_PUBLICATION_URL` | — | The publication's https address |
| `SUBSTACK_CANONICAL_BASE` | — | Base of chapters' canonical URLs (or `--canonical-base`) |
| `SUBSTACK_SESSION_COOKIE` | — | Unofficial adapter only: the `substack.sid` session cookie. A secret: environment only, never a file, a row or a log line |
| `ZER0_SUBSTACK_UNOFFICIAL` | off | Arms the unofficial adapter |
| `ZER0_SUBSTACK_PUBLISH` | off | Lets the unofficial adapter publish (otherwise drafts only) |

## Failure: detect, contain, recover, log

- **Detect** — every failure is a `SubstackError` saying whether a retry may help (429, 5xx, a dropped connection) and whether the write may have landed (a 5xx or a broken connection after a write).
- **Contain** — one chapter's failure never stops the rest; the command lists every chapter's outcome and exits non-zero if any failed.
- **Recover** — retryable failures with no doubt are retried with exponential backoff (3 attempts). A write in doubt is never retried: it is ledgered `unconfirmed`, and that chapter is refused until a person checks Substack and syncs with `--force`. A 401/403 asks for a fresh session cookie.
- **Log** — one line per outcome through `logging`; no message carries the cookie.
- **Idempotency** — the ledger (`--ledger`, required and kept outside the book, whose `library/<slug>/` is a generated tree) is `distribution/ledger.py`'s file format with `target: substack`, keyed by canonical URL with the content digest and the state on Substack; an unchanged chapter is not sent again, and a changed draft is updated in place, not duplicated.

## Where it lives

`content/distribution/substack/` (`chapters.py`, `adapters.py`, `sync.py`), `content/distribution/management/commands/substack.py`, tests in `content/tests/distribution/test_substack.py`. It reads the books library's files (`library/<slug>/book.yml`, `chapters/chNN.md`) through the `Chapter` interface; a loader from the platform's `BookPage`/`ChapterPage` rows, a channel kind in the distribution queue and a studio surface are follow-ups.
