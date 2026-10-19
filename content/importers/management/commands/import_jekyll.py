"""`manage.py import_jekyll --site KEY --path DIR [--force]`: import a Jekyll
site (importers/jekyll.py). Re-running it changes nothing that did not
change on disk; exit status 1 on any error or conflict."""

from django.core.management.base import BaseCommand

from importers.jekyll import import_site


class Command(BaseCommand):
    help = "Import a Jekyll site into Wagtail."

    def add_arguments(self, parser):
        parser.add_argument("--site", required=True)
        parser.add_argument("--path", required=True)
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, site, path, force=False, **options):
        report = import_site(path, site, force=force)
        self.stdout.write(report.summary())
        for line in report.conflicts + report.errors:
            self.stderr.write(f"  {line}")
        if report.conflicts or report.errors:
            raise SystemExit(1)
