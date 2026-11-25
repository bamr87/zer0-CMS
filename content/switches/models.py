"""`SwitchConfig`: the one row the content switches keep (switches/README.md).

The content outlets — the repositories whose GitHub Actions content loops the
studio shows and flips — and the GitHub credential the platform reads and
writes their Actions variables with. The switches themselves are not stored
here: the hub's switch map (bamr87/bamr87 `_data/fleet.yml` `switches:`) is
their record, and each repository's variables are its projection (the hub's
constitution § 17). The credential is encrypted at rest with the AI layer's
keys (`ai/crypto.py`, rotated with them by `manage.py rotate_ai_credentials`)
and write-only over the API: it goes in, and only whether one is set comes back.
"""

from django.conf import settings
from django.db import models

from ai import crypto

# The repositories the platform publishes content through, until a person changes the list.
DEFAULT_OUTLETS = ["bash-365/bash-365.com", "bamr87/lifehacker.dev", "bamr87/it-journey"]


def default_outlets() -> list[str]:
    return list(DEFAULT_OUTLETS)


class SwitchConfig(models.Model):
    """One row (`load()`): the outlets and the credential."""

    outlets = models.JSONField(default=default_outlets, help_text="The outlet repositories, as owner/name.")
    credential_encrypted = models.TextField(blank=True, editable=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "content switches"

    def __str__(self):
        return f"content switches ({len(self.outlets)} outlets)"

    @classmethod
    def load(cls) -> "SwitchConfig":
        return cls.objects.get_or_create(pk=1)[0]

    # ── the credential: encrypted at rest, never returned ───────────────────
    @property
    def has_credential(self) -> bool:
        return bool(self.credential_encrypted)

    def set_credential(self, raw: str) -> None:
        self.credential_encrypted = crypto.encrypt(raw or "")

    def get_credential(self) -> str:
        """The token, or '' when none is set or no current key can read it (set it again)."""
        try:
            return crypto.decrypt(self.credential_encrypted)
        except crypto.InvalidToken:
            return ""
