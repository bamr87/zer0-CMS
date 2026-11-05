# Distribution

> Distribution on the platform — channels (LinkedIn, X, WordPress, GitHub pull requests, newsletters), the queue, the brand guard, a person's approval, the ledger and statistics — and the LinkedIn and X lanes a site that is still files runs from its CI.

zer0-CMS carries a site's content to where its readers are — a LinkedIn company page or a member's own profile, an X account, a WordPress site, a GitHub repository as a pull request, a newsroom newsletter — and brings LinkedIn's and X's aggregate response back, where it decides what gets written next. A person approves every post. Nothing a repository ships can switch publishing on. Every LinkedIn and X call the CMS can make is declared, as data, before it is made.

```text
page ──▶ draft ──▶ guard ──▶ approve ──▶ preview ──▶ publish ──▶ ledger ──▶ statistics
         pending   findings  a person    no network   gated       keyed by    own posts,
                   kept                               twice       URL         aggregate
```

This is the design of record. It supersedes the per-site Python publisher bash-365.com ran from `scripts/features/linkedin/`, the `zer0-distribute` prototype on bash-365.com's `claude/linkedin-community-api-desc-so9f8u` branch, the Ruby lane in `rails/lib/zer0_cms/{linkedin,distribution}` with the Rails CMS's `/admin/distribution` and `/admin/channels`, AIEO's WordPress publisher and barodybroject's publish-to-pull-request — all absorbed into the platform's `distribution` app by PLAN G5 ([ADR 0004](adr/0004-one-platform.md)). The Python is held to what the Ruby lane computed: `content/tests/distribution/golden/ruby-lane.json` was recorded on ruby:3.3 over a fixture site and every site in this repository before the Ruby was deleted. What changed on purpose is listed at the end.

## Where it runs

Two queues share one set of rules. The **platform's** is rows — channels of every kind, for any site the platform knows. The **lane's** is files — a content repository that is still files keeps its LinkedIn and X drafts and ledgers in git and publishes from its own CI.

The platform is where accounts are connected and managed. It is registered with LinkedIn and with X as an app of its own (`LINKEDIN_CLIENT_ID` and `LINKEDIN_CLIENT_SECRET`, `X_CLIENT_ID` and `X_CLIENT_SECRET`): a person connects each account through that network's consent screen in the studio, and composes, approves, publishes and reads statistics there, with no repository involved. The lane, and the reusable workflows that run it from CI, are optional automation for a site that keeps its drafts in git; nothing on the platform needs them. A channel whose `ledger_file` names the site's ledger shares it with the lane, so a page either one published is never published by the other.

Both use the same client, the same gates (`distribution/gates.py`), the same ledger format, the same permalinks and the same brand guard, so a draft, a finding and a ledger entry mean the same thing in the extension, the studio and CI.

| Surface | Where | For |
|---|---|---|
| Platform | `content/distribution/` — channels, the queue, the ledger, statistics, `/api/v2/distribution/` ([README](../content/distribution/README.md)) | every channel kind; publishing and statistics run on the worker |
| Studio | the **Distribution** area (`/distribution`: the queue, channels, the ledger, statistics) and **Distribute** in the page editor and a newsroom story's panel (`web/packages/ui/src/distribution/`) | composing, the guard's findings, the exact payload, approving and publishing; connecting an account through LinkedIn's or X's consent screen |
| Platform MCP | `/mcp/`: `distribution.compose` (`propose`) and `distribution.publish` (`publish`), for a client holding the `distribution` agent's token | an agent drafts; it publishes only on the armed path below |
| Published-page consumer | `content.page.published` → a run of the `distribution` agent | a draft for every channel of the page's site set to draft automatically; never a publish |
| Lane library | `content/distribution/linkedin/` and `content/distribution/x/` (the API clients) and `content/distribution/lane/` (the lanes: `site.py`, `pipeline.py`, `cli.py`, `mcp.py` for LinkedIn, and their `x_*.py` subclasses for X — § X) | a site's own files, no database |
| CLI | `python manage.py linkedin COMMAND --site PATH` and `python manage.py x COMMAND --site PATH`, from `content/` | a terminal, and every other lane surface's reference behaviour |
| Reusable workflows | `.github/workflows/zer0-linkedin.yml`, `.github/workflows/zer0-x.yml` | optional: a content repository's CI publishes merged drafts, checks the token and reads statistics (LinkedIn) |
| Lane MCP servers | `python manage.py linkedin mcp --site PATH`, `python manage.py x mcp --site PATH` | Claude Code in a site's checkout: status, sources, queue, preview, draft — publish only when the operator armed it |

## Channels

A channel belongs to a site and has a kind. Everyone who edits the site sees its channels; a person with the `distribution.change_channel` permission sets one up, connects it, changes its credential and arms it. A credential is encrypted with the AI layer's keys (`ai/crypto.py`: `AI_CREDENTIAL_KEYS`, newest first, or one derived from `SECRET_KEY`; `manage.py rotate_ai_credentials` re-encrypts) and is write-only: no response carries it. A channel whose site, author, address, user or repository changes forgets its credential, which was given for the old one. **Check it** asks the target, on the worker, whether the credential works and who it publishes as.

| Kind | Publishing a post | Credential |
|---|---|---|
| `linkedin` | an article (a link card for the page, with its preview image when it has one) or a text update, as the channel's author | its own OAuth token, from **Connect with LinkedIn** |
| `x` | an article (its text, then the page's URL — X draws the card from the page's own card tags) or a text update, as the channel's `account`, after checking the token is that account's | its own OAuth 2.0 token pair, from **Connect with X**, which the platform renews (§ X) |
| `wordpress` | `POST /wp-json/wp/v2/posts` with the page's HTML, a draft unless the channel says `pending`, `private` or `publish`, with the Yoast title and meta description (`yoast_title`, `yoast_metadesc`); the address goes through the research library's SSRF guard and no redirect is followed | the user's application password |
| `github_pr` | the page exported as its Jekyll file (`exporters/jekyll.py`) onto a `distribute/…` branch, and a pull request into the channel's branch | a token that may push and open pull requests |
| `email` | an issue of the site's newsletter carrying the story, sent as the newsroom sends every issue (django-anymail) | none |

A failure is a sentence a person can act on: LinkedIn's error body with every credential scrubbed out; WordPress's 401 (the application password), 403 (the user may not post) and 404 (no REST API at that address); GitHub's 401, 403 (a rate limit, or no write access), 404 and 422 — with the link when a pull request for the post is already open; the newsletter's own refusal.

## Configure a site's lane

A site opts in to the lane with a `distribution.linkedin` block in its `zer0.json`. Settings only: no credential goes in the file, and no key in it can arm a publish.

```jsonc
"distribution": {
  "linkedin": {
    "author": "urn:li:organization:64517157",
    "queue": "drafts/linkedin",
    "ledger": ".github/linkedin-log.json",
    "acceptStatuses": ["pending", "approved"],
    "sources": ["posts"],
    "fallbackImage": "assets/images/office.jpg"
  }
}
```

| Key | Default | Meaning |
|---|---|---|
| `author` | `_config.yml` `linkedin.org_urn` | Who posts: `urn:li:organization:{id}` for a page, `urn:li:person:{id}` for a member's own profile. A platform channel's author may start empty: **Connect with LinkedIn** then asks for the person scopes and fills in the member who connects, from `userinfo` — a member's id is not shown anywhere before |
| `siteUrl` | `_config.yml` `url` + `baseurl` | The origin of the canonical URLs article shares link to and the ledger is keyed by |
| `apiVersion` | `202608` | The `Linkedin-Version` header (YYYYMM). LinkedIn supports a version for twelve months; `status` warns two months before |
| `queue` | `.zer0/drafts/linkedin` | The draft queue folder |
| `ledger` | `.zer0/ledger.json` | The idempotency ledger |
| `acceptStatuses` | `["approved"]` | Which draft statuses may publish. `pending` means "a merge to the default branch is the approval": it counts only where `ZER0_LINKEDIN_MERGED=1` says the run is on that branch, which the reusable workflow sets there and nowhere else. On a laptop and in the MCP server a draft must be `approved` |
| `sources` | every collection | The collections whose pages can be shared |
| `fallbackImage` | none | A card image for a page with no uploadable preview |
| `hashtagLimit` | `3` | Hashtags in a composed first draft |
| `bannedPatternsFile` | none | Extra brand-guard bans, in the extension's `[{name, pattern, flags}]` format |
| `scopes` | by author type (below) | The OAuth scopes a connection asks for |
| `cadence` | none | When a queue run may release a draft: slots, gaps, caps, blackout dates and the page's phase (§ The cadence). None: every accepted draft goes on the run that finds it |
| `requirePreview` | `false` | An article share needs a card image of its own (the draft's `image:`, or the page's preview on disk): one that would carry `fallbackImage` is refused (`source_missing`), so a share never goes out with a generic card |
| `checkLink` | `true` | Before a live send, ask the page the share links to (§ Preview and the gates). `false` for a site that refuses automated requests |

Paths must stay inside the repository; `..` and absolute paths are refused. An unknown key is a warning, so a typo such as `publishAllow` is reported rather than silently believed. A platform LinkedIn channel can name the same ledger file (its `ledger_file` setting, inside the site's checkout), and then reads it before publishing and writes what it published into it, under the same lock and atomic rename the lane uses — so a site moving from its lane to the platform does not post a page twice, once the platform's write is committed: the platform writes the checkout's working tree, never a commit, and the site's own CI reads the committed file (the post's notes say so). The checkout is found only inside the platform's repository or `SITES_DIR`. A named file the platform cannot reach (the site's checkout is not on the machine doing the work), or that the worker cannot write, blocks the channel rather than being skipped.

The environment, all optional, overrides the file for one process: `LINKEDIN_AUTHOR_URN` (or the older `LINKEDIN_ORG_URN`), `LINKEDIN_BASE_URL`, `LINKEDIN_API_VERSION`.

| Variable | Kind | Used for |
|---|---|---|
| `LINKEDIN_ACCESS_TOKEN` | secret | Every LinkedIn call of the lane (never a platform channel's: each uses its own token). Sixty days |
| `LINKEDIN_REFRESH_TOKEN` | secret | Renewing the lane's access token on a 401, when LinkedIn issued one |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | secret | OAuth: connecting an account, refreshing, and introspecting a token's expiry |
| `ZER0_LINKEDIN_PUBLISH` | switch | `1` arms a live LinkedIn publish for this process. The CLI also needs `--live`; the platform also needs a channel a person armed |
| `ZER0_X_PUBLISH`, `ZER0_WORDPRESS_PUBLISH`, `ZER0_GITHUB_PR_PUBLISH`, `ZER0_EMAIL_PUBLISH` | switch | `1` arms the platform's channels of that kind, the same way — and `ZER0_X_PUBLISH` the X lane's live publish (§ X) |
| `ZER0_LINKEDIN_MCP_PUBLISH` | switch | `1` lets the lane MCP server's `linkedin_publish` tool run at all |
| `ZER0_LINKEDIN_MERGED` | switch | `1` says this run publishes the default branch, so a `pending` draft there was merged; the reusable workflow sets it for a run on the default branch and nowhere else |
| `ZER0_CMS_LINKEDIN_REDIRECT_URI` | setting | The platform's OAuth callback, when it is not this request's origin plus `/api/v2/distribution/oauth/linkedin/` |

`manage.py linkedin status` reads the block the way the lane does and fails on its errors, so the reusable workflow's `status` command gates a site's settings. `zer0 doctor`'s `distribution` check is `content/sites/doctor.py`'s — the block's errors and warnings, an unreadable ledger, a leftover per-site publisher, with the environment ignored so the report is the same on every machine; it needs no Django, so the reusable `zer0-doctor.yml` runs it.

## The draft queue

The lane's queue is markdown files at the top level of the queue folder; `examples/` and a front-matter-less `README.md` are never drafts. The dialect is the one the VS Code extension and the Python publisher already share, so a queue any of them wrote reads the same here.

| Key | Values | Meaning |
|---|---|---|
| `type` | `article` (default), `update` (`text` is accepted) | A link card for a page, or text alone |
| `status` | `pending` (default), `approved`, `published` | Where it is in the lifecycle |
| `source` | a repository path, or `section/YYYY-MM-DD-slug` | The page an article shares |
| `title`, `description`, `link` | text | An article's own card, for a link that is not a page of this site; ignored when `source` names a page |
| `image` | a repository path | The card image, ahead of the page's preview and the fallback: how a share of a page on another site (`link:`) carries that page's own image |
| `no_thumbnail` | `true` | Post the card without an image |
| `publish_at` | `2026-11-10 09:00`, an ISO time with an offset, or a date | Not before this time: a queue run leaves the draft waiting until then, read in the cadence's zone (UTC without one) when it names none. A person's publish of the named draft is not held |
| `linkedin_urn` | set on publish | The post it became |

The body is the commentary that publishes. `manage.py linkedin draft SOURCE` (or `linkedin_draft` over MCP) writes a new draft with a deterministic first commentary — the page's sub-title, excerpt or description as the hook, never its title, then up to three hashtags from its tags — for a person or an agent working to a skill to rewrite. A new draft is always `pending`; a collision becomes `-2`, never an overwrite. Approval is `pending` → `approved`, by `manage.py linkedin approve` or a person editing the line and merging it, and is refused while the brand guard has an error. There is no approval tool over MCP: approval is a person's act. Status changes are line surgery, so approving is a one-line diff.

The platform's queue is `DistributionPost` rows: a page, or a newsroom story, going to one channel. **Compose** (the studio's **Distribute**, `distribution.compose`, or the published-page consumer) seeds the same first commentary, computes the post's canonical URL and runs the brand guard, whose findings stay on the post. A post is a draft when it is made, whoever made it. **Approve** is a person who may publish the page, refused while the guard has an error; it is of the exact text (`approved_digest`, which the gates compare), so changing an approved or failed post's text sends it back to draft. **Publish** answers `202` and the worker sends it; every attempt ends published or failed — an error nobody expected fails it as one that may have published, and an attempt whose worker died is settled by the next request or the beat's sweep (`distribution-settle`) — and an email post is published once the newsroom has sent its issue.

## Preview and the gates

A preview renders the exact request — the payload with its commentary escaped as LinkedIn will read it, the card image it would upload, the brand guard's findings and every blocker — with no network call and no write. Publishing re-reads the draft (the lane, from disk; the platform, the row, again on the worker), rebuilds that preview and refuses on any blocker, in this order:

| Blocker | When | Lifted by |
|---|---|---|
| `config_error` | the site's settings have an error; a channel is not connected or misses a setting its kind needs | fixing `zer0.json`, or the channel |
| `no_author` | no author, or not a person or organization URN | the `author` setting |
| `source_missing` | the `source` names no page, the page is not live or has no URL or no description, or an article has neither source nor link; an email's story is not published | the draft, the page or the story |
| `ledger_unreadable` | the ledger exists but is not JSON; a platform channel's site ledger file cannot be reached from the machine doing the work, or written by the worker | repairing the ledger, or running where the site's checkout is — never by reading it as empty |
| `guard_error` | a banned phrase, or commentary over 3,000 characters once escaped | editing the text, or `force` by a person who read it |
| `already_published` | the ledger has this draft's key | `force`, deliberately posting again |
| `publish_unconfirmed` | an earlier attempt ended in a 5xx, a dropped connection or a success with no post id, so the post may exist | **Record** (`manage.py linkedin record DRAFT URN`) once a person finds the post, or `force` once they have checked it did not post |
| `status_not_accepted` | the draft is not approved (the lane: not one of `acceptStatuses`, with `pending` only in a merged run) | approval — never `force` |
| `publish_disabled` | `ZER0_LINKEDIN_PUBLISH=1` (or the kind's switch) is not set; on the platform, also the channel is not armed | the operator's environment and a channel manager — never a file, a flag or `force` |
| `no_credential` | no access token and no refresh token | the environment, or connecting the channel |

Without `--live`, `manage.py linkedin publish` is a rehearsal: it reports the same blockers and exits non-zero when any blocker other than `status_not_accepted`, `publish_disabled` and `no_credential` applies — those three say a draft is not cleared to go yet, not that anything is wrong with it — so a dry run in CI fails on a guard error, a missing page or an unconfirmed attempt. `preview` exits the same way. `--force` needs a draft id; it never applies to a whole queue. On the platform, publishing a post with a blocker answers `409` with every blocker.

**The page is up before the share goes.** A preview makes no network call, so it cannot see a page that is not published yet — a share merged before its article, or a `link:` to another site whose pull request is still open. A live send of an article therefore asks the page first (`checkLink`, on by default): one GET of the canonical URL or `link`, following redirects, the lane's only request outside LinkedIn's and X's declared calls. A 2xx or 3xx answer is up. A 404 or 410 is not live yet; a 403, a 5xx or no answer does not confirm it. Either way nothing is sent: a queue run leaves the draft `waiting`, so the next run takes it once the page answers, and a person's publish of the named draft is refused with the answer. The platform's channels check that the page is live in the platform instead (`source_missing`).

**The card image** is the draft's own `image:`, else the page's preview on disk, else the site's `fallbackImage`, else none; the preview notes which. With `requirePreview` a share that would carry the fallback or no image is refused, so every post goes out with its own picture.

A write that ends in a 5xx, a dropped connection or a success with no post id may have posted, so the doubt is written to the ledger before anything else happens — an `unconfirmed` entry with no URN — and every later attempt, on every surface, refuses that key until a person has looked. One case is finished rather than refused: a lane draft whose key is already in the ledger, with nothing else in the way, is the tail of a run that died between the ledger write and the draft write, so a live run marks the draft published and posts nothing.

The brand guard is `content/suggestions/guard.py`, a rule-for-rule port of the extension's (`src/core/governance/guard.ts`): thirteen hard bans, nine filler warnings, the 140-character fold and the 3,000-character limit, with the same rule names, messages and order, so a finding reads the same in the editor, the studio and CI. The platform adds the site's active brand rules.

## The cadence: timed, phased release

Approval says *whether* a post goes; a cadence says *when* (issue #89). Without one, a lane's queue run publishes every accepted draft it finds, which is how a merge used to post at once. With one, the drafts that are approved line up and go out one slot at a time. The rules are `content/distribution/cadence.py`, pure and shared by every surface, as the gates are:

```jsonc
"distribution": { "linkedin": { "cadence": {
  "timezone": "America/Denver",          // an IANA zone; default UTC
  "slots": ["tue 09:00", "thu 09:00"],   // weekly release times: mon … sun, daily, weekdays, weekends, mon-fri, mon,wed
  "minGap": "48h",                       // never closer than this to another post of the lane (default 0)
  "perDay": 1,                           // at most this many a local day (default 1)
  "perWeek": 2,                          // at most this many a local ISO week (default: no limit)
  "blackout": ["2026-12-24..2027-01-01"],  // local dates, or inclusive ranges, with no release
  "afterPage": "1h",                     // the phase: a share waits this long after its page landed (default 0)
  "grace": "6h"                          // how late a run may still take a slot it missed (default 6h)
} } }
```

Durations are whole minutes, hours and days, alone or together (`90m`, `48h`, `2d`, `1d12h`, `0`). Every key is checked: an unknown key or a value that cannot be read is a `config_error`, which blocks every publish rather than releasing on a rule nobody meant, and `zer0 doctor` reports it. The X lane takes the same block under `distribution.x.cadence`, so a site can phase its channels: the page goes live, LinkedIn shares it an hour later, X a day later, each in its own slots.

**What a queue run does.** A queue run is `publish` with no draft named, which is what CI runs. It releases at most one draft, and only while a slot is open. A slot is open when its time has passed by no more than `grace`, nothing has gone out since it opened (the ledger's `posted_at`, and any attempt that may have posted), and `minGap`, `perDay`, `perWeek` and the blackout dates hold at the moment of release. That last check means a run that comes back after days away takes one slot, never the backlog at once. The draft it takes is the first that is ready: drafts pinned with `publish_at:` whose time has come, earliest first, then the rest in queue order (the queue folder's, which dated draft ids keep chronological). A draft is ready once its `publish_at:` has passed and, for an article, once its page has been on the branch for `afterPage`. A draft a gate refuses gives the slot to the next ready draft; a failed send ends the run, since it may have posted. Every other draft comes back `waiting`, with the time it will go, and a waiting draft does not fail the run.

**When a page landed.** It is the oldest first-parent commit on the run's branch that touched the page: its merge commit, or its squash, not the commit on the branch it came from. So a page and its share merged in one pull request go in order, page first. A checkout with no git history falls back to the page's `date`. The workflow checks out with full history.

**What a person does is never held.** `publish DRAFT` names a draft, whether from a terminal or a dispatched workflow with `draft:` set. That publishes now, through every gate as before, whatever the cadence and its pin say. Only a queue run waits.

**Seeing the calendar.** `manage.py linkedin calendar` (`--json`, and `x calendar`, and the MCP tools `linkedin_calendar` and `x_calendar`) lists every accepted, unpublished draft with the time a queue run will give it: the slot open now if there is one, then the slots to come, in the order above. A draft whose `publish_at:` cannot be read is listed with the problem and makes the command exit 1. A draft no slot within a year can take (every one dark or full) says so.

**On the platform.** A channel's `cadence` takes the same settings (the studio's channel panel, or `PATCH /api/v2/distribution/channels/<id>/` with `cadence`; an unreadable one is refused with every problem named, and `{}` clears it). On a channel with a cadence, approving a post queues it: `scheduled_for` is the first free slot after its page's phase (`afterPage` after the page's first publish, or after the time its approved schedule puts it live), counting what the channel published (its ledger rows and its site ledger file, one share counted once), what it is sending and what is already scheduled. **Schedule** puts any approved post in the queue, in the next slot or at a time a person chose, which the cadence's rules never move (`POST …/posts/<id>/schedule/` with `at` or without); **Unschedule** takes it out, still approved. Beat's `distribution-release` runs each minute and releases what is due, oldest first, as the publish of the person who scheduled it, so every gate runs again and the worker sends it as before. At release:

- a slot the rules no longer allow is moved to the next free one, never sent in a burst. That happens to a backlog after the worker was away, or when something was published by hand since.
- a post whose page is not live yet is held to the next slot (fifteen minutes on, for a chosen time), and the hold is noted once.
- a gate's refusal (the channel disarmed, the deployment's switch off, a guard error, the ledger), or a scheduler who may no longer publish the page, takes the post off the schedule with the reason in its error, for a person.

Changing the text of a scheduled post sends it back to draft and off the schedule; rejecting it does too, and **Publish now** sends it at once. The channel's **release calendar** (`GET …/channels/<id>/calendar/`, and its panel in the studio) lists what is scheduled, the next free slots and what went lately; the queue's **When** column and its **Scheduled only** filter (`?scheduled=true`) show the same from the posts' side. The extension's bridge asks before a schedule and before an approval, since on a channel with a cadence an approval reaches people later with no further request.

**Running it on a timer.** A cadence only releases what a run finds, so a site that uses one runs its publish on a schedule as well as on the merge (§ CI). An hourly run off the hour, with the default six hours of `grace`, absorbs GitHub's late scheduled starts.

## What LinkedIn sees

`manage.py linkedin plan` prints every call the client can make (`distribution/linkedin/plan.py`). `Client.request` takes a call id from that plan, never a URL, and refuses anything else before a socket opens; the one URL a caller supplies, the image upload slot LinkedIn returns, must be https on linkedin.com.

| Call | Endpoint | Scopes (any of) | Returns |
|---|---|---|---|
| `token` | `POST www.linkedin.com/oauth/v2/accessToken` | app credentials | this app's own access token for the member who consented |
| `introspect` | `POST www.linkedin.com/oauth/v2/introspectToken` | app credentials | the status, expiry and scopes of this app's own token |
| `userinfo` | `GET /v2/userinfo` | `openid profile` | the authenticated member's own id and name |
| `organization_acls` | `GET /rest/organizationAcls?q=roleAssignee` | `r_organization_admin`, `rw_organization_admin` | the authenticated member's own page roles |
| `organization` | `GET /rest/organizations/{id}` | same | the own public name of a page the member administers |
| `posts_create` | `POST /rest/posts` | `w_organization_social`, `w_member_social` | the id of the author's own new post |
| `posts_get` | `GET /rest/posts/{urn}` | `r_organization_social`, `rw_organization_admin`, `r_member_social` | the author's own post, as published |
| `posts_by_author` | `GET /rest/posts?q=author` | same | the configured author's own recent posts |
| `posts_delete` | `DELETE /rest/posts/{urn}` | `w_organization_social`, `w_member_social` | nothing; it removes the author's own post |
| `images_initialize` | `POST /rest/images?action=initializeUpload` | same | an upload slot for the author's own image |
| `images_upload` | `PUT` the slot | same | nothing; it stores the author's own image |
| `images_get` | `GET /rest/images/{urn}` | `w_organization_social` | the processing status of the author's own image |
| `organization_share_statistics` | `GET /rest/organizationalEntityShareStatistics` | `r_organization_admin`, `rw_organization_admin` | aggregate counts for the page's own posts |
| `member_post_statistics` | `GET /rest/memberCreatorPostAnalytics?q=entity` | `r_member_postAnalytics` | aggregate counts for the member's own post |

Two tests keep the list honest: every entry's `returns` sentence must contain the word "own", and no declared path may reach connections, people, followers, network sizes, social actions, likes, reactions, comments, messages, conversations or search. Adding a call that reaches another person's data therefore fails the build instead of shipping. Every REST call carries `Linkedin-Version` and `X-Restli-Protocol-Version: 2.0.0`; URNs are percent-encoded and Rest.li `List(...)` and `(key:value)` records are built by `restli.py`. The client speaks httpx; its tests are recordings (respx), never LinkedIn.

Reads are retried on 429, 5xx and a dropped connection, honouring `Retry-After`. Writes are retried on 429 only: a 5xx or a dropped socket after `POST /rest/posts` may mean the post exists, and retrying it is how a page publishes the same thing twice. An error message is built from LinkedIn's error body, never from the request, and any credential the client holds is scrubbed out of it.

Commentary is escaped to LinkedIn's `little` text format before it is sent. All fifteen reserved characters — `| { } @ [ ] ( ) < > # \ * _ ~` — are backslash-escaped, except a hashtag (`#` and letters or digits, not glued to a word) and a mention written as `@[Name](urn:li:person:…)` or `…(urn:li:organization:…)`. Sent raw, LinkedIn misreads the text around an unescaped reserved character; the familiar symptom is a post cut off at its first parenthesis.

## Accounts and tokens

Each account is authorized by its owner through LinkedIn's three-legged OAuth: a member consents for their own profile, a page administrator for the pages they administer. Nothing can mint a token for anyone who did not consent. The scopes requested by default are the least each author type needs:

| Author | Scopes |
|---|---|
| organization | `w_organization_social r_organization_social rw_organization_admin` |
| person, and a platform channel with no author yet | `openid profile w_member_social r_member_postAnalytics` |

Both ways to connect send a fresh `state` and a PKCE challenge (S256). PKCE has never been tried against a live LinkedIn, which documents it for native apps only, on an endpoint of their own; on the web flow LinkedIn may well ignore it (a server ignores a parameter it does not know, RFC 6749 § 3.1), so `state` is the guard relied on. In the studio, a LinkedIn channel's **Connect with LinkedIn** is a POST, so no other site can start a connection; the person's session keeps the state and the verifier, the callback (`/api/v2/distribution/oauth/linkedin/`) is accepted only when its `state` matches one this session started less than ten minutes ago and is consumed on first use, and the worker exchanges the code with the verifier and stores the token encrypted on the channel. A channel's token is used for its site, and only its own: a channel nobody connected has none, so it is not checked, read for statistics or published to. In a terminal, `manage.py linkedin connect` prints the consent URL, waits for LinkedIn's redirect on `http://127.0.0.1:8765/callback` (add it to the app's authorized redirect URLs; `--redirect-uri` may name another loopback port, which is then the one it listens on), checks `state`, exchanges the code and — only with `--write-env FILE` for a file git ignores, or `--print-token` — stores or shows the token for a CI secret.

Access tokens last sixty days. LinkedIn issues refresh tokens (365 days) only to apps it has enabled for programmatic refresh; with one, a 401 refreshes once and repeats the call — safe, because a 401 means LinkedIn did nothing — and the platform keeps the new token on the channel. Without one, the owner re-runs consent, which LinkedIn skips while they are signed in and the old token is alive. `manage.py linkedin status --check` and a channel's **Check it** ask LinkedIn: with the app credentials they introspect the token (active, scopes, expiry); without them they only prove the token works with a cheap read, so its expiry is not known. A 403 on that read is reported as "authenticates but may not read", not as a dead token.

## The ledger

What was published, keyed by an article's canonical URL, or `draft:<…>` for a text update, which has no URL of its own (`draft:<queue path>` in the lane, `draft:<post id>` on the platform). Whichever surface publishes a key first writes it; every other surface looks it up and skips. The platform keeps its ledger as rows and gives each channel's as the file every lane reads (**Download**); **Import** reads one in — the extension's, a site's CI's — so what another lane published is never published again from the platform, keeping the keys it does not model. That coordination depends on agreement about the file, so:

- an entry carries the post URN under both `linkedin_urn` (the name live ledgers already hold) and `urn` (the name the extension reads), with `posted_at`, `type`, `target: "linkedin"`, `author`, `source_file` and, when a card image was uploaded, `image_urn`; a reader accepts either URN name;
- the file is written as Python's `json.dump(indent=2, sort_keys=True)` plus a newline, byte for byte (`distribution/ledger.py`), pinned by a golden test, so no surface churns it;
- a write is a read-modify-write under an exclusive lock outside the repository, then an atomic rename, and every key it does not own — metadata other lanes wrote, of any shape — survives it;
- an attempt the target did not confirm is an entry with `state: "unconfirmed"`, `attempted_at` and `error` but no URN: no reader counts it as published, and every surface refuses that key until a person records the post or forces past it;
- an unreadable ledger is never read as "nothing published" and never rewritten.

The canonical URL is the one Jekyll 4.4 gives the page: a front-matter `permalink`, then a matching `defaults:` scope, then the collection's `permalink`, then the site's style, with Jekyll's placeholders and slugify rules (`distribution/permalink.py`). The platform computes it the same way for a page of a Jekyll site, from the site checkout's `_config.yml` — read inside its repository or `SITES_DIR`, or the post is refused (409): a URL guessed from the few keys the importer keeps would be one Jekyll never builds, and no lane's ledger would hold it — and uses Wagtail's URL for any other page. On bash-365.com that reproduces every URL the Python publisher keyed its ledger by, and gets right the one it got wrong: a post whose front matter moves it elsewhere.

## Statistics

The platform reads aggregate counts for each LinkedIn channel's own published posts once a day (`distribution-statistics` on beat, 04:23 UTC) or when a person asks (**Read statistics now**), into one `Statistic` row per post a day; the studio's ledger shows each entry's latest counts. The lane's `manage.py linkedin stats --write` (the workflow's `stats` command) reads them for the ledger's posts by the configured author and merges them into `.cms/distribution/performance.json`:

```json
{
  "generated_at": "2026-09-15T12:00:00Z",
  "note": "Aggregate statistics for the author's own content. No per-reader data.",
  "content": {
    "pages/_posts/tech/2026-07-06-mcp-for-the-back-office.md": {
      "impressions": 90, "clicks": 4, "reactions": 5, "comments": 1, "shares": 0, "engagements": 6
    }
  }
}
```

Both read `organizationalEntityShareStatistics` in batches of twenty for a page and `memberCreatorPostAnalytics` one metric per call for a member. `performance.json` is the file the VS Code extension's `writePerformance` writes and its catering worklist ranks subjects from, so the loop closes in the editor where writing happens. A post LinkedIn leaves out of a page-statistics answer had no impressions and no actions, and is recorded as zeros, as LinkedIn's documentation says to read it; only posts that were asked about are filled in. A refresh merges over the file, so this week's numbers update this week's posts and leave the history alone. Nothing about who engaged is requested, stored or derivable.

## Agents

`distribution.compose` drafts a post of a page for a channel of its site, as the agent user, under the narrower of the agent's and the page's policy (`suggest` or more) and the agent's change right on the page; a person approves the draft. `distribution.publish` publishes a post a person approved, to an armed channel of a kind the deployment armed — and is refused until the page's and the agent's policy is `auto`, the agent's definition is live and its group holds the page's publish right, none of which is given: the armed path is off until each is set on purpose. When a page goes live, the `content.page.published` consumer starts one run of the GitOps `distribution` agent (`content/agents/definitions/distribution.yaml`), which drafts a post for every channel of the page's site with **auto draft** on; a page at policy `off` gets none.

## CI: the reusable workflow

The workflow is optional: a site whose channels live on the platform publishes from the studio and needs none. A content repository that wants its merged drafts published from its own CI calls `zer0-linkedin.yml` without vendoring anything:

```yaml
name: LinkedIn publish
on:
  push:
    branches: [main]
    paths: ["drafts/linkedin/**"]
  schedule:
    - cron: "17 * * * *" # with a cadence: each hour, a run takes the slot that is open (§ The cadence)
  workflow_dispatch:
    inputs:
      draft: { description: "One draft id (empty: the queue)", type: string, default: "" }
      live: { description: "Send to LinkedIn", type: boolean, default: false }
permissions:
  contents: write
jobs:
  publish:
    uses: bamr87/zer0-CMS/.github/workflows/zer0-linkedin.yml@main
    with:
      command: publish
      draft: ${{ inputs.draft || '' }}
      live: ${{ github.event_name != 'workflow_dispatch' || inputs.live == true }}
    secrets: inherit
```

A push and a scheduled run publish live; a dispatch rehearses unless `live` is ticked. Without a cadence, the schedule adds nothing, since the push already published every merged draft. With one, the push releases a draft only if a slot happens to be open, and the scheduled runs release the rest, one slot at a time.

| Input | Default | Meaning |
|---|---|---|
| `command` | `publish` | `publish`, `status` (fails on a settings error, and when the token is dead or within `warn-days` of expiry) or `stats` |
| `site-path` | `.` | The Jekyll root inside the caller; absolute or climbing paths fail the job |
| `live` | `false` | `publish` only: send, rather than rehearse |
| `draft` | empty | `publish` only: one draft id instead of the queue |
| `warn-days` | `7` | `status` only |
| `zer0-cms-ref` | `main` | The zer0-CMS ref to run |

It checks out the caller — at the tip of the branch the run is on, not the commit that triggered it, so a run queued behind another sees the ledger that run committed — and zer0-CMS side by side, installs the platform's requirements on Python 3.13 and runs `python manage.py linkedin`, which opens no database. It sets `ZER0_LINKEDIN_MERGED=1` when that branch is the repository's default branch and `ZER0_LINKEDIN_PUBLISH=1` for the one step of a live publish. After a live publish or a stats run it commits the ledger, the queue and the performance file back with `[skip ci]` (a `GITHUB_TOKEN` push starts no workflow, so it cannot loop); if the push still conflicts after a rebase, the job fails and the files are in the `zer0-linkedin-results` artifact with the CLI's output, which also goes to the job summary. Concurrency is per repository and command, so a token check never displaces a queued publish. The workflow declares no permissions, so the caller's grant applies: `contents: write` for publish and stats, `contents: read` for status. A rehearsal needs no credential; every other run without `LINKEDIN_ACCESS_TOKEN` or a refresh token skips with a notice.

## The lane's MCP server

`python manage.py linkedin mcp --site PATH` speaks newline-delimited JSON-RPC on stdio. Tools: `linkedin_status`, `linkedin_plan`, `linkedin_sources`, `linkedin_queue`, `linkedin_calendar`, `linkedin_preview`, `linkedin_draft`, `linkedin_posts` and `linkedin_publish`. The last needs `ZER0_LINKEDIN_MCP_PUBLISH=1` and `ZER0_LINKEDIN_PUBLISH=1` in the server's environment plus `confirm: true` on the call, and then runs the same `Pipeline.publish`. The server never runs with `ZER0_LINKEDIN_MERGED`, so a draft that is not `approved` is refused, whatever the site's `acceptStatuses`. Every call re-reads the configuration and the queue from disk. A site wires it into Claude Code through its `.mcp.json`, with a Python that has the platform's requirements installed:

```json
{ "mcpServers": { "zer0-linkedin": { "type": "stdio", "command": "python",
  "args": ["${ZER0_CMS_DIR:-../zer0-CMS}/content/manage.py", "linkedin", "mcp", "--site", "."] } } }
```

## What changed from the Python publisher, on purpose

- **Commentary is escaped.** The Python lane sent raw text, which LinkedIn's `little` format misreads at the first reserved character.
- **A write is not retried after a 5xx.** The Python lane retried every request, including `POST /rest/posts`.
- **Canonical URLs follow Jekyll.** The Python lane built `/posts/Y/M/D/slug/` from the filename, which is wrong for a post with its own `permalink`.
- **An unreadable ledger blocks publishing.** The Python lane read it as empty.
- **Text updates are ledgered**, under `draft:<…>`, so a re-run cannot post one twice.
- **An unconfirmed create blocks the next run.** A 5xx, a dropped connection or a success with no post id is written down as `unconfirmed`, because the post may exist.
- **A queued CI run publishes from the branch tip**, so it sees what the run before it recorded, and a `pending` draft publishes only in a run on the default branch.
- **A share is a draft, always.** The Python workflow's dispatch could post a free-text update or any article by reference without a queue file; the reusable workflow publishes only drafts, so every post has a file a person approved.
- **Page roles are verified, tokens introspected**, rather than inferred from whether a post-listing call happens to succeed.

## What changed from the Ruby lane and the Rails CMS, on purpose

- **One app, four kinds.** LinkedIn, WordPress, a GitHub pull request and a newsletter are channels of one model with one queue, one gate order and one ledger, instead of a LinkedIn-only queue in Rails, AIEO's WordPress publisher and barodybroject's pull-request button.
- **Double arming on the platform.** A channel a person armed and the deployment's switch for its kind, where the Rails CMS had the environment's switch and a ticked confirmation.
- **Connecting sends PKCE as well as `state`** (PKCE unverified against a live LinkedIn), and the code is exchanged on the worker, not in the request.
- **A credential is encrypted with the AI layer's rotatable keys** (`ai/crypto.py`) rather than Active Record encryption keyed on `secret_key_base`.
- **The gates run twice on the platform**: when publishing is asked for (a `409` with every blocker) and again on the worker that sends it.

## X

The X lane is the LinkedIn lane's twin, and inherits from it rather than copying it: `lane/x_site.py`, `x_pipeline.py`, `x_cli.py` and `x_mcp.py` subclass the LinkedIn modules and change only what X changes. The sources, composing, the draft queue and its dialect, approval, the gates after the target's own, the publish flow, the ledger file's format and recording a post by hand are the same code. A platform X channel goes through the same queue, gates and worker as every other kind, and is connected in the studio (§ Connecting an X account in the studio); the lane and `zer0-x.yml` are optional automation beside it.

### Connecting an X account in the studio

The platform is the X app. In the X developer console (console.x.com → Apps → the app → Keys & Tokens → OAuth 2.0 Keys → **Set up**), the app's user authentication settings are "Read and write" permission, the type "Web App, Automated App or Bot" (a confidential client) and the callback `https://<the platform>/api/v2/distribution/oauth/x/`, matched exactly, trailing slash included. A platform on this machine uses `http://127.0.0.1:<port>/…`, not `localhost`, which X's docs say not to use. X shows the OAuth 2.0 Client ID and Client Secret once, after the save: they are the platform's `X_CLIENT_ID` and `X_CLIENT_SECRET`, on the content service and the worker.

| Variable | Kind | Used for |
|---|---|---|
| `X_CLIENT_ID`, `X_CLIENT_SECRET` | secret | The platform's X app: connecting an account and renewing its token. Never the lane's `X_API_KEY` and `X_API_SECRET`, which are OAuth 1.0a's |
| `ZER0_CMS_X_REDIRECT_URI` | setting | The platform's X callback, when it is not this request's origin plus `/api/v2/distribution/oauth/x/` |

**Connect with X** on a channel is a POST, so no other site can start a connection. It answers with X's consent URL (`https://x.com/i/oauth2/authorize`) carrying a fresh `state`, a PKCE challenge (S256) and the scopes `tweet.read tweet.write users.read offline.access` — the least a channel needs to post, read its own posts and their counts back, learn which account it is, and renew its token. The person's session keeps the state, the verifier and the channel's kind; the callback accepts a state this session started for X less than ten minutes ago, once. X's code lives thirty seconds, so the worker exchanges it as soon as the callback commits: the token endpoint (`POST /2/oauth2/token`) gets the code and the verifier, with the app's id and secret as HTTP Basic, never in a URL or a form. The worker then asks X which account the token is (`GET /2/users/me`). A channel that names its `account` keeps a token for that account only; one that names none takes the account its owner approved as, unless another channel of the site already posts as it. A token the channel does not keep is revoked (`POST /2/oauth2/revoke`), and the channel says why.

The access token lasts two hours. The platform renews it two minutes before it lapses, or once on a 401 — safe, because a 401 means X did nothing — and keeps the new pair at once: X spends a refresh token when it is used and answers with a new one. The renewal holds the channel's row, so two workers that find the token lapsed at once renew it once; the second takes the pair the first kept. A renewal X refuses (the owner revoked the app, or the refresh token is spent) changes nothing kept and says to connect the channel again. Revoking an access token ends its whole grant at X, refresh token included, so a 401 after a revocation is answered by a refused renewal, never a second one. **Disconnect** forgets the pair here and has the worker give the grant back to X (`POST /2/oauth2/revoke` with the refresh token), reading it from the credential as it was sealed, so the token never crosses the queue in the clear; a revocation X refuses or cannot take is logged and the channel is disconnected all the same. The owner can also revoke the app in X's settings ("Connected apps").

### Configure a site's X lane

```jsonc
"distribution": {
  "x": {
    "account": "bamr87",
    "queue": "drafts/x",
    "ledger": ".github/x-log.json",
    "acceptStatuses": ["pending", "approved"],
    "sources": ["posts"]
  }
}
```

| Key | Default | Meaning |
|---|---|---|
| `account` | none | The X handle the lane posts as (`@` optional). X posts as whoever the token is, so a publish first reads the token's account (`GET /2/users/me`) and refuses before sending anything when it is another |
| `siteUrl` | `_config.yml` `url` + `baseurl` | The origin of the canonical URLs posts link to and the ledger is keyed by |
| `queue` | `.zer0/drafts/x` | The draft queue folder, in the LinkedIn queue's dialect (the post's id goes under `post_id`) |
| `ledger` | `.zer0/x-ledger.json` | The idempotency ledger. X's own file: it is keyed by canonical URL, and a page shared on LinkedIn has still to go to X |
| `acceptStatuses` | `["approved"]` | As LinkedIn's, with `ZER0_X_MERGED=1` saying a run is on the default branch |
| `sources` | every collection | The collections whose pages can be shared |
| `hashtagLimit` | `2` | Hashtags in a composed first draft |
| `bannedPatternsFile` | none | Extra brand-guard bans |
| `cadence` | none | X's own release slots, gaps and page phase, as LinkedIn's (§ The cadence), counted against X's ledger |
| `checkLink` | `true` | Ask the page a post links to before a live send, as LinkedIn's lane does |

| Variable | Kind | Used for |
|---|---|---|
| `X_API_KEY`, `X_API_SECRET` | secret | The app's key and secret (the X developer console's "API Key and Secret") |
| `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` | secret | The account's OAuth 1.0a token and secret — the console's "Access Token and Secret" for the app owner's own account, or `manage.py x connect` for any account whose owner approves |
| `ZER0_X_PUBLISH` | switch | `1` arms a live X publish for this process; the CLI also needs `--live` |
| `ZER0_X_MCP_PUBLISH` | switch | `1` lets the lane MCP server's `x_publish` tool run at all |
| `ZER0_X_MERGED` | switch | `1` says this run publishes the default branch, so a `pending` draft there was merged |

`manage.py x` takes `status [--check]`, `plan`, `sources`, `queue`, `calendar`, `draft`, `approve`, `preview`, `publish [--live] [--force]`, `record DRAFT ID`, `posts`, `verify ID`, `connect` and `mcp`, with the LinkedIn lane's exit codes. `zer0 doctor`'s `distribution` check reads the `distribution.x` block beside `distribution.linkedin`.

### What a post is, and its length

A post is `{"text": …}`. An article is its commentary with the page's canonical URL on a line of its own after it (unless the commentary already carries it); X draws the link's card from the page's own `twitter:card` and Open Graph tags, so nothing is uploaded and no card title or description travels with it. A text update is the text alone, ledgered under `draft:<queue path>`. The brand guard runs on the commentary, and X's own limit on the whole post: 280 characters as X counts them (`x/plan.py` `weighted_length`, twitter-text's rules — a link counts 23 whatever its length, a character outside the Latin, Greek, Cyrillic and common punctuation ranges counts 2). An emoji sequence is counted per code point and a bare domain at no less than 23, so the count may refuse a post X would take, never take one X refuses. A post over the limit is a `guard_error`.

### What X sees

`manage.py x plan` prints every call the client can make (`distribution/x/plan.py`); `Client.request` takes a call id from it, never a URL, and every request goes to `api.x.com` over https.

| Call | Endpoint | Returns |
|---|---|---|
| `request_token` | `POST /oauth/request_token` | a temporary token for this app's own connection request |
| `access_token` | `POST /oauth/access_token` | this app's own access token for the account whose owner authorized it |
| `oauth2_token` | `POST /2/oauth2/token` | this app's own OAuth 2.0 token for the account whose owner authorized it |
| `oauth2_revoke` | `POST /2/oauth2/revoke` | nothing but this app's own token, revoked |
| `me` | `GET /2/users/me` | the authenticated account's own id, name and handle |
| `posts_create` | `POST /2/tweets` | the id of the account's own new post |
| `posts_lookup` | `GET /2/tweets?ids=…` | the account's own posts, as published, with their aggregate counts (posts by any other author are dropped) |
| `posts_by_account` | `GET /2/users/{id}/tweets` | the account's own recent posts |

The same two tests as LinkedIn's keep the list honest: every `returns` sentence contains "own", and no declared path reaches followers, likes, bookmarks, mentions, messages, lists, spaces or search. The lane signs every request with OAuth 1.0a (HMAC-SHA1, oauthlib's signer), so a secret signs a request and is never sent; a platform channel sends its OAuth 2.0 token as a bearer, and the token endpoint authenticates the platform's app with HTTP Basic. Every credential is scrubbed out of an error. Retries are LinkedIn's: a read on 429, 5xx and a dropped connection (honouring `retry-after` and `x-rate-limit-reset`), a write and a token call only on 429 — a renewal that reached X has spent its refresh token. A create that ends in a 5xx, a dropped connection or a success with no id is ledgered `unconfirmed`, and `manage.py x record DRAFT ID` (the digits of `x.com/…/status/ID`) or the studio's **Record** clears it.

### Tokens and cost

The lane uses OAuth 1.0a, whose tokens do not expire until their owner revokes them or the app's permission changes, which is what a repository secret needs: an OAuth 2.0 token lasts two hours and each renewal spends the refresh token it used, which only a store the renewal can write back to — the platform's channel — can follow. `status --check` and a channel's **Check it** ask which account the token posts as and fail when it is not the configured one; **Check it** renews a lapsed token first. `manage.py x connect` runs OAuth 1.0a's three legs with a PIN: it prints the authorize URL, the account's owner approves while signed in as that account, types the PIN X shows, and the lane stores the token pair only with `--write-env FILE` (a file git ignores) or shows it with `--print-token`. The app's permission must be "Read and write". The lane's app and the platform's may be one X app (it has both OAuth 1.0a keys and an OAuth 2.0 client) or two; either way X bills the app.

X's API is pay-per-use, billed per request against credits bought ahead. Since 2026-04-20 a post carrying a URL is billed well above one without (X's developer announcement put them at $0.20 and $0.015 at the time; the console shows today's rates), and reads are billed too. Every article share carries its URL, so it is the dearer kind of post; each publish also makes one billed read (the account check), as does each daily statistics read on the platform plus one per post read. A failed request is not billed.

### Statistics

The platform reads X's public counts for each X channel's own ledgered posts once a day with LinkedIn's (`distribution-statistics`) or when a person asks: impressions, likes as reactions, replies as comments, reposts and quotes as shares. Link clicks are not public metrics, so `clicks` stays at zero. The lane has no `stats` command: `performance.json` is keyed by page and holds LinkedIn's counts, and X's would overwrite them.

## Not built, and not to be described as built

Reading or replying to comments, reactions or mentions; anything about individual members (profiles, connections, followers, who engaged); an agent tool to schedule a post, and re-slotting the posts already scheduled when a channel's cadence changes (the release checks the rules again instead); video, document, poll or multi-image posts; threads, replies and media on X; X statistics in the lane; statistics for WordPress, a pull request or a newsletter; and a hosted multi-tenant service. The call plan is the list of what exists: a capability not on it does not exist.
