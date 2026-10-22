"""`manage.py export_books [--out DIR] [--site KEY] [--book SLUG …] [--prune]`:
write each book's generated file set to `<DIR>/<slug>/` from the platform's
latest revisions (books/files.py). An unchanged book writes the files it was
imported from, byte for byte, and a file already identical is not touched;
files there that the platform does not hold are listed (and with `--prune`,
deleted)."""

from django.conf import settings
from django.core.management.base import BaseCommand

from books.files import export_library


class Command(BaseCommand):
    help = "Write the platform's books as their library/<slug>/ files."

    def add_arguments(self, parser):
        parser.add_argument("--out", default=None, help="The library directory (default: BOOKS_LIBRARY_DIR).")
        parser.add_argument("--site", default=None, help="The library's site key (default: BOOKS_SITE_KEY).")
        parser.add_argument("--book", action="append", dest="books", help="Only this book (repeatable).")
        parser.add_argument("--prune", action="store_true", help="Delete files in a book's directory it does not hold.")

    def handle(self, *args, out=None, site=None, books=None, prune=False, **options):
        report = export_library(
            out or settings.BOOKS_LIBRARY_DIR, site_key=site or settings.BOOKS_SITE_KEY, slugs=books, prune=prune
        )
        self.stdout.write(report.summary())
        for path in report.written:
            self.stdout.write(f"  wrote {path}")
        for path in report.extra:
            self.stdout.write(f"  {'removed' if prune else 'not the platform’s'}: {path}")
