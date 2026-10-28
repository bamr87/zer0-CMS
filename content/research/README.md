# `research/` — the research library

Gathering information for content: web pages, feed items, documents and notes kept as sources with their extracted text, metadata, summary and entities; quotes and citations; collections; questions answered from the sources with citations; and drafts fact-checked against them ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 15, [TARGET.md](../../docs/plan/TARGET.md) § Ideas and research, PLAN G14). Every AI step is a run of the AI layer's `assistant` agent ([`ai/README.md`](../ai/README.md)), and every result is something a person reviews.

## The pieces

| File | What |
|---|---|
| `models.py` | `Collection`, `Source`, `Quote`, `Citation`, `FeedSubscription`, `Question`, `FactCheck`; `Collaborative` (a site-visible row is changed by the site's editors) and `placement` (what a row made inside a collection, a board or a feed inherits) |
| `fetch.py` | The only way research reaches the web: the SSRF guard, the limits, robots.txt, and extraction (trafilatura, pypdf, feedparser) |
| `services.py` | Every command: capture, upload, notes, feeds, search, summarize, ask, fact-check, cite, research briefs; retrieval |
| `handlers.py` | The run kinds `research.summarize`, `research.answer`, `research.fact_check`, `research.search` (registered with `ai.handlers.register`) |
| `tasks.py` | Celery: fetch a captured page, store a source's vector, refresh one feed, claim the due feeds and queue their reads (beat, every five minutes); the fetching tasks run on the `research` queue under a time limit |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/research/` |
| `data/` | The bundled output schemas (source summary, research answer, fact-check findings) and assistants (Source summarizer, Research answerer, Fact checker, Research brief writer), seeded after every migrate |

## Gathering

| Way in | What happens |
|---|---|
| A URL (`POST sources/` with `kind: url`) | Saved as `pending` and answered `202`; a worker asks robots.txt, fetches the page through the guard and extracts it — HTML through trafilatura (main text, title, author, site, date, language, description), a PDF through pypdf, plain text and Markdown in their own encoding (the declared charset, else UTF-8, else what charset-normalizer reads: UTF-16 with or without a mark, a legacy code page). A refusal or a failure is recorded on the source (`status: failed`, `error`), which can be fetched again (`refetch/`); a source is never left `fetching`. The worker writes only what a fetch owns (the text, the metadata, the status; a title or author only when the source has none), to the row as it is once the fetch is over: a person's change meanwhile stays, and a source deleted meanwhile stays gone. |
| A feed (`POST feeds/`) | An RSS or Atom subscription, refreshed when it is due (`interval_minutes`, 15 minutes to a week) or on request (`refresh/`, refused while the feed is paused), with `If-None-Match`/`If-Modified-Since`; each new item (by its guid) becomes a `feed` source with the item's text. Beat claims each due feed — its next check moves on — before a task reads it, so a slow batch never reads a feed twice; feedparser reads the bytes fetched, as a stream, never a URL or a file they name. A failure is kept on the subscription and tried again on schedule; a feed paused or deleted while it is read takes nothing. |
| An upload (`POST sources/upload/`, multipart) | A PDF, plain text or Markdown file, read in the request (it reaches no network), at most `RESEARCH_UPLOAD_MAX_BYTES`. |
| A note (`POST sources/` with `kind: note`) | Text a person writes. |
| A web search (`POST sources/search/`) | A run: a provider that declares `search` (`anthropic`'s server-side web search tool; the fake in tests) searches, and each hit becomes a `url` source to fetch. With no such provider configured, the request is refused (422). |

**The guard** (`fetch.get`): http and https only, no credentials in the URL; the host is resolved and every address it resolves to must be public (not private, loopback, link-local, carrier-grade NAT, multicast, reserved or unspecified, IPv4-mapped forms included); the connection goes to the address that was checked, with the name in `Host` and in TLS SNI, so a DNS answer that changes between the check and the connection cannot move it; environment proxies are not used; redirects are followed by hand and every hop is checked again (at most five); a body is read up to `RESEARCH_MAX_BYTES`, and the whole exchange — every hop's connection, status line, headers and body — is cancelled once it has taken `RESEARCH_FETCH_TIMEOUT` seconds, however slowly the server answers (resolving a name is left to the resolver's own timeout). Every field extracted is kept free of NUL and the other control characters but tab and line breaks, which Postgres refuses. `fetch.post` sends a body under the same guard and the same one deadline — no redirect followed, the answer's body not read — and is how an automation notifies a webhook (`automations/`). The tasks that fetch run on a `research` queue that only their own worker consumes (`research-worker` in `docker-compose.yml`) — automations' runs too, whose webhooks and email wait on someone else's server as well —, each stopped after `RESEARCH_TASK_TIME_LIMIT` seconds, so a slow site never holds the worker that runs agents and publishes; what a person asks to fetch — a capture, a refetch, a search, a subscription, a feed read now — is throttled per person (`THROTTLE_RESEARCH_FETCH_RATE`). An address written out in the URL is refused when the request is made (422); a name is resolved and checked by the worker. robots.txt is honoured for our user agent (`RESEARCH_USER_AGENT`) and its answer recorded on the source (`allowed`, `disallowed`, `unknown`).

## What the assistants do

| Kind | Started by | What a person gets |
|---|---|---|
| `research.summarize` | `sources/<id>/summarize/` | the summary and key points (`summary`), the entities it names (`entities`), passages worth quoting (`highlights`) — on the source, to edit or keep as quotes |
| `research.answer` | `POST questions/` | an answer drawn only from the closest sources (by stored vector — pgvector on Postgres — then by their words through Wagtail search in the database, then the newest), each claim marked with its source's label, and citations whose quotes are checked against the source's own text (`verified`) |
| `research.fact_check` | `POST fact-checks/` (a page the person may edit) | findings for the draft's claims — supported, contradicted or unsupported, with the sources that decide each — checked against what it read: the sources the draft cites first (every one, or the six closest to the draft when it cites more), then the closest of a chosen collection's; the check records what it read (`sources`) and how many it left out (`left_out`). A contradicted claim's correction is the exact words and what they should say; a block's corrections are made together in the block's own value — inside a rich-text block's runs of text, so its links, emphasis and lists stay — and proposed as one `replace` suggestion through the tool registry (`content.propose_edit`, as the `assistant` agent, for the person who asked: the agent's tools, its principal's page rights, the page's policy, the person's edit right and the rate all hold, and the call is a step of the run), for the editor to accept or reject in Review; nothing changes the page until a person accepts. A correction that cannot be made (its words not in the block exactly once, or running across a link) and a refusal (a page whose agent policy is `off`) are noted on the finding. |
| `research.search` | `POST sources/search/` | sources to fetch, one per hit |
| (an `assistant` run) | `collections/<id>/research-brief/` | a research brief on a topic from the collection (AIEO's: intent, keywords, angles, outline, link opportunities), to read and keep as a note |

Each run re-checks what it uses when it executes, as every AI run does: the row it is about must still be its starter's to use, and the assistant visible to them; a fact-check's page must be one they may edit. A brief that cites sources (`POST citations/` with a `brief`) hands them to its writer when it is generated (`ai.handlers.brief_context`).

## Rows and who sees them

Collections, sources, feeds, questions and fact-checks are owned rows with the AI layer's rules (`owner`, `site`, `visibility`, `visible_to(user, site)`), and research in a site is teamwork: a row visible to its site is changed by anyone who edits that site, but who sees it — its `site` and `visibility` — is changed only by its owner or staff (`CollaborativeSerializer`: 403 for anyone else, while a form that sends them back unchanged is fine). A row made inside a collection or a feed takes its site and visibility as far as its owner may hold them; sharing a collection later does not change the sources already in it. A quote is seen with its source and changed by its owner or the source's editors; a citation is seen with its source and what cites it (a page the person may edit, a brief they see) and removed by whoever made it.

## Settings

`RESEARCH_USER_AGENT`, `RESEARCH_MAX_BYTES` (5 MB), `RESEARCH_FETCH_TIMEOUT` (20 s for a whole exchange), `RESEARCH_UPLOAD_MAX_BYTES` (10 MB), `RESEARCH_TASK_TIME_LIMIT` (120 s for a fetching task; the hard limit is 30 s later), `THROTTLE_RESEARCH_FETCH_RATE` (30 a minute per person); the beat entry `research-feeds`; the `research` queue in `CELERY_TASK_ROUTES`; embeddings follow `EMBEDDING_BACKEND` (graph/README.md).

## Tests

`tests/research/`: the guard, robots.txt and extraction (`test_fetch.py`), every service and run kind with recorded HTTP and the fake provider (`test_services.py`), the API's scoping and flows (`test_api.py`), and the `anthropic` adapter's web search against a stand-in SDK (`test_search_provider.py`). Names resolve from a table and every request is recorded with respx — or, for a server that answers a byte at a time, sent to a stand-in on loopback in the test's own process: no test touches DNS, the web or a model.
