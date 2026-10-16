# .raw — immutable source drop-zone

Drop source documents (PDFs, articles, exports, images, transcripts) here, then tell Claude:

> ingest [filename]

`/wiki-ingest` reads the source and generates 8–15 cross-linked pages under `wiki/`. Files in `.raw/` are **never modified** — they are the immutable ground truth. This folder is hidden from Obsidian's file explorer and graph (dot-prefixed).

This folder starts empty. The existing Jekyll content under `_docs/`, `_posts/`, etc. is *already* vault content and does not need ingesting.
