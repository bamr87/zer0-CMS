"""`manage.py consume_events`: handle the Rails plane's events (`zer0:app`) —
or, with `--own --group automations`, this plane's own (`EVENTS_STREAM`, where
the relay writes them), for the automations an event fires
(automations/consumers.py; the compose `events` service).

Each handler runs once per event (outbox/consumers.py); the command loops
until interrupted. A read blocks for up to five seconds (`consume_stream`), so
the connection waits longer than that: redis-py's own default of five seconds
would end the first quiet read with a timeout.
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from outbox.consumers import consume_stream

SOCKET_TIMEOUT = 30  # seconds a read may wait on the socket, well past the stream's five-second block


class Command(BaseCommand):
    help = "Consume events from the experience plane's stream, or (--own) this plane's own."

    def add_arguments(self, parser):
        parser.add_argument("--stream", default="zer0:app")
        parser.add_argument("--own", action="store_true", help="read this plane's own stream (EVENTS_STREAM)")
        parser.add_argument("--group", default="content")
        parser.add_argument("--name", default="content-1")
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, stream, own, group, name, once=False, **options):
        import redis

        import graph.consumers  # noqa: F401 — registers the handlers
        from automations.consumers import register

        register()

        stream = settings.EVENTS_STREAM if own else stream
        client = redis.Redis.from_url(settings.REDIS_URL, socket_timeout=SOCKET_TIMEOUT)
        while True:
            handled = consume_stream(client, stream, group, name)
            if handled:
                self.stdout.write(f"handled {handled} event(s)")
            if once:
                return
