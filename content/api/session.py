"""Who is signed in: `GET /api/v2/me` — the person (or `authenticated: false`),
their permissions, and a CSRF token (the cookie set with it).

Signing in, out and everything around it (sign-up, codes, MFA, passkeys, the
session list) is django-allauth's headless API at `/_allauth/browser/v1/…`
(accounts/README.md), which the studio's auth adapter (web/studio/src/auth.tsx)
calls; this endpoint stays because every studio screen reads the person and
their permissions from it, and because it hands an anonymous browser the CSRF
cookie allauth's endpoints ask for. A caller with a token gets its person
here too — the extension asks who its token is.
"""

from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ops.openapi import ERROR_RESPONSES

from .serializers import MeSerializer


def me_payload(request) -> dict:
    user = request.user
    signed_in = bool(user and user.is_authenticated)
    return {
        "authenticated": signed_in,
        "user": user if signed_in else None,
        "permissions": sorted(user.get_all_permissions()) if signed_in else [],
        "csrf_token": get_token(request._request),
    }


@extend_schema(operation_id="me", summary="Who is signed in", responses={200: MeSerializer, **ERROR_RESPONSES})
@api_view(["GET"])
@permission_classes([AllowAny])
def me(request):
    return Response(MeSerializer(me_payload(request)).data)
