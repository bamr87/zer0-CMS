"""`manage.py import_parodynews --dump FILE`: import config's
`dumpdata parodynews` output (importers/parodynews.py)."""

from django.core.management.base import BaseCommand

from importers.parodynews import import_dump


class Command(BaseCommand):
    help = "Import parodynews posts, their versions and its assistants."

    def add_arguments(self, parser):
        parser.add_argument("--dump", required=True)

    def handle(self, *args, dump, **options):
        self.stdout.write(import_dump(dump).summary())
