"""Substack for a book's chapters — a serial (a series' pilot such as the
books library's `cost-line`) carried to a Substack publication as posts.

Substack has no public write API: its Developer API (substack.com/api-tos) only
reads public profile and publication data. So the sanctioned route is the one
Substack documents for every platform it does not know — its **post importer
reading an RSS feed** (Settings → Import/Export → Import posts, with "Update
existing posts" for a re-import) — and, for one chapter at a time, a **copy
package** (HTML and Markdown) a person pastes into Substack's editor as a draft.
The unofficial route — Substack's own undocumented web endpoints with a session
cookie — is an adapter too, but off unless the deployment arms it, and never
the default (its limits and risks are in docs/SUBSTACK.md).

| Module | What |
|---|---|
| `chapters.py` | `Chapter`, the interface every adapter takes, and the loader from a book's `library/<slug>/` files |
| `adapters.py` | `SubstackAdapter`: `FeedAdapter` and `CopyAdapter` (sanctioned), `UnofficialApiAdapter` (off by default) |
| `sync.py` | Syncing a book: idempotent by canonical URL and content digest, retried, contained, ledgered |

It touches no database and imports nothing from Django, so it runs where the
platform does not (`manage.py substack …` is its command line).
"""
