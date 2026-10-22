"""Error reporting (UPS-OPS-13): on when `SENTRY_DSN` is set, otherwise every
function here is a no-op. Events are tagged with the release and the request
id, carry no personal data by default, and go through the same redaction as
the logs before they leave the process."""

from django.conf import settings


def _scrub(event, hint):
    from .logging import redact

    if isinstance(event.get("message"), str):
        event["message"] = redact(event["message"])
    entry = event.get("logentry") or {}
    if isinstance(entry.get("message"), str):
        entry["message"] = redact(entry["message"])
    for value in (event.get("exception") or {}).get("values") or []:
        if isinstance(value.get("value"), str):
            value["value"] = redact(value["value"])
    return event


def init() -> bool:
    dsn = getattr(settings, "SENTRY_DSN", "")
    if not dsn:
        return False
    import sentry_sdk

    sentry_sdk.init(
        dsn=dsn,
        release=f"{settings.APP_NAME}@{settings.APP_VERSION}",
        environment=settings.SENTRY_ENVIRONMENT,
        send_default_pii=False,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        before_send=_scrub,
    )
    return True


def tag_request(request_id: str) -> None:
    if not getattr(settings, "SENTRY_DSN", ""):
        return
    import sentry_sdk

    if sentry_sdk.is_initialized():
        sentry_sdk.set_tag("request_id", request_id)
