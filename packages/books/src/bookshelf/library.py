"""Discovery of book projects on disk.

A library is any directory holding one sub-directory per book. A directory
counts as a book when it contains a ``book.yml``; names starting with ``_`` or
``.`` are reserved (``_template`` is the scaffold source, not a book).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .models import Book

#: Default location of the library relative to the repository root.
LIBRARY_DIRNAME = "library"

#: Directory inside the library that seeds ``books new``.
TEMPLATE_DIRNAME = "_template"


class LibraryError(Exception):
    """Raised when the library directory is missing or a slug is unknown."""


def find_root(start: Path | None = None) -> Path:
    """Walk up from *start*, stopping short of the filesystem root, to the nearest directory holding ``library/``.

    The name is matched against the directory's real entries, case-sensitively: ``Path.is_dir()`` alone
    accepts ``/Library`` and ``~/Library`` on macOS's case-insensitive filesystem, and the CLI would then
    adopt the operating system's folder as a book repository whenever it runs outside one.
    """
    current = (start or Path.cwd()).resolve()
    for candidate in (current, *current.parents):
        if candidate == candidate.parent:
            break  # the filesystem root is never a repository
        if _holds_library(candidate):
            return candidate
    raise LibraryError(
        f"no {LIBRARY_DIRNAME}/ directory found in {current} or any parent; "
        "run from inside the repository or pass --root"
    )


def _holds_library(directory: Path) -> bool:
    """True when *directory* has an entry spelled exactly ``library`` and it is a directory."""
    try:
        names = os.listdir(directory)
    except OSError:
        # An ancestor that cannot be read cannot be the repository; keep walking up.
        return False
    return LIBRARY_DIRNAME in names and (directory / LIBRARY_DIRNAME).is_dir()


@dataclass
class Library:
    """All book projects under a library directory."""

    root: Path
    books: list[Book]

    @classmethod
    def load(cls, root: Path | None = None) -> Library:
        repo_root = Path(root).resolve() if root is not None else find_root()
        directory = repo_root / LIBRARY_DIRNAME
        if not directory.is_dir():
            raise LibraryError(f"{directory} is not a directory")
        books = [Book.load(path) for path in cls.book_dirs(directory)]
        books.sort(key=lambda book: book.slug)
        return cls(root=repo_root, books=books)

    @staticmethod
    def book_dirs(directory: Path) -> list[Path]:
        return sorted(
            path
            for path in directory.iterdir()
            if path.is_dir() and not path.name.startswith(("_", ".")) and (path / Book.CONFIG).exists()
        )

    @property
    def library_dir(self) -> Path:
        return self.root / LIBRARY_DIRNAME

    @property
    def template_dir(self) -> Path:
        return self.library_dir / TEMPLATE_DIRNAME

    def get(self, slug: str) -> Book:
        for book in self.books:
            if book.slug == slug:
                return book
        known = ", ".join(book.slug for book in self.books) or "(none)"
        raise LibraryError(f"unknown book {slug!r}; available: {known}")

    def select(self, slugs: list[str] | None) -> list[Book]:
        """Resolve a list of slugs, or every book when *slugs* is empty."""
        if not slugs:
            return list(self.books)
        return [self.get(slug) for slug in slugs]

    @property
    def word_count(self) -> int:
        return sum(book.word_count for book in self.books)
