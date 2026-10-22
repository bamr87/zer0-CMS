"""The request id: one per HTTP request, bound for its duration so every log
line, error body and JSON-RPC error written while handling it carries it.

It is the client-facing correlation id (`X-Request-Id`, echoed when a client
sent one), distinct from the W3C trace id `agents.tracing` carries across
planes: a trace id must be 32 hex characters, a client's request id can be
anything, so neither can stand in for the other and both are logged.
"""

import contextlib
import contextvars
import re
import uuid

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("zer0_request_id", default=None)

# What an incoming id may look like: a header value is attacker-controlled and
# ends up in log lines, so anything else is replaced rather than echoed.
SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def new_request_id() -> str:
    return str(uuid.uuid4())


def current_request_id() -> str | None:
    return _request_id.get()


def sanitize(value: str | None) -> str | None:
    """The incoming id when it is safe to echo and log, else None."""
    value = (value or "").strip()
    return value if SAFE.match(value) else None


@contextlib.contextmanager
def bind(request_id: str):
    token = _request_id.set(request_id)
    try:
        yield request_id
    finally:
        _request_id.reset(token)
