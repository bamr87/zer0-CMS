# `research/` — the research library

Gathering information for content: web pages, feed items, documents and notes kept as sources with their extracted text, metadata, summary and entities; quotes and citations; collections; questions answered from the sources with citations; and drafts fact-checked against them ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 15, [TARGET.md](../../docs/plan/TARGET.md) § Ideas and research, PLAN G14). Every AI step is a run of the AI layer's `assistant` agent ([`ai/README.md`](../ai/README.md)), and every result is something a person reviews.

## The pieces

| File | What |
|---|---|
| `models.py` | `Collection`, `Source`, `Quote`, `Citation`, `FeedSubscription`, `Question`, `FactCheck`; `Collaborative` (a site-visible row is changed by the site's editors) and `placement` (what a row made inside a collection, a board or a feed inherits) |
| `fetch.py` | The only way research reaches the web: the SSRF guard, the limits, robots.txt, and extraction (trafilatura, pypdf, feedparser) |
| `services.py` | Every command: capture, upload, notes, feeds, search, summarize, ask, fact-check, cite, research briefs; retrieval |
| `handlers.py` | The run kinds `research.summarize`, `research.answer`, `research.fact_check`, `research.search` (registered with `ai.handlers.register`) |
| `tasks.py` | Celery: fetch a captured page, store a source's vector, refresh one feed, refresh the due feeds (beat, every five minutes) |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/research/` |
| `data/` | The bundled output schemas (source summary, research answer, fact-check findings) and assistants (Source summarizer, Research answerer, Fact checker, Research brief writer), seeded after every migrate |

## Gathering

| Way in | What happens |
|---|---|
| A URL (`POST sources/` with `kind: url`) | Saved as `pending` and answered `202`; a worker asks robots.txt, fetches the page through the guard and extracts it — HTML through trafilatura (main text, title, author, site, date, language, description), a PDF through pypdf, plain text and Markdown as they are. A refusal or a failure is recorded on the source (`status: failed`, `error`), which can be fetched again (`refetch/`). |
| A feed (`POST feeds/`) | An RSS or Atom subscription, refreshed by Celery beat when it is due (`interval_minutes`, 15 minutes to a week) or on request (`refresh/`), with `If-None-Match`/`If-Modified-Since`; each new item (by its guid) becomes a `feed` source with the item's text. A failure is kept on the subscription and tried again on schedule. |
| An upload (`POST sources/upload/`, multipart) | A PDF, plain text or Markdown file, read in the request (it reaches no network), at most `RESEARCH_UPLOAD_MAX_BYTES`. |
| A note (`POST sources/` with `kind: note`) | Text a person writes. |
| A web search (`POST sources/search/`) | A run: a provider that declares `search` (`anthropic`'s server-side web search tool; the fake in tests) searches, and each hit becomes a `url` source to fetch. With no such provider configured, the request is refused (422). |

**The guard** (`fetch.get`): http and https only, no credentials in the URL; the host is resolved and every address it resolves to must be public (not private, loopback, link-local, carrier-grade NAT, multicast, reserved or unspecified, IPv4-mapped forms included); the connection goes to the address that was checked, with the name in `Host` and in TLS SNI, so a DNS answer that changes between the check and the connection cannot move it; environment proxies are not used; redirects are followed by hand and every hop is checked again (at most five); a body is read up to `RESEARCH_MAX_BYTES` within `RESEARCH_FETCH_TIMEOUT` seconds in all. An address written out in the URL is refused when the request is made (422); a name is resolved and checked by the worker. robots.txt is honoured for our user agent (`RESEARCH_USER_AGENT`) and its answer recorded on the source (`allowed`, `disallowed`, `unknown`).

## What the assistants do

| Kind | Started by | What a person gets |
|---|---|---|
| `research.summarize` | `sources/<id>/summarize/` | the summary and key points (`summary`), the entities it names (`entities`), passages worth quoting (`highlights`) — on the source, to edit or keep as quotes |
| `research.answer` | `POST questions/` | an answer drawn only from the closest sources (by stored vector — pgvector on Postgres — then by shared words, then the newest), each claim marked with its source's label, and citations whose quotes are checked against the source's own text (`verified`) |
| `research.fact_check` | `POST fact-checks/` (a page the person may edit) | findings for the draft's claims checked against the sources it cites and a collection — supported, contradicted or unsupported, with the sources that decide each — and, for each correction, a `replace` suggestion on the claim's block from the `assistant` agent, for the editor to accept or reject in Review; nothing changes the page until a person accepts. A page whose agent policy is `off` gets findings and no suggestions. |
| `research.search` | `POST sources/search/` | sources to fetch, one per hit |
| (an `assistant` run) | `collections/<id>/research-brief/` | a research brief on a topic from the collection (AIEO's: intent, keywords, angles, outline, link opportunities), to read and keep as a note |

Each run re-checks what it uses when it executes, as every AI run does: the row it is about must still be its starter's to use, and the assistant visible to them; a fact-check's page must be one they may edit. A brief that cites sources (`POST citations/` with a `brief`) hands them to its writer when it is generated (`ai.handlers.brief_context`).

## Rows and who sees them

Collections, sources, feeds, questions and fact-checks are owned rows with the AI layer's rules (`owner`, `site`, `visibility`, `visible_to(user, site)`), and research in a site is teamwork: a row visible to its site is changed by anyone who edits that site. A row made inside a collection or a feed takes its site and visibility as far as its owner may hold them. A quote is seen with its source and changed by its owner or the source's editors; a citation is seen with its source and what cites it (a page the person may edit, a brief they see) and removed by whoever made it.

## Settings

`RESEARCH_USER_AGENT`, `RESEARCH_MAX_BYTES` (5 MB), `RESEARCH_FETCH_TIMEOUT` (20 s), `RESEARCH_UPLOAD_MAX_BYTES` (10 MB); the beat entry `research-feeds`; embeddings follow `EMBEDDING_BACKEND` (graph/README.md).

## Tests

`tests/research/`: the guard, robots.txt and extraction (`test_fetch.py`), every service and run kind with recorded HTTP and the fake provider (`test_services.py`), the API's scoping and flows (`test_api.py`), and the `anthropic` adapter's web search against a stand-in SDK (`test_search_provider.py`). Names resolve from a table and every request is recorded with respx: no test touches DNS, the web or a model.
