"""Provider credentials, encrypted at rest with `cryptography`'s MultiFernet.

The first key encrypts and every key decrypts. The keys are
`AI_CREDENTIAL_KEYS` (comma-separated Fernet keys, newest first), then one key
derived from `SECRET_KEY` and one from each of `SECRET_KEY_FALLBACKS` — so a
credential is never stored in the clear, one stored before
`AI_CREDENTIAL_KEYS` was set (or before `SECRET_KEY` rotated) still reads, and
`manage.py rotate_ai_credentials` moves every credential to the first key. To
rotate: put a new key first, run the command, then drop the old key. Another
app that keeps credentials under these keys (distribution's channels) connects
to `credentials_rotated`, which the command sends in its transaction: the
receiver re-encrypts its own and answers how many, or raises to stop it all.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings
from django.dispatch import Signal

__all__ = ["InvalidToken", "credentials_rotated", "decrypt", "encrypt"]

credentials_rotated = Signal()


def _derived(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(f"zer0-cms/ai-credentials:{secret}".encode()).digest())


def _fernet() -> MultiFernet:
    secrets = [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]
    return MultiFernet([Fernet(k) for k in [*settings.AI_CREDENTIAL_KEYS, *map(_derived, secrets)]])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode() if token else ""
