"""REST authentication by agent token: `Authorization: Bearer zer0_…`.

The token resolves to its agent user; DRF then treats the request as that
user, so the same Wagtail permissions the tool registry checks apply to the
REST views. `request.auth` is the `AgentToken`, which narrows the tools a
caller may use when the token lists any.
"""

from rest_framework import authentication, exceptions

from .models import AgentToken


def bearer(header: str | None) -> str | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    return value.strip() if scheme.lower() == "bearer" and value.strip() else None


class AgentTokenAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        raw = bearer(request.headers.get("Authorization"))
        if raw is None:
            return None
        token = AgentToken.authenticate(raw)
        if token is None:
            raise exceptions.AuthenticationFailed("unknown, revoked or inactive agent token")
        return token.user, token

    def authenticate_header(self, request):
        return 'Bearer realm="zer0-content"'
