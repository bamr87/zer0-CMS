"""The loop `relay_outbox` and `consume_events` run in, which outlives a database or Redis blip.

Both commands run for as long as their container does. A pass that fails because Postgres is restarting or in
recovery, or because Redis cannot be reached (`TRANSIENT`), is logged; the connections Django holds are dropped if the
error broke them (`close_old_connections`), and the loop waits 1, 2, 4 … 30 seconds before the next pass instead of
ending the process. A good pass starts the wait over. Any other error still ends the process: that is a bug, and
retrying it forever would only hide it. Every pass that finishes touches the role's heartbeat (ops/heartbeat.py),
which its compose healthcheck reads; `once` runs a single pass for cron or a test, and a blip in it is raised.
"""

import logging
import time
from collections.abc import Callable

from django.db import InterfaceError, OperationalError, close_old_connections
from redis.exceptions import ConnectionError as RedisConnectionError
from redis.exceptions import TimeoutError as RedisTimeoutError

from ops import heartbeat as heartbeats

log = logging.getLogger(__name__)

TRANSIENT = (OperationalError, InterfaceError, RedisConnectionError, RedisTimeoutError)
FIRST_DELAY = 1.0  # seconds before the pass after a first blip
MAX_DELAY = 30.0  # the longest wait between passes while the blip lasts

sleep = time.sleep  # module-level, so a test can stand in for it


def run(step: Callable[[], int], *, heartbeat: str, once: bool = False, idle: float = 0.0) -> None:
    """Call `step()` until the process is stopped; after a pass that did nothing (it returned 0), wait `idle` seconds."""
    delay = 0.0
    while True:
        try:
            done = step()
        except TRANSIENT as exc:
            if once:
                raise
            delay = min(MAX_DELAY, delay * 2 or FIRST_DELAY)
            log.warning("%s: %s: %s; next pass in %g s", heartbeat, type(exc).__name__, exc, delay)
            close_old_connections()
            sleep(delay)
            continue
        delay = 0.0
        if once:
            return
        heartbeats.touch(heartbeat)
        if not done and idle:
            sleep(idle)
