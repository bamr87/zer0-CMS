"""`manage.py consume_events`: handle the Rails plane's events (`zer0:app`).

Each handler runs once per event (outbox/consumers.py); the command loops
until interrupted.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from outbox.consumers import consume_stream


class Command(BaseCommand):
    help = "Consume events from the experience plane's stream."

    def add_arguments(self, parser):
        parser.add_argument("--stream", default="zer0:app")
        parser.add_argument("--group", default="content")
        parser.add_argument("--name", default="content-1")
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, stream, group, name, once=False, **options):
        import redis

        import graph.consumers  # noqa: F401 — registers the handlers

        client = redis.Redis.from_url(settings.REDIS_URL)
        while True:
            handled = consume_stream(client, stream, group, name)
            if handled:
                self.stdout.write(f"handled {handled} event(s)")
            if once:
                return
