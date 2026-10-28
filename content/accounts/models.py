"""`UserToken`: a person's API token, for a client that is not a browser.

The studio signs in with a session; the VS Code extension (PLAN G10) cannot
hold one, so it sends `Authorization: Bearer zer0u_<…>` from the editor's
secret storage and the platform treats the request as that person — the same
Wagtail permissions, the same `IsPerson` endpoints. What it shares with an
agent's token (the hash, the one-time raw token, authentication) is
`accounts.tokens.HashedToken`; what is a person's is here: an expiry, a public
id, and `visible_to`, the one scope a token is read through. Issuing, listing
and revoking are `accounts.services`. PLAN G3 grows this (scopes, the account
menu).
"""

import uuid

from django.conf import settings
from django.db import models

from .tokens import HashedToken


class UserTokenQuerySet(models.QuerySet):
    def visible_to(self, user):
        """A person's own tokens, every token for a superuser, none for anyone signed out or inactive."""
        if user is None or not user.is_authenticated or not user.is_active:
            return self.none()
        return self if user.is_superuser else self.filter(user=user)


class UserToken(HashedToken):
    PREFIX = "zer0u_"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    name = models.CharField(max_length=120, help_text="Where it is used, e.g. “VS Code on my laptop”.")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_tokens")
    prefix = models.CharField(max_length=14, db_index=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    objects = UserTokenQuerySet.as_manager()

    def in_date(self, now) -> bool:
        return self.expires_at is None or self.expires_at > now
