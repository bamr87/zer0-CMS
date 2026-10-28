"""`manage.py export_jekyll --site KEY --out DIR [--include-drafts]`: write a
site's pages as Jekyll Markdown (exporters/jekyll.py), and name each imported
page a person moved, whose old file the export leaves for you to delete."""

from django.core.management.base import BaseCommand

from exporters.jekyll import export_site


class Command(BaseCommand):
    help = "Export a site's pages as Jekyll files."

    def add_arguments(self, parser):
        parser.add_argument("--site", required=True)
        parser.add_argument("--out", required=True)
        parser.add_argument("--include-drafts", action="store_true")

    def handle(self, *args, site, out, include_drafts=False, **options):
        report = export_site(site, out, include_drafts=include_drafts)
        self.stdout.write(report.summary())
        for old, new in report.moved:
            self.stdout.write(f"  moved: {old} -> {new} (the old file is not deleted)")
