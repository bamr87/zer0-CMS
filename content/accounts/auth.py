"""REST authentication by a person's token: `Authorization: Bearer zer0u_…`.

It runs before `agents.auth.AgentTokenAuthentication` and answers only for its
own prefix, so an agent token still reaches the agent authenticator. The
request is then the token's person, with their Wagtail permissions; no CSRF
applies, because nothing a browser sends by itself carries this header.
"""

from rest_framework import authentication, exceptions

from agents.auth import bearer

from .models import UserToken


class UserTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        raw = bearer(request.headers.get("Authorization"))
        if raw is None or not raw.startswith(UserToken.PREFIX):
            return None
        token = UserToken.authenticate(raw)
        if token is None:
            raise exceptions.AuthenticationFailed("unknown, expired or revoked token")
        return token.user, token

    def authenticate_header(self, request):
        return 'Bearer realm="zer0-content"'
