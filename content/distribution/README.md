# `distribution/` — channels, the queue, the ledger, statistics

Carrying a site's content to where its readers are — a LinkedIn page or profile, a WordPress site, a GitHub repository as a pull request, a newsroom newsletter — under a person's approval, and the audience's aggregate response back ([TARGET.md](../../docs/plan/TARGET.md) § Distribution, built in PLAN G5). The studio's Distribution area (`web/packages/ui/src/distribution/`) is where people use it; [`docs/DISTRIBUTION.md`](../../docs/DISTRIBUTION.md) is the design of record, including the LinkedIn call plan.

```text
compose ──▶ brand guard ──▶ approve ──▶ publish (202) ──▶ worker: every gate again ──▶ published | failed
a person,   findings kept    a person     an armed channel     LinkedIn · WordPress ·      ledger, keyed by
an agent,   on the post      who may      and the deployment's  GitHub pull request ·      canonical URL
or a page                    publish      switch for its kind   newsletter
going live                   the page
```

## The pieces

| File | What |
|---|---|
| `models.py` | `Channel` (a site's LinkedIn page or profile, WordPress site, GitHub repository or newsletter; its credential encrypted with the AI layer's keys, `ai/crypto.py`, rotated with them by `manage.py rotate_ai_credentials`, and write-only), `DistributionPost` (a page or a story going to a channel), `LedgerEntry` (what a channel published, keyed by canonical URL), `Statistic` (a post's counts on a day); `visible_to(user, site)` |
| `services.py` | Every command: channels and their connections, the canonical URL, composing, the brand guard, approving and rejecting, the gates (`preview`), publishing on the worker (`deliver`), recording a post by hand, the ledger as a file, statistics |
| `gates.py` | The publish gates in their fixed order, shared with the site's own lane |
| `ledger.py` | The ledger as a file — Python's `json.dump(indent=2, sort_keys=True)` plus a newline, the extension's and every lane's byte format, written under a lock and atomically; an unreadable ledger is never read as empty |
| `permalink.py` | The URL Jekyll gives a page: the canonical URL both the platform and a site's lane key the ledger by |
| `linkedin/` | The LinkedIn client: every call declared as data, OAuth with state and PKCE, posts and card images, page roles, aggregate statistics (`linkedin/__init__.py`) |
| `transports.py` | WordPress (REST over https, through the research library's fetcher, `research.fetch.send`: its SSRF guard, one deadline and size cap), GitHub pull requests (PyGithub; the page's file as a write-back writes it, `exporters.jekyll.file_of`), email (the newsroom's newsletters) |
| `lane/` | The LinkedIn lane over a site's own files, for its CI and a terminal: `manage.py linkedin …` (`lane/__init__.py`) |
| `tasks.py` | Publishing, exchanging an OAuth code, checking a channel; on beat, settling attempts that are over without their worker saying so (`distribution-settle`, each minute) and statistics (`distribution-statistics`, daily) |
| `tools.py` | `distribution.compose` (`propose`) and `distribution.publish` (`publish`) in the registry |
| `consumers.py`, `agent.py` | `content.page.published` → a run of the GitOps `distribution` agent (`agents/definitions/distribution.yaml`), which drafts a post for every channel of the page's site that drafts automatically |
| `serializers.py`, `views.py`, `urls.py` | `/api/v2/distribution/` and LinkedIn's OAuth callback |

## Channels

A channel belongs to a site. Who sees it: everyone who edits that site. Who sets one up, connects it, changes its credential, arms it, has the worker check it or read its statistics, and removes it: people with the `distribution.change_channel` permission (a superuser has it), as configuring an AI provider is a permission, not `is_staff`. A site has one channel per target — the LinkedIn author, the WordPress address, the repository and folder, the newsletter (`models.target_of`) — since each channel keeps its own ledger, and a second channel for one place would post a page there twice; `save_channel` refuses it, naming the first. A channel goes, with its posts, only while its ledger is empty: a post that went out, or an attempt that may have, is what keeps a page from going there twice — disconnect it instead.

| Kind | Settings (never a secret) | Credential (encrypted, write-only) | Connected by |
|---|---|---|---|
| `linkedin` | `author` (`urn:li:organization:…` or `urn:li:person:…`), `api_version`, `scopes`, `ledger_file` | `access_token`, `refresh_token` | **Connect with LinkedIn**: the platform's app (`LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET`) sends the account's owner to LinkedIn's consent screen with a fresh `state` and a PKCE challenge kept in their session; the callback (`/api/v2/distribution/oauth/linkedin/`) accepts a state once, within ten minutes, and the worker exchanges the code with the verifier. A 401 refreshes the token once (when LinkedIn issued a refresh token) and keeps the new one. PKCE has never been tried against a live LinkedIn, which documents it for native apps only — a server ignores a parameter it does not know (RFC 6749 § 3.1), so state is the guard relied on. A channel uses its own token only — never the environment's `LINKEDIN_ACCESS_TOKEN`, which is the site lane's — so one nobody connected is neither checked, read for statistics nor published to |
| `wordpress` | `url` (https only: the application password never travels in the clear), `username`, `status` (`draft` by default) | `application_password` | the person typing the user's application password |
| `github_pr` | `repo` (`owner/name`), `branch` (`main`), `directory` (where the site lives in the repository) | `token` | the person typing a token that may push and open pull requests |
| `email` | — and the channel's `newsletter` (one of the site's) | — | nothing: the newsroom sends it |

A channel whose site, author, address, user or repository changes forgets its credential: it was given for the old one. **Check** asks the target, on the worker, whether the credential works and who it publishes as (LinkedIn: introspection and a cheap read; WordPress: `users/me`; GitHub: the user and their push right on the repository; email: the newsletter's confirmed subscribers).

## The queue

A **post** is a page — or a story, whose page it is — going to one channel: an `article` (a link card for LinkedIn; the page itself for WordPress and GitHub; the story in a newsletter issue) or, for LinkedIn only, a text `update`. Composing one — of a live page — computes its **canonical URL** (`services.canonical_url`: a page of a Jekyll site gets the URL Jekyll gives its file, read from the site's checkout `_config.yml` — the key its own lane and CI use, so the platform and they never double-publish; any other page gets Wagtail's URL, and a page that names its canonical URL keeps it). The checkout is found by one rule, `services.site_checkout` — the site root's `source_root`, through symlinks, only inside this repository or `SITES_DIR`, as the site registry's (`sites.services.resolve_checkout`) — so compose's `/sites` works and a `source_root` an editor changed leads nowhere else; a site with a URL of its own whose `_config.yml` cannot be read there is refused (409), never keyed by a guessed URL. Composing also seeds its text with the page's own summary and tags (the lane's default commentary), and runs the **brand guard** (`suggestions/guard.py`, the extension's rules with the active brand rules; for LinkedIn also its 3,000-character limit once escaped) — the findings stay on the post. A post is always a draft when it is made, by a person, an agent or the published-page consumer. Someone who does not manage channels sees the posts of the channels they see about pages they find in the studio (`cms.services.visible_pages`); a text update, which has no page, is the managers'.

**Approving** is a person's act — someone who may publish the page (a text update's: a channel manager) — and is refused while the guard has an error. Approval is of the exact text: `approved_digest` keeps a hash of the kind and text the person approved, the gates compare it, and changing the text of an approved or failed post sends it back to draft — someone who may edit the page need not be someone who may publish it. **Publishing** answers `202` and runs on the worker. Both the request and the worker check every gate, in `gates.ORDER`:

| Gate | When | Lifted by |
|---|---|---|
| `config_error` | the channel is not connected, or misses a setting its kind needs | the channel |
| `no_author` | a LinkedIn channel has no author URN | the channel |
| `source_missing` | the page is gone or not live, has no public URL, or (LinkedIn) no title and description for the card; an email's story is not published | the page or the story |
| `ledger_unreadable` | the channel's site ledger file is not JSON, or cannot be reached from the machine doing the work (the site's checkout is not there), or — asked by the worker, which writes it — cannot be written there | repairing the file, or running where the checkout is — never by reading it as empty |
| `guard_error` | the brand guard has an error | editing the text, or `force` |
| `already_published` | the ledger has the post's key with a post id (the channel's rows, or the site's ledger file) | `force` |
| `publish_unconfirmed` | an earlier attempt ended in a 5xx, a dropped connection or a success without an id, so it may have published | **Record** (a person found the post), or `force` once they checked it did not post |
| `status_not_accepted` | a person has not approved it, or its text is not the text they approved | approval — never `force` |
| `publish_disabled` | the channel is not armed (its `armed` setting, a person's), or the deployment does not publish to its kind (`ZER0_LINKEDIN_PUBLISH`, `ZER0_WORDPRESS_PUBLISH`, `ZER0_GITHUB_PR_PUBLISH`, `ZER0_EMAIL_PUBLISH`) | the operator — never `force` |
| `no_credential` | no credential to publish with | connecting the channel |

A failure is a sentence a person can act on: LinkedIn's error body with every credential scrubbed out; WordPress's 401 (the application password), 403 (the user may not post) and 404 (no REST API at that address); GitHub's 401, 403 (rate limit or no write access), 404 and 422 — with the link when a pull request for the post is already open — as barodybroject reported them; the newsletter's own refusal. A write that may have landed (a 5xx, a dropped connection, a LinkedIn success with no post id) is written down as an **unconfirmed** ledger entry before the error goes up, and nothing sends that key again until a person records the post or forces past it. The worker claims an attempt (`attempted_at`, committed, by a conditional update) before it sends anything, so a task delivered twice — acks are late — never sends twice, and a post queued or being sent is not queued again (409). Every attempt ends published or failed: an error nobody expected (a library's own network error, an unreadable image, the soft time limit a minute before the hard one) fails the post and ledgers it unconfirmed, since it may have gone. An attempt that is over without its worker saying so — a claim older than the send's time limit (`tasks.SEND_TIME_LIMIT`), whose worker died — is settled by the next Publish or by the beat's sweep (`distribution-settle`, each minute): ledgered unconfirmed and failed for a person to check; a post no worker took within that time goes back to approved, as nothing was sent. An email post follows its newsletter issue (`DistributionPost.issue`): it is published, and ledgered under the issue's id, once the newsroom has sent it, and fails with the newsroom's reason when it could not; publishing again resumes the same issue for those who have not had it. **Record** takes an approved or failed post only.

## The ledger

`LedgerEntry` rows, one per channel and key: the canonical URL of an article, or `draft:<post id>` for a text update. **Download** gives a channel's ledger as the file every lane reads (`services.ledger_file`, byte for byte the extension's format: `urn`, and `linkedin_urn` for LinkedIn, `posted_at`, `type`, `target`, `author`, `source_file`, `image_urn`; an unconfirmed attempt as `state`, `attempted_at`, `error`); **Import** reads one in — the extension's, a site's CI's — so what another lane published is never published again from here, keeping the keys it does not model; every entry is checked first (a real date, `type` article or update, each value within its column), and one that cannot be a row refuses the file (422, naming them). A publish writes exactly the entry every lane writes, nothing of an older one. Each entry's API id is its UUID `public_id`. A LinkedIn channel may also name its site's own `ledger_file` (inside the site's checkout, found by `site_checkout`): the platform then reads it before publishing and writes what it published into it, under the same lock and atomic rename the lane uses — the worker, which compose mounts the sites writable for, refuses a post whose file it cannot write before sending anything. The write is a change in the checkout's working tree, never a commit: the site's own CI lane, which reads the committed file, sees it once someone commits it, and the post's notes say so. A file that cannot take the entry after a post went out never undoes the channel's row: the post exists, and the row is what keeps the platform from sending it again (the post's notes say the file did not take it; **Download** gives the entry for the site).

## Statistics

Once a day (`distribution-statistics` on beat) — or when a person asks — the worker reads aggregate counts for each LinkedIn channel's own published posts (`organizationalEntityShareStatistics` for a page, `memberCreatorPostAnalytics` for a member) into `Statistic` rows, one per post a day. Nothing about who engaged is requested, stored or derivable. The ledger's list carries each entry's latest counts.

## Agents, MCP and the published-page consumer

`distribution.compose` drafts a post of a page for a channel of its site, as the agent user, under the narrower of the agent's and the page's policy (`suggest` or more) and the agent's change right on the page; a person approves the draft. `distribution.publish` publishes a post a person approved, to an armed channel — and is refused until the page's and the agent's policy is `auto`, the definition is live and the agent's group holds the page's publish right, which none is given: the armed path is off until each is set on purpose. The GitOps `distribution` agent lists both, so an MCP client holding its token sees them. When a page goes live (`content.page.published`, consumed once per event), a run of that agent drafts a post for every channel of the page's site with **auto draft** on — a draft, never a publish; a page at policy `off` gets none, and a channel that already has a post of the page — a rejected one too: a person said no — gets no other.

## The API (`/api/v2/distribution/`)

| Path | What |
|---|---|
| `channels/` | list (`site`, `kind`), create, read, change (`PATCH`, `credentials` write-only), delete (refused while its ledger holds anything: it is what keeps posts from going twice — disconnect it instead); `connect/` (LinkedIn's consent URL), `disconnect/`, `check/` (202) and `statistics/` (202) for channel managers, `ledger-file/` (`GET` the file, `POST` one to import) |
| `oauth/linkedin/` | LinkedIn's callback: a state this session started, once; redirects to the studio's channel |
| `posts/` | the queue (`channel`, `site`, `status`, `page`, `story`), compose (201; a page the person cannot find is a 404, one that is not live a 409), read (with every blocker and LinkedIn's exact payload), change the text (`PATCH`), delete a draft; `approve/`, `reject/`, `publish/` (202 — or the post as it ended, for an attempt that is over without its worker saying so —, 409 while it is queued or being sent, or with every blocker; `force`), `record/` |
| `ledger/` | what was published (`channel`, `site`, `state`), each with its UUID id and its latest statistics |

## The lane over a site's own files

`manage.py linkedin COMMAND --site PATH` (`lane/`) is the LinkedIn lane for a site that is still files — a content repository's CI, through the reusable `.github/workflows/zer0-linkedin.yml`, and a terminal: `status [--check]`, `plan`, `sources`, `queue`, `draft`, `approve`, `preview`, `publish [--live] [--force]`, `record`, `posts`, `verify`, `organizations`, `stats [--write]`, `connect` (a loopback callback, with state and PKCE), and `mcp` — the same tools over MCP on stdio for an agent in the site's checkout, with no approve tool and `linkedin_publish` off unless the server's environment arms it (`ZER0_LINKEDIN_MCP_PUBLISH=1` and `ZER0_LINKEDIN_PUBLISH=1`) and the call says `confirm: true`. `zer0 doctor`'s `distribution` check is `sites/doctor.py`'s, which needs no Django so the reusable `zer0-doctor.yml` can run it. It reads the site's `zer0.json` `distribution.linkedin` block, its draft queue and its ledger file, touches no database, and shares this app's client, gates, ledger file, permalinks and brand guard — so a draft, a finding and a ledger entry mean the same in the extension, the studio and CI. It is the Ruby lane (`rails/lib/zer0_cms/{linkedin,distribution}`) in Python, held to what that lane computed (`tests/distribution/golden/ruby-lane.json`, recorded on ruby:3.3 over the fixture site and every site in this repository).

## Tests

`tests/distribution/`: `test_linkedin.py` (the client; the Ruby lane's tests), `test_lane.py` (the lane end to end and its command line; the Ruby lane's tests and its recording), `test_platform.py` (channels, OAuth, the queue and its gates, the ledger file, the site ledger, statistics, the tools, MCP and the consumer), `test_transports.py` (WordPress, GitHub pull requests, email). LinkedIn and WordPress are recorded with respx (WordPress at the address the SSRF guard pins), GitHub with `responses` (PyGithub speaks `requests`), email with Django's locmem backend.
