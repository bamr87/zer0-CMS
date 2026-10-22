"""`manage.py import_parodynews --dump FILE [--force]`: import barodybroject's
`dumpdata parodynews` output (importers/parodynews.py). A post's page or an AI
row a person changed here since the last import is reported as a conflict and
left alone, unless `--force`."""

from django.core.management.base import BaseCommand

from importers.parodynews import import_dump


class Command(BaseCommand):
    help = "Import parodynews posts, their versions and its AI tables."

    def add_arguments(self, parser):
        parser.add_argument("--dump", required=True)
        parser.add_argument("--force", action="store_true", help="Overwrite what was changed here since the import.")

    def handle(self, *args, dump, force=False, **options):
        self.stdout.write(import_dump(dump, force=force).summary())
