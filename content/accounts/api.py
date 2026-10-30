"""`/api/v2/account/`: a person's API tokens, from the studio's account menu
(and the extension's account tab, which lists and revokes them).

    GET    /api/v2/account/tokens/        the person's tokens, newest first
    POST   /api/v2/account/tokens/        issue one (201): the token and, this once, its raw value
    DELETE /api/v2/account/tokens/<id>/   revoke one of theirs (by its public id)

People only (`IsPerson`). Issuing needs a signed-in session — a token never
issues another, so one that leaks cannot make itself a successor; a token may
list its person's tokens and revoke one (its own included: the extension's
sign-out). Another person's token is a 404, as one that does not exist. The
rules are `accounts.services`; everything a person does with allauth (sign-in,
MFA, passkeys, sessions) is allauth's headless API, not this.
"""

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from api.pages import IsPerson
from ops.errors import Forbidden, Invalid, NotFound
from ops.openapi import ERROR_RESPONSES

from . import serializers as s
from . import services
from .models import UserToken


def token_json(token: UserToken, request, now) -> dict:
    current = request.auth
    return {
        "public_id": token.public_id,
        "name": token.name,
        "prefix": token.prefix,
        "scopes": token.scopes,
        "state": token.state(now),
        "created_at": token.created_at,
        "last_used_at": token.last_used_at,
        "expires_at": token.expires_at,
        "revoked_at": token.revoked_at,
        "current": isinstance(current, UserToken) and current.pk == token.pk,
    }


class Tokens(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="account_tokens_list",
        summary="The person's API tokens",
        responses={200: s.UserTokenSerializer(many=True), **ERROR_RESPONSES},
    )
    def get(self, request):
        now = timezone.now()
        rows = [token_json(token, request, now) for token in services.tokens_of(request.user)]
        return Response(s.UserTokenSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="account_tokens_issue",
        summary="Issue an API token; its raw value is in this answer only",
        request=s.IssueTokenSerializer,
        responses={201: s.IssuedTokenSerializer, **ERROR_RESPONSES},
    )
    def post(self, request):
        if isinstance(request.auth, UserToken):
            raise Forbidden("a token cannot issue another; sign in to issue one", code="auth.session_required")
        serializer = s.IssueTokenSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            token, raw = services.issue(
                request.user, name=data["name"], days=data["days"], superuser=data["superuser"], scopes=data["scopes"]
            )
        except services.TokenError as e:
            raise Invalid(str(e), code="token.refused") from e
        body = {"token": token_json(token, request, timezone.now()), "raw": raw}
        return Response(s.IssuedTokenSerializer(body).data, status=status.HTTP_201_CREATED)


class Token(APIView):
    permission_classes = [IsPerson]

    @extend_schema(
        operation_id="account_tokens_revoke",
        summary="Revoke one of the person's API tokens",
        request=None,
        responses={200: s.UserTokenSerializer, **ERROR_RESPONSES},
    )
    def delete(self, request, public_id):
        token = services.revoke_by_id(request.user, public_id, by=request.user)
        if token is None:
            raise NotFound("no such token")
        return Response(s.UserTokenSerializer(token_json(token, request, timezone.now())).data)
