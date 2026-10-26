"""One error envelope for every non-2xx the platform's APIs return (UPS-BE-20):

    {"error": {"code": "<domain>.<reason>", "message": "...", "status": 404,
               "details": [...], "request_id": "...", "retry_after": null}}

`ApiError` is what a view raises; `drf_exception_handler` turns it — and every
DRF exception — into the envelope; the Django handlers below do the same for
what never reaches a DRF view (an unknown path, a CSRF failure, a crash) when
the request is for an API path or asks for JSON. HTML paths keep Django's
pages. A crash never leaks its traceback: the body says `internal.error` and
the request id, and the log line with the same id holds the rest.

Code taxonomy (ops/README.md): `auth.required`, `auth.invalid_token`,
`auth.forbidden`, `auth.csrf_failed`, `auth.invalid_credentials`, `request.malformed`,
`request.method_not_allowed`, `request.unsupported_media_type`,
`request.not_acceptable`, `validation.failed`, `resource.not_found`,
`resource.conflict`, `resource.locked`, `rate.limited`, `upstream.unavailable`,
`internal.error`.
"""

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.http import Http404, JsonResponse
from django.views import defaults
from django.views.csrf import csrf_failure as django_csrf_failure
from rest_framework import exceptions as drf
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_default_handler
from rest_framework.views import set_rollback

from .context import current_request_id

# Paths whose errors are JSON even when Django, not DRF, answers them.
JSON_ERROR_PREFIXES = ("/api/", "/graphql/", "/mcp/", "/healthz", "/readyz", "/version")


class ApiError(Exception):
    status = 400
    code = "request.invalid"

    def __init__(
        self, message: str, *, code: str | None = None, status: int | None = None, details=(), retry_after=None
    ):
        super().__init__(message)
        self.message = message
        self.code = code or type(self).code
        self.status = status or type(self).status
        self.details = list(details)
        self.retry_after = retry_after


class Invalid(ApiError):
    status = 422
    code = "validation.failed"


class Forbidden(ApiError):
    status = 403
    code = "auth.forbidden"


class NotFound(ApiError):
    status = 404
    code = "resource.not_found"


class Conflict(ApiError):
    status = 409
    code = "resource.conflict"


class Locked(Conflict):
    """A Wagtail lock keeps the caller from changing the page; the message says whose."""

    code = "resource.locked"


class Unavailable(ApiError):
    status = 503
    code = "upstream.unavailable"


def envelope(code: str, message: str, status: int, *, details=(), retry_after=None) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "status": status,
            "details": list(details),
            "request_id": current_request_id(),
            "retry_after": retry_after,
        }
    }


# ── DRF ────────────────────────────────────────────────────────────────────

_CODES = (
    (drf.NotAuthenticated, "auth.required"),
    (drf.AuthenticationFailed, "auth.invalid_token"),
    (drf.PermissionDenied, "auth.forbidden"),
    (drf.NotFound, "resource.not_found"),
    (drf.MethodNotAllowed, "request.method_not_allowed"),
    (drf.ParseError, "request.malformed"),
    (drf.UnsupportedMediaType, "request.unsupported_media_type"),
    (drf.NotAcceptable, "request.not_acceptable"),
    (drf.Throttled, "rate.limited"),
    (drf.ValidationError, "validation.failed"),
)


def _flatten(detail, field=None) -> list[dict]:
    """DRF's nested `detail` as a flat list of {field, code, message}."""
    if isinstance(detail, dict):
        found = []
        for key, value in detail.items():
            name = None if key == "non_field_errors" else (f"{field}.{key}" if field else str(key))
            found.extend(_flatten(value, name))
        return found
    if isinstance(detail, list):
        return [item for value in detail for item in _flatten(value, field)]
    code = getattr(detail, "code", "invalid")
    return [{"field": field, "code": str(code), "message": str(detail)}]


def _message(exc) -> str:
    if isinstance(exc, drf.ValidationError):
        return "validation failed"
    detail = exc.detail
    return str(detail) if isinstance(detail, str) else str(exc.default_detail)


def drf_exception_handler(exc, context):
    if isinstance(exc, ApiError):
        set_rollback()
        return Response(
            envelope(exc.code, exc.message, exc.status, details=exc.details, retry_after=exc.retry_after),
            status=exc.status,
        )
    response = drf_default_handler(exc, context)
    if response is None:
        return None  # a crash: Django's 500 path logs it and `server_error` answers
    if isinstance(exc, Http404):
        exc = drf.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf.PermissionDenied()
    code = next((code for cls, code in _CODES if isinstance(exc, cls)), "request.invalid")
    if isinstance(exc, drf.PermissionDenied) and str(exc.detail).startswith("CSRF Failed"):
        code = "auth.csrf_failed"  # DRF's SessionAuthentication says it only in the message
    status = response.status_code
    details: list = []
    retry_after = None
    if isinstance(exc, drf.ValidationError):
        status = 422
        details = _flatten(exc.detail)
    elif isinstance(exc, drf.Throttled) and exc.wait is not None:
        retry_after = int(exc.wait)
    response.data = envelope(code, _message(exc), status, details=details, retry_after=retry_after)
    response.status_code = status
    return response


# ── Django's own error paths ───────────────────────────────────────────────


def is_api_request(request) -> bool:
    return request.path.startswith(JSON_ERROR_PREFIXES) or "application/json" in request.headers.get("Accept", "")


def _json_or_none(request, code, status, message):
    if is_api_request(request):
        return JsonResponse(envelope(code, message, status), status=status)
    return None


def bad_request(request, exception=None):
    return _json_or_none(request, "request.malformed", 400, "bad request") or defaults.bad_request(request, exception)


def permission_denied(request, exception=None):
    return _json_or_none(request, "auth.forbidden", 403, "forbidden") or defaults.permission_denied(request, exception)


def not_found(request, exception=None):
    return _json_or_none(request, "resource.not_found", 404, "not found") or defaults.page_not_found(request, exception)


def server_error(request):
    return _json_or_none(request, "internal.error", 500, "internal error") or defaults.server_error(request)


def csrf_failure(request, reason=""):
    return _json_or_none(request, "auth.csrf_failed", 403, "CSRF check failed") or django_csrf_failure(request, reason)
