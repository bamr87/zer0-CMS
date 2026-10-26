"""Signing in to the studio with a Django session: who am I, sign in, sign out.

    GET  /api/v2/me               the person signed in (or `authenticated: false`),
                                  their permissions, and a CSRF token
    POST /api/v2/session/login    username and password → a session
    POST /api/v2/session/logout   ends the session

One small module on purpose: the studio's auth adapter
(web/studio/src/auth.tsx) calls these three endpoints and nothing else, so G3
can replace them with django-allauth's headless API without touching a screen.
Both POSTs need the CSRF token — a login form is a CSRF target too — and
Django rotates the token on login, so each answer carries the current one.
Agent principals never sign in here; they use their tokens.
"""

from django.contrib.auth import authenticate
from django.contrib.auth import login as django_login
from django.contrib.auth import logout as django_logout
from django.contrib.auth.models import AnonymousUser
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from ops.errors import ApiError
from ops.openapi import ERROR_RESPONSES

from .serializers import LoginSerializer, MeSerializer


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


@extend_schema(
    operation_id="session_login",
    summary="Sign in with a username and password",
    request=LoginSerializer,
    responses={200: MeSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def login(request):
    SessionAuthentication().enforce_csrf(request)
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    user = authenticate(request._request, **serializer.validated_data)
    if user is None or user.username.startswith("agent:"):
        raise ApiError("the username or the password is not right", code="auth.invalid_credentials", status=400)
    django_login(request._request, user)
    request.user = user
    return Response(MeSerializer(me_payload(request)).data)


@extend_schema(
    operation_id="session_logout",
    summary="Sign out",
    request=None,
    responses={200: MeSerializer, **ERROR_RESPONSES},
)
@api_view(["POST"])
@permission_classes([AllowAny])
def logout(request):
    django_logout(request._request)
    request.user = AnonymousUser()
    return Response(MeSerializer(me_payload(request)).data)
