"""`manage.py consume_events`: handle a stream's events through a consumer group —
the experience plane's (`zer0:app`, group `content`, the default; nothing publishes there since the
Rails app was deleted, ADR 0008) or this plane's own (`zer0:content`, e.g. group `outboxdesk`).

Every installed app's `consumers` module registers its handlers
(`autodiscover_modules`); each handler runs once per event (outbox/consumers.py).
The command loops until interrupted.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import autodiscover_modules

from outbox.consumers import consume_stream

BLOCK_MS = 5000  # how long one read waits on an idle stream


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
        # An idle stream holds the read for the whole block, so the socket timeout must outlast it; redis-py 8
        # defaults socket_timeout to 5 s, the same as the block, and the process then died on its first quiet spell.
        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=BLOCK_MS / 1000 + 10)
        while True:
            handled = consume_stream(client, stream, group, name, block_ms=BLOCK_MS)
            if handled:
                self.stdout.write(f"handled {handled} event(s)")
            if once:
                return
