"""The three probes (UPS-BE-10, BE-11).

Plain Django views, not DRF: nothing — no authentication class, throttle or
renderer — should stand between an orchestrator and the answer. They opt out
of `ATOMIC_REQUESTS` because a liveness probe must answer while the database
is down, and a readiness probe reports that state rather than failing to open
a transaction around it.
"""

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_GET

from .readiness import run_checks


def _json(payload, status=200):
    response = JsonResponse(payload, status=status)
    response["Cache-Control"] = "no-store"
    return response


@transaction.non_atomic_requests
@require_GET
def healthz(request):
    """Liveness: the process answers HTTP. Touches nothing."""
    return _json({"status": "ok"})


@transaction.non_atomic_requests
@require_GET
def readyz(request):
    """Readiness: every dependency answers, else 503 and which one did not."""
    checks = run_checks()
    ok = all(state == "ok" for state in checks.values())
    return _json({"status": "ok" if ok else "degraded", "checks": checks}, status=200 if ok else 503)


@transaction.non_atomic_requests
@require_GET
def version(request):
    return _json(
        {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "commit": settings.GIT_SHA,
            "built_at": settings.BUILT_AT,
        }
    )
