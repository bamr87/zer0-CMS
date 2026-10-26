# `ideas/` — boards of ideas

Capturing ideas, sorting them on boards, voting, brainstorming with an assistant, clustering and de-duplicating them by meaning, and promoting one to a brief, an article or a book ([ADR 0006](../../docs/adr/0006-one-python-platform.md) decision 15, [TARGET.md](../../docs/plan/TARGET.md) § Ideas and research, PLAN G14). AI help comes through the AI layer ([`ai/README.md`](../ai/README.md)); research comes from [`research/`](../research/README.md).

## The pieces

| File | What |
|---|---|
| `models.py` | `Board`, `Idea` (title, notes, taggit tags, status, origin, the sources it links to, the brainstorm reply it came from, the brief or page it became), `Vote` |
| `services.py` | Capture (and AIEO's topic template), votes, brainstorms and keeping their ideas, clusters and duplicates, merging, promotion |
| `serializers.py`, `views.py`, `urls.py` | The REST API under `/api/v2/ideas/` |
| `tasks.py` | Celery: an idea's vector, stored after it is saved |
| `data/` | The bundled idea-list schema and the Brainstormer and Article writer assistants, seeded after every migrate |

## What a person does

| | How |
|---|---|
| Capture | `POST capture/` from anywhere — the studio, the editor's research tab, later the extension: the first line is the title, the rest the notes, or AIEO's topic template's (`template: topic`); onto a board or into the inbox (no board). |
| Sort | Boards are lists whose columns are an idea's statuses (`new`, `exploring`, `planned`, `promoted`, `archived`); move one by changing its status; filter by board (`none` is the inbox), status, origin, tag or words. |
| Vote | `POST <id>/vote/`, `DELETE` to take it back — one vote per person, by anyone who sees the idea. |
| Brainstorm | `POST brainstorm/`: a message in a brainstorm conversation (the AI layer's `Conversation`, with the bundled Brainstormer or another assistant) asking for angles, headlines or outlines, with the board's ideas to avoid and research to build on; its reply is a run whose result is validated against the idea-list schema. `POST keep/` keeps the ideas a person picks from the reply; nothing becomes an idea unseen. Post again with the `conversation` to continue the session. |
| Cluster | `GET clusters/`: groups of ideas alike in meaning (single-link at `IDEAS_CLUSTER_THRESHOLD`) and pairs similar enough to be one (`IDEAS_DUPLICATE_THRESHOLD`), read from the vectors workers stored in `graph.Embedding` — through the provider registry when `EMBEDDING_BACKEND` names one, the deterministic hashing embedder otherwise (SQLite, tests). No model is called in the request; on Postgres pgvector compares the pairs in the database, elsewhere each vector is made a unit vector once and a pair is one `math.sumprod` (at most 300 ideas at a time). |
| Merge | `POST <id>/merge/` folds another idea in: its notes, tags, sources and votes come along, then it goes. |
| Promote | `POST <id>/promote/` with `into`: `brief` — the AI layer's brief, written by the bundled Article writer (or another assistant) from the idea, with the idea's sources cited on it so its writer reads them, generated now with `generate` (202); `article` or `book` — a draft `ArticlePage` or `BookPage` under a parent, the notes as its body (never published). The idea is marked `promoted` and points at what it became. |

## Rows and who sees them

Boards and ideas are owned rows with the AI layer's rules (`owner`, `site`, `visibility`, `visible_to`), and a site's board is teamwork: a site-visible board or idea is changed by anyone who edits that site, while who sees it — its `site` and `visibility` — is changed only by its owner or staff (403 for anyone else; a form that sends them back unchanged is fine). An idea put on a board takes the board's site and visibility unless it says otherwise. What an idea links to is shown as far as the person reading it may see it — the sources they see, the brief if they see it, the page if they can find it — and saving `source_ids` keeps the idea's links to sources they cannot see; naming one they cannot see is refused (422). Promoting cites the sources the person who promotes it sees.

## Tests

`tests/ideas/`: the services (`test_services.py`) and the API (`test_api.py`), with the scripted fake provider and the hashing embedder; nothing reaches a model.
