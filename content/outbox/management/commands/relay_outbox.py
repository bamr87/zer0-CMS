"""`manage.py relay_outbox [--once]`: publish undelivered events to Redis Streams.

The compose `relay` service runs it in a loop; `--once` drains one batch and
exits, for cron or a test.
"""

import time

from django.core.management.base import BaseCommand

from outbox.relay import relay_pending


class Command(BaseCommand):
    help = "Relay outbox events to the event bus."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--batch", type=int, default=100)
        parser.add_argument("--interval", type=float, default=2.0)

    def handle(self, *args, once=False, batch=100, interval=2.0, **options):
        while True:
            sent = relay_pending(batch=batch)
            if sent:
                self.stdout.write(f"relayed {sent} event(s)")
            if once:
                return
            if not sent:
                time.sleep(interval)
