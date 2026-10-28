"""`HashedToken`: the bearer token both kinds of caller carry — an agent's
(`agents.AgentToken`, `zer0_…`) and a person's (`accounts.UserToken`,
`zer0u_…`) — written once.

Only a SHA-256 digest is stored, and the raw token is returned once, by
`mint`. `authenticate` refuses an unknown, revoked, out-of-date or inactive
token. It records a use at most once per `USED_EVERY`, after the request's
transaction commits and never as the request's failure. A write on every
request inside `ATOMIC_REQUESTS` held a lock for the whole request, so a
client's parallel requests failed on SQLite and ran one at a time on Postgres.
`raw` is a sensitive variable wherever it is a local, so an error report shows
stars, and `ops.logging` redacts both token shapes everywhere else.
"""

import hashlib
import secrets
from datetime import timedelta

from django.db import models, transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

USED_EVERY = timedelta(minutes=5)


class HashedToken(models.Model):
    PREFIX = ""  # each model's own, e.g. "zer0_"

    name = models.CharField(max_length=120)
    prefix = models.CharField(max_length=12, db_index=True)
    key_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True

    def __str__(self):
        return f"{self.name} ({self.prefix}…)"

    @staticmethod
    @sensitive_variables("raw")
    def digest(raw: str) -> str:
        return hashlib.sha256(raw.encode()).hexdigest()

    @classmethod
    @sensitive_variables("raw")
    def mint(cls, **fields):
        """A new row and its raw token, which is neither stored nor shown again."""
        raw = cls.PREFIX + secrets.token_urlsafe(32)
        shown = cls._meta.get_field("prefix").max_length
        return cls.objects.create(prefix=raw[:shown], key_hash=cls.digest(raw), **fields), raw

    @classmethod
    @sensitive_variables("raw")
    def authenticate(cls, raw: str):
        token = cls.objects.select_related("user").filter(key_hash=cls.digest(raw), revoked_at__isnull=True).first()
        now = timezone.now()
        if token is None or not token.user.is_active or not token.in_date(now):
            return None
        if token.last_used_at is None or now - token.last_used_at >= USED_EVERY:
            transaction.on_commit(lambda: cls.objects.filter(pk=token.pk).update(last_used_at=now), robust=True)
        return token

    def in_date(self, now) -> bool:
        """Whether the token may still be used at `now`; one that never expires always may."""
        return True
