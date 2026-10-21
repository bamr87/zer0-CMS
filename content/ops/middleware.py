"""Three middlewares, outermost first in `MIDDLEWARE`:

- `RequestIdMiddleware` binds the request id before anything else runs, so a
  static file, a security redirect or a crash deep inside all carry it, and
  stamps `X-Request-Id` and `X-App-Version` on every response.
- `AccessLogMiddleware` writes one line per request at completion (method,
  path, status, duration) — the probes excepted, or they would be most of
  the log.
- `SecurityHeadersMiddleware` adds the headers Django's SecurityMiddleware
  does not: `Permissions-Policy` and a report-only CSP (the Wagtail admin
  inlines scripts, so enforcing one is a later step after the reports are
  read).
"""

import logging
import time

from django.conf import settings

from . import context, sentry

access_log = logging.getLogger("ops.access")
PROBES = ("/healthz", "/readyz")


class RequestIdMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = context.sanitize(request.headers.get("X-Request-Id")) or context.new_request_id()
        request.request_id = request_id
        with context.bind(request_id):
            sentry.tag_request(request_id)
            response = self.get_response(request)
            response["X-Request-Id"] = request_id
            response["X-App-Version"] = settings.APP_VERSION
            return response


class AccessLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        response = self.get_response(request)
        if request.path not in PROBES:
            access_log.info(
                "%s %s %s",
                request.method,
                request.path,
                response.status_code,
                extra={
                    "method": request.method,
                    "path": request.path,
                    "status": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                    "request_id": getattr(request, "request_id", None),
                },
            )
        return response


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "text/html" not in response.get("Content-Type", ""):
            return response
        if settings.PERMISSIONS_POLICY and not response.has_header("Permissions-Policy"):
            response["Permissions-Policy"] = settings.PERMISSIONS_POLICY
        if settings.CSP_REPORT_ONLY and not response.has_header("Content-Security-Policy-Report-Only"):
            policy = settings.CSP_REPORT_ONLY
            if settings.CSP_REPORT_URI:
                policy = f"{policy}; report-uri {settings.CSP_REPORT_URI}"
            response["Content-Security-Policy-Report-Only"] = policy
        return response
