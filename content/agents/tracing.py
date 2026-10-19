"""One trace id per unit of work, carried across both planes.

A request that arrives with a W3C `traceparent` header keeps its trace id; any
other request, task or command gets a new one. The id is stored on every
`AgentRun` and on every outbox event (as a CloudEvents `traceparent`), and is
echoed back in the response header, so a run started from Rails can be found
from either side. When OpenTelemetry is installed, `span()` opens a real span;
otherwise it is a no-op and the id is still recorded.
"""

import contextlib
import contextvars
import re
import uuid

_trace_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("zer0_trace_id", default=None)
TRACEPARENT = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


def new_trace_id() -> str:
    return uuid.uuid4().hex


def current_trace_id() -> str | None:
    return _trace_id.get()


@contextlib.contextmanager
def trace(trace_id: str | None = None):
    """Run the block under `trace_id` (or the current one, or a new one)."""
    token = _trace_id.set(trace_id or _trace_id.get() or new_trace_id())
    try:
        yield _trace_id.get()
    finally:
        _trace_id.reset(token)


def trace_id_from_header(value: str | None) -> str | None:
    match = TRACEPARENT.match((value or "").strip())
    return match.group(1) if match and match.group(1) != "0" * 32 else None


def traceparent(trace_id: str) -> str:
    return f"00-{trace_id}-{'0' * 15}1-01"


@contextlib.contextmanager
def span(name: str, **attributes):
    try:
        from opentelemetry import trace as otel
    except ImportError:
        yield None
        return
    with otel.get_tracer("zer0.content").start_as_current_span(name) as current:
        current.set_attribute("zer0.trace_id", current_trace_id() or "")
        for key, value in attributes.items():
            if value is not None:
                current.set_attribute(
                    f"zer0.{key}", value if isinstance(value, (str, int, float, bool)) else str(value)
                )
        yield current


class TraceMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        incoming = trace_id_from_header(request.headers.get("traceparent"))
        with trace(incoming or new_trace_id()) as trace_id:
            response = self.get_response(request)
            response["traceparent"] = traceparent(trace_id)
            return response
