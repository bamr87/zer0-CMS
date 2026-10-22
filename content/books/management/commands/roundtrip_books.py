"""`manage.py roundtrip_books [--path DIR] [--book SLUG …]`: import a library
into a throwaway transaction, export it to a temporary directory, and compare
every file of every book with the original, byte for byte (ADR 0006 decision
13). Prints the files that differ or are missing; exit status 1 if any does.
Nothing is left in the database."""

import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from books.files import export_library, import_library, library_dirs, read_dir


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Round-trip a library of books through the platform and diff the result."

    def add_arguments(self, parser):
        parser.add_argument("--path", default=None, help="The library directory (default: BOOKS_LIBRARY_DIR).")
        parser.add_argument("--book", action="append", dest="books", help="Only this book (repeatable).")

    def handle(self, *args, path=None, books=None, **options):
        root = Path(path or settings.BOOKS_LIBRARY_DIR)
        differ, compared, summary = [], 0, ""
        try:
            with transaction.atomic(), tempfile.TemporaryDirectory() as out:
                report = import_library(root, site_key="roundtrip-books", slugs=books)
                summary = report.summary()
                differ += report.conflicts + report.errors
                export = export_library(out, site_key="roundtrip-books", slugs=books)
                summary += f"; {export.summary()}"
                for directory in library_dirs(root):
                    if books and directory.name not in books:
                        continue
                    original, _ = read_dir(directory)
                    exported, _ = read_dir(Path(out) / directory.name)
                    for rel in sorted(set(original) | set(exported)):
                        compared += 1
                        if original.get(rel) != exported.get(rel):
                            differ.append(f"{directory.name}/{rel}")
                raise _Rollback
        except _Rollback:
            pass
        self.stdout.write(summary)
        for rel in differ:
            self.stdout.write(f"  differs: {rel}")
        self.stdout.write(f"{compared - len(differ)}/{compared} file(s) identical after the round trip")
        if differ:
            raise SystemExit(1)
