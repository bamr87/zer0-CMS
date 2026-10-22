"""Log formatting and redaction.

`JsonFormatter` writes one JSON object per line with the fields the fleet's
log plane joins on (`ts level msg logger request_id trace_id app version`);
`TextFormatter` is the human format for development. Both go through
`redact()`, and `RedactionFilter` scrubs the message and its arguments before
any handler sees them, so a token pasted into an exception message or logged
by a library never reaches stdout. Hand-written on purpose: a JSON line is
twenty lines of code, and one fewer dependency in the image.
"""

import json
import logging
import re
import traceback
from datetime import UTC, datetime

from agents.tracing import current_trace_id

from .context import current_request_id

# Token shapes the fleet knows (UPS-OPS-12) plus this platform's own agent
# tokens, which are `zer0_` + 43 url-safe characters; the twelve-character
# prefix the admin shows is deliberately shorter than the match.
SECRET = re.compile(
    r"(?:sk-ant-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|github_pat_[A-Za-z0-9_]{8,}|AIza[A-Za-z0-9_-]{8,}|zer0_[A-Za-z0-9_-]{32,})"
)
AUTHORIZATION = re.compile(r"(?i)(authorization\s*[:=]\s*)(?:bearer|basic|token)?\s*\S+")
REDACTED = "[REDACTED]"

# Attributes every LogRecord has; anything else on a record came from `extra=`
# and is worth keeping as a field of its own.
_STANDARD = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName"}


def redact(text: str) -> str:
    return SECRET.sub(REDACTED, AUTHORIZATION.sub(rf"\1{REDACTED}", text))


def _scrub(value):
    return redact(value) if isinstance(value, str) else value


class RedactionFilter(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if isinstance(record.args, dict):
            record.args = {key: _scrub(value) for key, value in record.args.items()}
        elif isinstance(record.args, tuple):
            record.args = tuple(_scrub(value) for value in record.args)
        return True


def _request_id_of(record) -> str:
    """The record's own id, else the bound one, else the id of the request Django
    attached (its 4xx lines are written after the middleware has unwound), else `-`."""
    attached = getattr(getattr(record, "request", None), "request_id", None)
    return getattr(record, "request_id", None) or current_request_id() or attached or "-"


class ContextFilter(logging.Filter):
    """Adds `request_id` and `trace_id` to every record, `-` when unbound."""

    def filter(self, record):
        record.request_id = _request_id_of(record)
        record.trace_id = getattr(record, "trace_id", None) or current_trace_id() or "-"
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, app: str = "", version: str = ""):
        super().__init__()
        self.app = app
        self.version = version

    def format(self, record):
        line = {
            "ts": datetime.fromtimestamp(record.created, tz=UTC)
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z"),
            "level": record.levelname,
            "msg": redact(record.getMessage()),
            "logger": record.name,
            "request_id": _request_id_of(record),
            "trace_id": getattr(record, "trace_id", None) or current_trace_id() or "-",
            "app": self.app,
            "version": self.version,
        }
        for key, value in record.__dict__.items():
            # Django attaches the request object itself to its own lines; the
            # id is already above and the object is not a log field.
            if key not in _STANDARD and key not in line and key != "request" and not key.startswith("_"):
                line[key] = value
        if record.exc_info:
            line["exc"] = redact("".join(traceback.format_exception(*record.exc_info)))
        return json.dumps(line, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))
