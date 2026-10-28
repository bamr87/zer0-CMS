"""`manage.py consume_events`: handle a stream's events through a consumer group —
the experience plane's (`zer0:app`, group `content`, the default; nothing publishes there since the
Rails app was deleted, ADR 0008) or, with `--own`, this plane's own (`EVENTS_STREAM`, where the relay
writes them: group `outboxdesk`, the outbox desk's belt publisher, and group `platform`, the compose
`events` service, which hands them to distribution and to the automations an event fires).

Every installed app's `consumers` module registers its handlers
(`autodiscover_modules`), and the automations' are registered by a call
(`automations.consumers.register`), so no other consumer's test sees them; each
handler runs once per event (outbox/consumers.py). The command loops until
interrupted. A read blocks for up to five seconds (`consume_stream`), so the
connection waits longer than that: redis-py's own default of five seconds would
end the first quiet read with a timeout.
"""

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import autodiscover_modules

from outbox.consumers import consume_stream

SOCKET_TIMEOUT = 30  # seconds a read may wait on the socket, well past the stream's five-second block


class Command(BaseCommand):
    help = "Consume events from a stream (the experience plane's by default, or --own: this plane's own)."

    def add_arguments(self, parser):
        parser.add_argument("--stream", default="zer0:app")
        parser.add_argument("--own", action="store_true", help="read this plane's own stream (EVENTS_STREAM)")
        parser.add_argument("--group", default="content")
        parser.add_argument("--name", default="content-1")
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, stream, own, group, name, once=False, **options):
        import redis

        from automations.consumers import register

        autodiscover_modules("consumers")  # registers the handlers: graph's, the outbox desk's, distribution's, …
        register()  # the automations' (automations/consumers.py)

        stream = settings.EVENTS_STREAM if own else stream
        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=SOCKET_TIMEOUT)
        while True:
            handled = consume_stream(client, stream, group, name)
            if handled:
                self.stdout.write(f"handled {handled} event(s)")
            if once:
                return
