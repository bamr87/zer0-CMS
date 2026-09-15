# LinkedIn distribution

zer0-CMS carries a site's content to LinkedIn — to a company page or to a member's own profile — and brings the audience's aggregate response back into the site, where it decides what gets written next. A person approves every post. Nothing a repository ships can switch publishing on. Every LinkedIn call the CMS can make is declared, as data, before it is made.

```
page ──▶ draft ──▶ approve ──▶ preview ──▶ publish ──▶ ledger ──▶ statistics ──▶ .cms/distribution/performance.json
         pending   a person    no network   gated       keyed by    own posts,       read by the extension's
                                                        URL         aggregate        catering worklist
```

This is the design of record. It supersedes the per-site Python publisher bash-365.com ran from `scripts/features/linkedin/` and the `zer0-distribute` prototype on bash-365.com's `claude/linkedin-community-api-desc-so9f8u` branch; what changed on purpose is listed at the end.

## Where it runs

One pipeline, `Zer0Cms::Distribution::Pipeline`, is the only path to LinkedIn. Every surface calls it, so there is one gate to audit.

| Surface | Where | For |
|---|---|---|
| Library | `rails/lib/zer0_cms/linkedin/` (the API client) and `rails/lib/zer0_cms/distribution/` (the lane) | stdlib Ruby 3.3+, no bundle — the same rule as the doctor |
| CLI | `rails/bin/zer0-cms linkedin COMMAND --site PATH` | a terminal, and every other surface's reference behaviour |
| Reusable workflow | `.github/workflows/zer0-linkedin.yml` | a content repository's CI: publish merged drafts, check the token, read statistics |
| Fleet CMS | `/admin/distribution` and `/admin/channels` in the Rails app | the queue, the exact payload, approve and publish in a browser; connecting an account through LinkedIn's consent screen |
| MCP server | `zer0-cms linkedin mcp --site PATH` | Claude Code or any MCP client: status, sources, queue, preview, draft — publish only when the operator armed it |

## Configure a site

A site opts in with a `distribution.linkedin` block in its `zer0.json`. Settings only: no credential goes in the file, and no key in it can arm a publish.

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
| `author` | `_config.yml` `linkedin.org_urn` | Who posts: `urn:li:organization:{id}` for a page, `urn:li:person:{id}` for a member's own profile |
| `siteUrl` | `_config.yml` `url` + `baseurl` | The origin of the canonical URLs article shares link to and the ledger is keyed by |
| `apiVersion` | `202608` | The `Linkedin-Version` header (YYYYMM). LinkedIn supports a version for twelve months; the doctor warns two months before |
| `queue` | `.zer0/drafts/linkedin` | The draft queue folder |
| `ledger` | `.zer0/ledger.json` | The idempotency ledger |
| `acceptStatuses` | `["approved"]` | Which draft statuses may publish. `pending` means "a merge to the default branch is the approval": it counts only where `ZER0_LINKEDIN_MERGED=1` says the run is on that branch, which the reusable workflow sets there and nowhere else. On a laptop, in the MCP server and in the CMS a draft must be `approved` |
| `sources` | every collection | The collections whose pages can be shared |
| `fallbackImage` | none | A card image for a page with no uploadable preview |
| `hashtagLimit` | `3` | Hashtags in a composed first draft |
| `bannedPatternsFile` | none | Extra brand-guard bans, in the extension's `[{name, pattern, flags}]` format |
| `scopes` | by author type (below) | The OAuth scopes a connection asks for |

Paths must stay inside the repository; `..` and absolute paths are refused. An unknown key is a warning, so a typo such as `publishAllow` is reported rather than silently believed.

The environment, all optional, overrides the file for one process: `LINKEDIN_AUTHOR_URN` (or the older `LINKEDIN_ORG_URN`), `LINKEDIN_BASE_URL`, `LINKEDIN_API_VERSION`.

| Variable | Kind | Used for |
|---|---|---|
| `LINKEDIN_ACCESS_TOKEN` | secret | Every LinkedIn call. Sixty days |
| `LINKEDIN_REFRESH_TOKEN` | secret | Renewing the access token on a 401, when LinkedIn issued one |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | secret | OAuth: connecting an account, refreshing, and introspecting a token's expiry |
| `ZER0_LINKEDIN_PUBLISH` | switch | `1` arms a live publish for this process. The CLI also needs `--live`, the CMS a ticked confirmation |
| `ZER0_LINKEDIN_MCP_PUBLISH` | switch | `1` lets the MCP server's `linkedin_publish` tool run at all |
| `ZER0_LINKEDIN_MERGED` | switch | `1` says this run publishes the default branch, so a `pending` draft there was merged; the reusable workflow sets it for a run on the default branch and nowhere else |
| `ZER0_CMS_LINKEDIN_REDIRECT_URI` | setting | The fleet CMS's OAuth callback, when it is not this request's origin plus `/oauth/linkedin/callback` |

`zer0 doctor` reads the block the way the lane does and reports its errors, its warnings and an unreadable ledger under the `distribution` check, with the environment ignored so the report is the same on every machine. It also warns about a leftover per-site publisher.

## The draft queue

A draft is a markdown file at the top level of the queue folder; `examples/` and a front-matter-less `README.md` are never drafts. The dialect is the one the VS Code extension and the Python publisher already share, so a queue any of them wrote reads the same here.

| Key | Values | Meaning |
|---|---|---|
| `type` | `article` (default), `update` (`text` is accepted) | A link card for a page, or text alone |
| `status` | `pending` (default), `approved`, `published` | Where it is in the lifecycle |
| `source` | a repository path, or `section/YYYY-MM-DD-slug` | The page an article shares |
| `title`, `description`, `link` | text | An article's own card, for a link that is not a page of this site; ignored when `source` names a page |
| `no_thumbnail` | `true` | Post the card without an image |
| `linkedin_urn` | set on publish | The post it became |

The body is the commentary that publishes. `zer0-cms linkedin draft SOURCE` (or **Draft a post** in the CMS, or `linkedin_draft` over MCP) writes a new draft with a deterministic first commentary — the page's sub-title, excerpt or description as the hook, never its title, then up to three hashtags from its tags — for a person or an agent working to a skill to rewrite. A new draft is always `pending`; a collision becomes `-2`, never an overwrite.

Approval is `pending` → `approved`, by `zer0-cms linkedin approve`, the CMS's **Approve** button, or a person editing the line and merging it. It is refused while the brand guard has an error. There is no approval tool over MCP: approval is a person's act. Status changes are line surgery, so approving is a one-line diff.

## Preview and the gates

`preview` renders the exact request — the payload with its commentary escaped as LinkedIn will read it, the card image it would upload, the brand guard's findings and every blocker — reading files only, with no network call and no write. `publish` re-reads the draft from disk, rebuilds that preview and refuses on any blocker, in this order:

| Blocker | When | Lifted by |
|---|---|---|
| `config_error` | the site's settings have an error | fixing `zer0.json` |
| `no_author` | no author, or not a person or organization URN | the `author` setting |
| `source_missing` | the `source` names no page, the page has no URL or no description, or an article has neither source nor link | the draft or the site |
| `ledger_unreadable` | the ledger exists but is not JSON | repairing the ledger — never by reading it as empty |
| `guard_error` | a banned phrase, or commentary over 3,000 characters once escaped | editing the draft, or `--force` by a person who read it |
| `already_published` | the ledger has this draft's key | `--force`, deliberately posting again |
| `publish_unconfirmed` | an earlier attempt ended in a 5xx, a dropped connection or a success with no post id, so the post may exist | `zer0-cms linkedin record DRAFT URN` once a person finds the post, or `--force` once they have checked it did not post |
| `status_not_accepted` | the draft's status is not one this run may publish (`acceptStatuses`, with `pending` only in a merged run) | approval — never `--force` |
| `publish_disabled` | `ZER0_LINKEDIN_PUBLISH=1` is not set | the operator's environment — never a file or a flag |
| `no_credential` | no access token and no refresh token | the environment, or a connected channel |

Without `--live`, `publish` is a rehearsal: it reports the same blockers and exits non-zero when any blocker other than `status_not_accepted`, `publish_disabled` and `no_credential` applies — those three say a draft is not cleared to go yet, not that anything is wrong with it — so a dry run in CI fails on a guard error, a missing page or an unconfirmed attempt. `preview` exits the same way. `--force` needs a draft id; it never applies to a whole queue.

A create that ends in a 5xx, a dropped connection or a success with no post id may have posted, so the pipeline writes that doubt to the ledger before anything else happens — an `unconfirmed` entry with no URN — and every later run, on every surface, refuses that draft until a person has looked. One case is finished rather than refused: a draft whose key is already in the ledger, with nothing else in the way, is the tail of a run that died between the ledger write and the draft write, so a live run marks the draft published and posts nothing.

The brand guard is a rule-for-rule port of the extension's (`src/core/governance/guard.ts`): thirteen hard bans, nine filler warnings, the 140-character fold and the 3,000-character limit, with the same rule names, messages and order, so a finding reads the same in the editor, the CMS and CI.

## What LinkedIn sees

`zer0-cms linkedin plan` prints every call the client can make. `Client#request` takes a call id from that plan, never a URL, and refuses anything else before a socket opens; the one URL a caller supplies, the image upload slot LinkedIn returns, must be https on linkedin.com.

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

Two tests keep the list honest: every entry's `returns` sentence must contain the word "own", and no declared path may reach connections, people, followers, network sizes, social actions, likes, reactions, comments, messages, conversations or search. Adding a call that reaches another person's data therefore fails the build instead of shipping. Every REST call carries `Linkedin-Version` and `X-Restli-Protocol-Version: 2.0.0`; URNs are percent-encoded and Rest.li `List(...)` and `(key:value)` records are built by `Restli`.

Reads are retried on 429, 5xx and a dropped connection, honouring `Retry-After`. Writes are retried on 429 only: a 5xx or a dropped socket after `POST /rest/posts` may mean the post exists, and retrying it is how a page publishes the same thing twice. An error message is built from LinkedIn's error body, never from the request, and any credential the client holds is scrubbed out of it.

Commentary is escaped to LinkedIn's `little` text format before it is sent. All fifteen reserved characters — `| { } @ [ ] ( ) < > # \ * _ ~` — are backslash-escaped, except a hashtag (`#` and letters or digits, not glued to a word) and a mention written as `@[Name](urn:li:person:…)` or `…(urn:li:organization:…)`. Sent raw, LinkedIn misreads the text around an unescaped reserved character; the familiar symptom is a post cut off at its first parenthesis.

## Accounts and tokens

Each account is authorized by its owner through LinkedIn's three-legged OAuth: a member consents for their own profile, a page administrator for the pages they administer. Nothing can mint a token for anyone who did not consent. The scopes requested by default are the least each author type needs:

| Author | Scopes |
|---|---|
| organization | `w_organization_social r_organization_social rw_organization_admin` |
| person | `openid profile w_member_social r_member_postAnalytics` |

Two ways to connect. In a terminal, `zer0-cms linkedin connect` prints the consent URL, waits for LinkedIn's redirect on `http://127.0.0.1:8765/callback` (add it to the app's authorized redirect URLs; `--redirect-uri` may name another loopback port, which is then the one it listens on), checks `state`, exchanges the code and — only with `--write-env FILE` for a file git ignores, or `--print-token` — stores or shows the token for a CI secret. In the fleet CMS, a **Channel** (a site plus an author URN) has **Connect with LinkedIn** — a POST, so no other site can start a connection; the callback is accepted only when its `state` matches the one this session started less than ten minutes ago, and is consumed on first use. The token is then stored encrypted with Active Record encryption, keys derived from `secret_key_base`, and never rendered; `code` and `state` are filtered out of the request log, and changing a channel's site or author forgets its token. A channel's token is used for its site; without one the CMS falls back to the environment's `LINKEDIN_ACCESS_TOKEN`.

Access tokens last sixty days. LinkedIn issues refresh tokens (365 days) only to apps it has enabled for programmatic refresh; with one, a 401 refreshes once and repeats the call — safe, because a 401 means LinkedIn did nothing. Without one, the owner re-runs consent, which LinkedIn skips while they are signed in and the old token is alive. `zer0-cms linkedin status --check` asks LinkedIn: with the app credentials it introspects the token (active, scopes, expiry); without them it only proves the token works with a cheap read, and says expiry cannot be known. A 403 on that read is reported as "authenticates but may not read", not as a dead token.

## The ledger

A flat JSON file keyed by what was published: an article's canonical URL, or `draft:<queue path>` for a text update, which has no URL of its own. Whichever surface publishes a key first writes it; every other surface looks it up and skips. That coordination depends on agreement about the file, so:

- an entry carries the post URN under both `linkedin_urn` (the name live ledgers already hold) and `urn` (the name the extension reads), with `posted_at`, `type`, `target: "linkedin"`, `author`, `source_file` and, when a card image was uploaded, `image_urn`; a reader accepts either URN name;
- the file is written as Python's `json.dump(indent=2, sort_keys=True)` plus a newline, byte for byte, pinned by a golden test, so no surface churns it;
- a write is a read-modify-write under an exclusive lock outside the repository, then an atomic rename, and every key it does not own — metadata other lanes wrote, of any shape — survives it;
- an attempt LinkedIn did not confirm is an entry with `state: "unconfirmed"`, `attempted_at` and `error` but no URN: no reader counts it as published, and the pipeline refuses that key until `record` replaces it or a person forces past it;
- an unreadable ledger is never read as "nothing published" and never rewritten.

The canonical URL is the one Jekyll 4.4 gives the page: a front-matter `permalink`, then a matching `defaults:` scope, then the collection's `permalink`, then the site's style, with Jekyll's placeholders and slugify rules (`Distribution::Permalink`). On bash-365.com that reproduces every URL the Python publisher keyed its ledger by, and gets right the one it got wrong: a post whose front matter moves it elsewhere.

## Statistics

`zer0-cms linkedin stats --write` (the CMS's **Read statistics**, or the workflow's `stats` command) reads aggregate counts for the ledger's posts by the configured author — `organizationalEntityShareStatistics` in batches of twenty for a page, `memberCreatorPostAnalytics` one metric per call for a member — and merges them into `.cms/distribution/performance.json`:

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

That is the file the VS Code extension's `writePerformance` writes and its catering worklist ranks subjects from, so the loop closes in the editor where writing happens. A post LinkedIn leaves out of a page-statistics answer had no impressions and no actions, and is recorded as zeros, as LinkedIn's documentation says to read it; only posts this lane asked about are filled in. A refresh merges over the file, so this week's numbers update this week's posts and leave the history alone. Nothing about who engaged is requested, stored or derivable.

## CI: the reusable workflow

A content repository calls `zer0-linkedin.yml` without vendoring anything:

```yaml
name: LinkedIn publish
on:
  push:
    branches: [main]
    paths: ["drafts/linkedin/**"]
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
      live: ${{ github.event_name == 'push' || inputs.live == true }}
    secrets: inherit
```

| Input | Default | Meaning |
|---|---|---|
| `command` | `publish` | `publish`, `status` (fails when the token is dead or within `warn-days` of expiry) or `stats` |
| `site-path` | `.` | The Jekyll root inside the caller; absolute or climbing paths fail the job |
| `live` | `false` | `publish` only: send, rather than rehearse |
| `draft` | empty | `publish` only: one draft id instead of the queue |
| `warn-days` | `7` | `status` only |
| `zer0-cms-ref` | `main` | The zer0-CMS ref to run |

It checks out the caller — at the tip of the branch the run is on, not the commit that triggered it, so a run queued behind another sees the ledger that run committed — and zer0-CMS side by side, and runs the CLI on Ruby 3.3 with no bundle. It sets `ZER0_LINKEDIN_MERGED=1` when that branch is the repository's default branch and `ZER0_LINKEDIN_PUBLISH=1` for the one step of a live publish. After a live publish or a stats run it commits the ledger, the queue and the performance file back with `[skip ci]` (a `GITHUB_TOKEN` push starts no workflow, so it cannot loop); if the push still conflicts after a rebase, the job fails and the files are in the `zer0-linkedin-results` artifact with the CLI's output, which also goes to the job summary. Concurrency is per repository and command, so a token check never displaces a queued publish. The workflow declares no permissions, so the caller's grant applies: `contents: write` for publish and stats, `contents: read` for status. A rehearsal needs no credential; every other run without `LINKEDIN_ACCESS_TOKEN` or a refresh token skips with a notice.

## The MCP server

`zer0-cms linkedin mcp --site PATH` speaks newline-delimited JSON-RPC on stdio. Tools: `linkedin_status`, `linkedin_plan`, `linkedin_sources`, `linkedin_queue`, `linkedin_preview`, `linkedin_draft`, `linkedin_posts` and `linkedin_publish`. The last needs `ZER0_LINKEDIN_MCP_PUBLISH=1` and `ZER0_LINKEDIN_PUBLISH=1` in the server's environment plus `confirm: true` on the call, and then runs the same `Pipeline#publish`. The server never runs with `ZER0_LINKEDIN_MERGED`, so a draft that is not `approved` is refused, whatever the site's `acceptStatuses`. Every call re-reads the configuration and the queue from disk. A site wires it into Claude Code through its `.mcp.json`:

```json
{ "mcpServers": { "zer0-linkedin": { "type": "stdio", "command": "ruby",
  "args": ["${ZER0_CMS_DIR:-../zer0-CMS}/rails/bin/zer0-cms", "linkedin", "mcp", "--site", "."] } } }
```

## What changed from the Python publisher, on purpose

- **Commentary is escaped.** The Python lane sent raw text, which LinkedIn's `little` format misreads at the first reserved character.
- **A write is not retried after a 5xx.** The Python lane retried every request, including `POST /rest/posts`.
- **Canonical URLs follow Jekyll.** The Python lane built `/posts/Y/M/D/slug/` from the filename, which is wrong for a post with its own `permalink`.
- **An unreadable ledger blocks publishing.** The Python lane read it as empty.
- **Text updates are ledgered**, under `draft:<path>`, so a re-run cannot post one twice.
- **An unconfirmed create blocks the next run.** A 5xx, a dropped connection or a success with no post id is written down as `unconfirmed`, because the post may exist.
- **A queued CI run publishes from the branch tip**, so it sees what the run before it recorded, and a `pending` draft publishes only in a run on the default branch.
- **A share is a draft, always.** The Python workflow's dispatch could post a free-text update or any article by reference without a queue file; the reusable workflow publishes only drafts, so every post has a file a person approved.
- **Page roles are verified, tokens introspected**, rather than inferred from whether a post-listing call happens to succeed.

## Not built, and not to be described as built

Reading or replying to comments, reactions or mentions; anything about individual members (profiles, connections, followers, who engaged); scheduling, queue-ahead or timed release; video, document, poll or multi-image posts; and a hosted multi-tenant service. The call plan is the list of what exists: a capability not on it does not exist.
