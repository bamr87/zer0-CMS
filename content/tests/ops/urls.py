"""A test-only URLconf: the platform's URLs plus views that fail on demand, so
each error path can be asserted without a real endpoint that happens to fail
that way."""

from django.http import Http404
from django.urls import path
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ErrorDetail, NotAuthenticated, PermissionDenied, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from config.urls import handler400, handler403, handler404, handler500
from config.urls import urlpatterns as platform_urlpatterns
from ops.errors import ApiError

__all__ = ["handler400", "handler403", "handler404", "handler500", "urlpatterns"]


class TwoPerMinute(AnonRateThrottle):
    scope = "test"
    rate = "2/min"


@api_view(["GET"])
@permission_classes([AllowAny])
def fail(request, kind):
    if kind == "unauthenticated":
        raise NotAuthenticated()
    if kind == "forbidden":
        raise PermissionDenied()
    if kind == "missing":
        raise Http404("gone")
    if kind == "invalid":
        raise ValidationError({"title": [ErrorDetail("This field is required.", code="required")]})
    if kind == "crash":
        raise RuntimeError("boom")
    if kind == "teapot":
        raise ApiError("short and stout", code="demo.teapot", status=418)
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([TwoPerMinute])
def throttled(request):
    return Response({"ok": True})


urlpatterns = [
    path("api/v2/_test/<str:kind>/", fail),
    path("api/v2/_test-throttled/", throttled),
    *platform_urlpatterns,
]
