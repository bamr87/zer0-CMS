"""A chapter as Substack needs it, and the loader from a book's file tree.

`Chapter` is the interface: any source — a book's `library/<slug>/` (the
books library's layout: `book.yml` and `chapters/chNN.md` with front matter),
or later the platform's `BookPage`/`ChapterPage` rows — gives adapters these
fields and nothing else, so an adapter never reads a book's files itself.

A chapter is `published` only when its front matter says `status: published`
(or `final`); every other status (outline, draft, revised, …) syncs as a draft,
which the sanctioned feed leaves out — Substack's importer publishes what it
imports. Its canonical URL is its front matter's `canonical_url`, else
`<canonical base>/<book>/<chNN>/`: the key the ledger and the feed's `guid` use,
so a re-sync never makes a second post.
"""

import hashlib
from dataclasses import dataclass
from pathlib import Path

import markdown
import yaml

PUBLISHED_STATUSES = frozenset({"published", "final"})


@dataclass(frozen=True)
class Chapter:
    series: str  # the book's slug
    series_title: str
    number: int
    title: str
    subtitle: str
    body_markdown: str
    canonical_url: str
    state: str  # "draft" | "published"
    source_file: str = ""
    published_at: str = ""  # ISO date, when the front matter gives one

    @property
    def key(self) -> str:
        return self.canonical_url

    @property
    def digest(self) -> str:
        """What a re-sync compares: the content Substack would receive, not the file's bytes."""
        text = "\n".join((self.title, self.subtitle, self.state, self.body_markdown))
        return hashlib.sha256(text.encode()).hexdigest()

    @property
    def html(self) -> str:
        return markdown.markdown(self.body_markdown, extensions=["extra"])


def _front_matter(text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---", 4)
    if end < 0:
        return {}, text
    data = yaml.safe_load(text[4:end]) or {}
    return (data if isinstance(data, dict) else {}), text[end + 4 :].lstrip("\n")


def load_book(directory, *, canonical_base: str) -> list[Chapter]:
    """Every chapter of the book in `directory` (a `library/<slug>/`), in chapter order."""
    root = Path(directory)
    manifest = yaml.safe_load((root / "book.yml").read_text(encoding="utf-8")) or {}
    slug = str(manifest.get("slug") or root.name)
    base = canonical_base.rstrip("/")
    chapters = []
    for path in sorted((root / "chapters").glob("ch*.md")):
        meta, body = _front_matter(path.read_text(encoding="utf-8"))
        number = int(meta.get("number") or int("".join(c for c in path.stem if c.isdigit()) or 0))
        status = str(meta.get("status") or "draft").lower()
        url = str(meta.get("canonical_url") or (f"{base}/{slug}/{path.stem}/" if base else ""))
        if not url:
            raise ValueError(f"{path.name}: no canonical_url and no canonical base — a chapter needs a stable key")
        chapters.append(
            Chapter(
                series=slug,
                series_title=str(manifest.get("title") or slug),
                number=number,
                title=str(meta.get("title") or path.stem),
                subtitle=str(meta.get("subtitle") or ""),
                body_markdown=body,
                canonical_url=url,
                state="published" if status in PUBLISHED_STATUSES else "draft",
                source_file=f"{slug}/chapters/{path.name}",
                published_at=str(meta.get("date") or ""),
            )
        )
    return sorted(chapters, key=lambda c: c.number)
