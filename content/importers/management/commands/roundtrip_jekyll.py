"""`manage.py roundtrip_jekyll --path DIR`: import a site into a throwaway
transaction, export it, and compare every imported file — each page's, and
each file read with one (an ABC book's spec sidecar) — with the original
(PLAN §4.7). Prints the files that differ; exit status 1 if any does.
Nothing is left in the database."""

import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.db import transaction

from exporters.jekyll import export_site
from importers.jekyll import import_site
from importers.models import ImportedSource


class _Rollback(Exception):
    pass


class Command(BaseCommand):
    help = "Round-trip a Jekyll site through Wagtail and diff the result."

    def add_arguments(self, parser):
        parser.add_argument("--path", required=True)
        parser.add_argument("--site", default="roundtrip")

    def handle(self, *args, path, site, **options):
        root = Path(path)
        differ, compared, summary = [], 0, ""
        try:
            with transaction.atomic(), tempfile.TemporaryDirectory() as out:
                report = import_site(root, site)
                summary = report.summary()
                export = export_site(site, out, include_drafts=True)
                read = list(report.created)
                for sidecars in ImportedSource.objects.filter(site_key=site).values_list("sidecars", flat=True):
                    read.extend(sidecars)
                for rel in read:
                    compared += 1
                    exported = Path(out) / rel
                    if not exported.is_file() or exported.read_bytes() != (root / rel).read_bytes():
                        differ.append(rel)
                summary += f"; {export.summary()}"
                raise _Rollback
        except _Rollback:
            pass
        self.stdout.write(summary)
        for rel in differ:
            self.stdout.write(f"  differs: {rel}")
        self.stdout.write(f"{compared - len(differ)}/{compared} file(s) identical after the round trip")
        if differ:
            raise SystemExit(1)
