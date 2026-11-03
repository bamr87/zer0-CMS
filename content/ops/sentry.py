"""Error reporting (UPS-OPS-13): on when `SENTRY_DSN` is set, otherwise every
function here is a no-op. Events are tagged with the release and the request
id, carry no personal data by default, and go through the same redaction as
the logs before they leave the process. Sentry's own scrubber runs first and
drops a value by its key, nested dicts included: the headers a channel client
signs a request with are a local of every frame below it, and an OAuth token
has no shape `redact()` could find."""

from django.conf import settings

# Sentry's denylist plus the names the platform's credentials go by.
DENIED = ("access_token", "refresh_token", "client_secret", "credential")


def _scrub(event, hint=None):
    """Every string in the event through the logs' redaction: the message, each
    exception's value, and the variables of every frame, which carry what a
    function held when it failed — a token it was checking, for one."""
    from .logging import redact

    if isinstance(event, str):
        return redact(event)
    if isinstance(event, dict):
        return {key: _scrub(value) for key, value in event.items()}
    if isinstance(event, list):
        return [_scrub(value) for value in event]
    return event


def options() -> dict:
    """What `init` gives `sentry_sdk.init`; a test builds a client from the same."""
    from sentry_sdk.scrubber import DEFAULT_DENYLIST, EventScrubber

    return {
        "dsn": settings.SENTRY_DSN,
        "release": f"{settings.APP_NAME}@{settings.APP_VERSION}",
        "environment": settings.SENTRY_ENVIRONMENT,
        "send_default_pii": False,
        "traces_sample_rate": settings.SENTRY_TRACES_SAMPLE_RATE,
        "event_scrubber": EventScrubber(denylist=[*DEFAULT_DENYLIST, *DENIED], recursive=True),
        "before_send": _scrub,
    }


def init() -> bool:
    if not getattr(settings, "SENTRY_DSN", ""):
        return False
    import sentry_sdk

    sentry_sdk.init(**options())
    return True


def tag_request(request_id: str) -> None:
    if not getattr(settings, "SENTRY_DSN", ""):
        return
    import sentry_sdk

    if sentry_sdk.is_initialized():
        sentry_sdk.set_tag("request_id", request_id)
