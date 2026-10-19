"""`manage.py import_barodybroject --dump FILE`: import barodybroject's
`dumpdata parodynews` output (importers/barodybroject.py)."""

from django.core.management.base import BaseCommand

from importers.barodybroject import import_dump


class Command(BaseCommand):
    help = "Import barodybroject posts, their versions and its assistants."

    def add_arguments(self, parser):
        parser.add_argument("--dump", required=True)

    def handle(self, *args, dump, **options):
        self.stdout.write(import_dump(dump).summary())
