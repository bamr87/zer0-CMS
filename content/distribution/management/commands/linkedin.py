"""`manage.py linkedin COMMAND [--site PATH] …` — the LinkedIn lane over a
site's own files (distribution/lane/cli.py), for a content repository's CI and
a terminal. It touches no database; `manage.py linkedin --help` lists the
commands. The platform's own channels and queue are the studio's Distribution
area and `/api/v2/distribution/`.
"""

import argparse
import sys

from django.core.management.base import BaseCommand

from distribution.lane.cli import main


class Command(BaseCommand):
    help = (
        "The LinkedIn lane over a site's own files: status, plan, sources, queue, draft, approve, preview, publish, …"
    )
    requires_system_checks: list = []
    requires_migrations_checks = False

    def add_arguments(self, parser):
        parser.add_argument("argv", nargs=argparse.REMAINDER, help="COMMAND and its options (manage.py linkedin help)")

    def handle(self, *args, argv, **options):
        code = main(list(argv), out=self.stdout, err=self.stderr)
        if code:
            sys.exit(code)
