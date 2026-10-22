"""`UserToken`: a person's API token, for a client that is not a browser.

The studio signs in with a session; the VS Code extension (PLAN G10) cannot
hold one, so it sends `Authorization: Bearer zer0u_<…>` from the editor's
secret storage and the platform treats the request as that person — the same
Wagtail permissions, the same `IsPerson` endpoints. Like `AgentToken`, the raw
token is shown once and only its hash is kept; a token may expire, and is
revoked rather than deleted so its use stays explainable. An agent never gets
one: agents have `AgentToken`s. PLAN G3 grows this (scopes, the account menu).
"""

import hashlib
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone


class UserToken(models.Model):
    PREFIX = "zer0u_"

    name = models.CharField(max_length=120, help_text="Where it is used, e.g. “VS Code on my laptop”.")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="user_tokens")
    prefix = models.CharField(max_length=14, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    def digest(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    def issue(cls, user, name: str, expires_at=None) -> tuple["UserToken", str]:
        if user.username.startswith("agent:"):
            raise ValueError("an agent's token is an AgentToken (manage.py agent_token)")
        raw = cls.PREFIX + secrets.token_urlsafe(32)
        token = cls.objects.create(
            name=name, user=user, prefix=raw[:14], key_hash=cls.digest(raw), expires_at=expires_at
        )
        return token, raw

    @classmethod
    def authenticate(cls, raw: str):
        token = cls.objects.select_related("user").filter(key_hash=cls.digest(raw), revoked_at__isnull=True).first()
        now = timezone.now()
        if token is None or not token.user.is_active or (token.expires_at is not None and token.expires_at <= now):
            return None
        cls.objects.filter(pk=token.pk).update(last_used_at=now)
        return token
