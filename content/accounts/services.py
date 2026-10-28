"""A person's API tokens: issue, list and revoke — the rules in one place, for
the account menu (`/api/v2/account/tokens/`, accounts/api.py) and
`manage.py user_token`.

A token expires after `DEFAULT_DAYS` unless the issuer says otherwise (the
account menu offers 1 to `MAX_DAYS`; only an operator's command line issues
one that never expires). It carries its scopes — `read`, and `write` to change
anything — and always `read`. An agent never gets one (agents have
`AgentToken`s), and a superuser's — every permission, unscoped by Wagtail — is
issued only when the issuer asks for it by name.
"""

from datetime import timedelta

from django.utils import timezone

from .models import READ, SCOPES, UserToken

DEFAULT_DAYS = 90
MAX_DAYS = 365


class TokenError(ValueError):
    """A token that cannot be issued or revoked; the message says why."""


def issue(
    user, name: str, days: int | None = DEFAULT_DAYS, superuser: bool = False, scopes=SCOPES
) -> tuple[UserToken, str]:
    """A new token for `user` and its raw value, shown once. It expires after
    `days` days; `None` or `0` is a token that never expires."""
    if user.username.startswith("agent:"):
        raise TokenError("an agent's token is an AgentToken (manage.py agent_token)")
    if user.is_superuser and not superuser:
        raise TokenError(
            f"{user.username} is a superuser, and their token would carry every permission; "
            "issue it with --superuser if that is what you mean"
        )
    unknown = set(scopes) - set(SCOPES)
    if unknown:
        raise TokenError(f"unknown scopes {sorted(unknown)}; a token's scopes are {', '.join(SCOPES)}")
    if READ not in scopes:
        raise TokenError("every token can read; a token's scopes include read")
    expires_at = timezone.now() + timedelta(days=days) if days else None
    return UserToken.mint(name=name, user=user, expires_at=expires_at, scopes=[s for s in SCOPES if s in scopes])


def tokens_of(user):
    """`user`'s own tokens, newest first."""
    return UserToken.objects.visible_to(user).filter(user=user).order_by("-created_at")


def revoke(user, prefix: str, by=None) -> UserToken:
    """Revoke `user`'s one active token that starts with `prefix`; `by`, when known, is who did (Wagtail's log)."""
    found = tokens_of(user).filter(prefix__startswith=prefix[:14], revoked_at__isnull=True)
    if found.count() != 1:
        raise TokenError(f"{found.count()} active tokens of {user.username} start with {prefix}; name exactly one")
    token = found.get()
    token.revoke(by=by)
    return token


def revoke_by_id(user, public_id, by=None) -> UserToken | None:
    """Revoke `user`'s own token with this public id; None when they have none (a 404, never someone else's)."""
    token = tokens_of(user).filter(public_id=public_id).first()
    if token is not None and token.revoked_at is None:
        token.revoke(by=by)
    return token
