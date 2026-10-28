"""A person's API tokens: issue, list and revoke — the rules in one place, for
`manage.py user_token` today and the account menu (PLAN G3) next.

A token expires after `DEFAULT_DAYS` unless the issuer says otherwise. An
agent never gets one (agents have `AgentToken`s), and a superuser's — every
permission, unscoped — is issued only when the issuer asks for it by name.
"""

from datetime import timedelta

from django.utils import timezone

from .models import UserToken

DEFAULT_DAYS = 90


class TokenError(ValueError):
    """A token that cannot be issued or revoked; the message says why."""


def issue(user, name: str, days: int | None = DEFAULT_DAYS, superuser: bool = False) -> tuple[UserToken, str]:
    """A new token for `user` and its raw value, shown once. It expires after
    `days` days; `None` or `0` is a token that never expires."""
    if user.username.startswith("agent:"):
        raise TokenError("an agent's token is an AgentToken (manage.py agent_token)")
    if user.is_superuser and not superuser:
        raise TokenError(
            f"{user.username} is a superuser, and their token would carry every permission; "
            "issue it with --superuser if that is what you mean"
        )
    expires_at = timezone.now() + timedelta(days=days) if days else None
    return UserToken.mint(name=name, user=user, expires_at=expires_at)


def tokens_of(user):
    """`user`'s own tokens, newest first."""
    return UserToken.objects.visible_to(user).filter(user=user).order_by("-created_at")


def revoke(user, prefix: str) -> UserToken:
    """Revoke `user`'s one active token that starts with `prefix`."""
    found = tokens_of(user).filter(prefix__startswith=prefix[:14], revoked_at__isnull=True)
    if found.count() != 1:
        raise TokenError(f"{found.count()} active tokens of {user.username} start with {prefix}; name exactly one")
    token = found.get()
    token.revoked_at = timezone.now()
    token.save(update_fields=["revoked_at"])
    return token
