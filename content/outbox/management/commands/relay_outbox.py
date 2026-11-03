"""`manage.py relay_outbox [--once]`: publish undelivered events to Redis Streams.

The compose `relay` service runs it in a loop that waits out a database or Redis blip and touches the `relay`
heartbeat after every pass (outbox/loop.py); `--once` drains one batch and exits, for cron or a test.
"""

from django.core.management.base import BaseCommand

from outbox import loop
from outbox.relay import relay_pending


class Command(BaseCommand):
    help = "Relay outbox events to the event bus."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--batch", type=int, default=100)
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, once=False, batch=100, interval=2.0, **options):
        def relay() -> int:
            sent = relay_pending(batch=batch)
            if sent:
                self.stdout.write(f"relayed {sent} event(s)")
            return sent

        loop.run(relay, heartbeat="relay", once=once, idle=interval)
