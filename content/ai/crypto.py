"""Credentials, encrypted at rest with `cryptography`'s MultiFernet: the AI
providers' and every other credential an app keeps with these keys.

The first key encrypts and every key decrypts. The keys are
`AI_CREDENTIAL_KEYS` (comma-separated Fernet keys, newest first), then one key
derived from `SECRET_KEY` and one from each of `SECRET_KEY_FALLBACKS` — so a
credential is never stored in the clear, one stored before
`AI_CREDENTIAL_KEYS` was set (or before `SECRET_KEY` rotated) still reads, and
`manage.py rotate_ai_credentials` moves every credential to the first key. To
rotate: put a new key first, run the command, then drop the old key.

A model that keeps a credential with these keys is named in `HOLDERS` (an app
adds its own with `holds_credentials` in its `AppConfig.ready`), with
`get_credential()` and `set_credential()` over a `credential_encrypted`
field, so the rotation re-encrypts it too: one left out would stop reading
the day its old key is dropped.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

__all__ = ["HOLDERS", "InvalidToken", "decrypt", "encrypt", "holds_credentials"]

HOLDERS = ["ai.ProviderConfig"]  # "app_label.Model" of every model that keeps a credential encrypted here


def holds_credentials(label: str) -> None:
    """Name a model that keeps a credential encrypted with these keys, so `rotate_ai_credentials` moves it too."""
    if label not in HOLDERS:
        HOLDERS.append(label)


def _derived(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(f"zer0-cms/ai-credentials:{secret}".encode()).digest())


def _fernet() -> MultiFernet:
    secrets = [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]
    return MultiFernet([Fernet(k) for k in [*settings.AI_CREDENTIAL_KEYS, *map(_derived, secrets)]])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode() if token else ""
