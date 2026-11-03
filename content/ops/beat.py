"""Celery beat's scheduler, with a heartbeat (W1-11).

Beat is the one long-running role with no loop of the platform's own, so nothing showed that it still ticked: a dead
beat stopped scheduled publishing and every sweep without a word. `HeartbeatScheduler` is Celery's own persistent
scheduler that touches the `beat` heartbeat (ops/heartbeat.py) on every tick; beat ticks at least once a minute while
a schedule runs every minute, and at least every five minutes in any case (its maximum interval). The compose `beat`
service runs it with `--scheduler ops.beat.HeartbeatScheduler` and checks the file's age.
"""

from celery.beat import PersistentScheduler

from . import heartbeat


class HeartbeatScheduler(PersistentScheduler):
    def tick(self, *args, **kwargs):
        heartbeat.touch("beat")
        return super().tick(*args, **kwargs)
