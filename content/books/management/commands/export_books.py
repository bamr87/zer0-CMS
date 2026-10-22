"""`manage.py export_books [--out DIR] [--site KEY] [--book SLUG …] [--include-drafts] [--force] [--prune]`:
write each book's generated file set to `<DIR>/<slug>/` from the platform
(books/files.py) — what is live, or with `--include-drafts` the latest
revisions. An unchanged book writes the files it was imported from, byte for
byte, and a file already identical is not touched. A file changed by hand since
the platform last read or wrote it is kept and reported as a conflict (import
it with import_books, or `--force` to overwrite it); a file the platform no
longer has there is removed while unchanged. Files the platform never held are
listed (and with `--prune`, deleted). Exit status 1 on any conflict."""

from django.conf import settings
from django.core.management.base import BaseCommand

from books.files import export_library


class Command(BaseCommand):
    help = "Write the platform's books as their library/<slug>/ files."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=None, help="The library directory (default: BOOKS_LIBRARY_DIR).")
        parser.add_argument("--site", default=None, help="The library's site key (default: BOOKS_SITE_KEY).")
        parser.add_argument("--book", action="append", dest="books", help="Only this book (repeatable).")
        parser.add_argument(
            "--include-drafts", action="store_true", help="Write the latest revisions, not what is live."
        )
        parser.add_argument("--force", action="store_true", help="Overwrite files changed by hand since the last sync.")
        parser.add_argument("--prune", action="store_true", help="Delete files in a book's directory it does not hold.")

    def handle(self, *args, out=None, site=None, books=None, include_drafts=False, force=False, prune=False, **opts):
        report = export_library(
            out or settings.BOOKS_LIBRARY_DIR,
            site_key=site or settings.BOOKS_SITE_KEY,
            slugs=books,
            prune=prune,
            include_drafts=include_drafts,
            force=force,
        )
        self.stdout.write(report.summary())
        for path in report.written:
            self.stdout.write(f"  wrote {path}")
        for path in report.removed:
            self.stdout.write(f"  removed {path}")
        for path in report.skipped:
            self.stdout.write(f"  skipped {path}")
        for path in report.extra:
            self.stdout.write(f"  {'removed' if prune else 'not the platform’s'}: {path}")
        for line in report.conflicts:
            self.stderr.write(f"  {line}")
        if report.conflicts:
            raise SystemExit(1)
