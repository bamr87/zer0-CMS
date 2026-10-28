"""REST authentication by a person's token: `Authorization: Bearer zer0u_…`.

It runs before `agents.auth.AgentTokenAuthentication` and answers only for its
own prefix, so an agent token still reaches the agent authenticator. The
request is then the token's person, with their Wagtail permissions; no CSRF
applies, because nothing a browser sends by itself carries this header. A
token without the `write` scope may only read: any request that is not GET,
HEAD or OPTIONS is refused here, before the view, whatever view it is — so no
endpoint has to remember. GraphQL applies the same rule to mutations
(api/views.py).
"""

from django.views.decorators.debug import sensitive_variables
from rest_framework import authentication, exceptions

from agents.auth import bearer

from .models import WRITE, UserToken

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
READ_ONLY = "this token may only read; issue one with the write scope (the account menu) to change anything"


class UserTokenAuthentication(authentication.BaseAuthentication):
    @sensitive_variables("raw")
    def authenticate(self, request):
        raw = bearer(request.headers.get("Authorization"))
        if raw is None or not raw.startswith(UserToken.PREFIX):
            return None
        token = UserToken.authenticate(raw)
        if token is None:
            raise exceptions.AuthenticationFailed("unknown, expired or revoked token")
        if request.method not in SAFE_METHODS and not token.allows(WRITE):
            raise exceptions.PermissionDenied(READ_ONLY)
        return token.user, token

    def authenticate_header(self, request):
        return 'Bearer realm="zer0-content"'
