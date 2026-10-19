# `graph/` — the content graph

Entities, edges and vectors in Postgres (note §5), and the retrieval built on them.

- **Structural edges come free.** On every publish, `index_page` rebuilds the page's `child_of`, `references` (Wagtail's `ReferenceIndex`: chooser blocks, foreign keys), `links_to` (Markdown links and Obsidian wikilinks resolved by permalink, URL or source path), `tagged` / `in_category` (topic entities) and `translation_of` edges. They are derived, so they are replaced, never edited.
- **Agent edges** (`mentions`, `about`, `similar_to`, `contradicts`, `supersedes`) come from `graph.upsert_edge`: written directly only at or above `GRAPH_EDGE_AUTO_THRESHOLD` (0.85) under a `draft`-or-higher policy, otherwise a Suggestion.
- **Behavioural edges** come from Rails' `app.user.interaction` events, aggregated into daily counts as they arrive (no reader identifier is stored) and turned into `viewed_together` edges nightly (`build_viewed_together`).
- **Vectors** live in one table, `Embedding`, for every kind of object, keyed by `(object, model)` and stamped with the `content_hash` they were computed from; a page whose hash did not change is not re-embedded. `EmbeddingField` is pgvector's `vector` on Postgres and JSON text on SQLite; kNN uses `<=>` on Postgres and computes cosine in Python elsewhere. The default embedder (`hashing-256`) is deterministic feature hashing, so everything works offline; `EMBEDDING_BACKEND=litellm` swaps in a real model.

Reading: `related(page)` merges vector neighbours (0.6) with one hop of edges and shared topics (0.4); `semantic_search`, `neighbors` (≤ 2 hops), `path` (≤ 4) and `graph_rag` (search → expand → rerank). GraphQL exposes `related`, `semanticSearch`, `graphSearch` and `entities`; REST exposes `/api/v2/graph/{neighbors,path,related,search}/`; agents get `graph.*` tools.
