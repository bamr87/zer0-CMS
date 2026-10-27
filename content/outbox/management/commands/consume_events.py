"""`manage.py consume_events`: handle a stream's events through a consumer group —
the Rails plane's (`zer0:app`, group `content`, the default) or this plane's own
(`zer0:content`, e.g. group `outboxdesk`: the outbox desk's belt publisher).

Every installed app's `consumers` module registers its handlers
(`autodiscover_modules`); each handler runs once per event (outbox/consumers.py).
The command loops until interrupted.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import autodiscover_modules

from outbox.consumers import consume_stream


class Command(BaseCommand):
    help = "Consume events from a stream (the experience plane's by default)."

    def add_arguments(self, parser):
        parser.add_argument("--stream", default="zer0:app")
        parser.add_argument("--group", default="content")
        parser.add_argument("--name", default="content-1")
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, stream, group, name, once=False, **options):
        import redis

        autodiscover_modules("consumers")  # registers the handlers: graph's, the outbox desk's, …
        client = redis.Redis.from_url(settings.REDIS_URL)
        while True:
            handled = consume_stream(client, stream, group, name)
            if handled:
                self.stdout.write(f"handled {handled} event(s)")
            if once:
                return
