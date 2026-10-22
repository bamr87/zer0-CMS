"""`manage.py import_books [--path DIR] [--site KEY] [--book SLUG …] [--force]`:
read a library's books (`<DIR>/<slug>/`, templates included) into the platform
(books/files.py). Re-running it changes nothing that did not change on disk; it
never overwrites what was changed in the platform since the files were last
read or written (a conflict, unless `--force`), never brings back a page
deleted there, and publishes a change only over a live page with no draft;
exit status 1 on any conflict or error."""

from django.conf import settings
from django.core.management.base import BaseCommand

from books.files import import_library


class Command(BaseCommand):
    help = "Import a library of books (library/<slug>/) into the platform."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=None, help="The library directory (default: BOOKS_LIBRARY_DIR).")
        parser.add_argument("--site", default=None, help="The library's site key (default: BOOKS_SITE_KEY).")
        parser.add_argument("--book", action="append", dest="books", help="Only this book (repeatable).")
        parser.add_argument("--force", action="store_true", help="Take the file where the platform changed it too.")

    def handle(self, *args, path=None, site=None, books=None, force=False, **options):
        report = import_library(
            path or settings.BOOKS_LIBRARY_DIR, site_key=site or settings.BOOKS_SITE_KEY, slugs=books, force=force
        )
        self.stdout.write(report.summary())
        for line in report.conflicts + report.errors:
            self.stderr.write(f"  {line}")
        if report.conflicts or report.errors:
            raise SystemExit(1)
