"""A liveness file for the roles that answer no HTTP: the outbox relay, the event consumers and beat.

A role's loop calls `touch(name)` after every pass it finishes, and its compose healthcheck runs
`python -m ops.heartbeat <name> <max-age-seconds>`, which exits 0 while the file is younger than that and 1 when it
is older or missing. Nothing here imports Django, so the probe costs one Python start, not a Django boot. The files
live in `HEARTBEAT_DIR` (the system's temporary directory when unset), read here rather than in settings because the
probe runs without them; each role has a container of its own, so a name only has to be unique on one machine.
"""

import logging
import os
import sys
import tempfile
import time
from pathlib import Path

log = logging.getLogger(__name__)


def path(name: str) -> Path:
    return Path(os.environ.get("HEARTBEAT_DIR") or tempfile.gettempdir()) / f"zer0-{name}.heartbeat"


def touch(name: str) -> None:
    """Record that `name` finished a pass. A file that cannot be written is logged, never raised: the probe then
    reports the role unhealthy, which is better than a loop that stops working over its own liveness file."""
    try:
        path(name).touch()
    except OSError as exc:
        log.warning("heartbeat: %s not written (%s)", path(name), exc)


def age(name: str) -> float | None:
    """Seconds since `name` last finished a pass, or None if it never has."""
    try:
        return time.time() - path(name).stat().st_mtime
    except FileNotFoundError:
        return None


def main(argv: list[str]) -> int:
    name, max_age = argv[0], float(argv[1])
    seconds = age(name)
    if seconds is None:
        print(f"{name}: no heartbeat at {path(name)}")
        return 1
    if seconds > max_age:
        print(f"{name}: last pass {seconds:.0f} s ago (allowed {max_age:.0f} s)")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
