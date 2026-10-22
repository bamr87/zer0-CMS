"""Provider credentials, encrypted at rest with `cryptography`'s MultiFernet.

The first key encrypts and every key decrypts. The keys are
`AI_CREDENTIAL_KEYS` (comma-separated Fernet keys, newest first), then one key
derived from `SECRET_KEY` and one from each of `SECRET_KEY_FALLBACKS` — so a
credential is never stored in the clear, one stored before
`AI_CREDENTIAL_KEYS` was set (or before `SECRET_KEY` rotated) still reads, and
`manage.py rotate_ai_credentials` moves every credential to the first key —
the providers' and every other secret kept under these keys (`REENCRYPT`). To
rotate: put a new key first, run the command, then drop the old key.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

__all__ = ["REENCRYPT", "InvalidToken", "decrypt", "encrypt"]

# The other secrets kept under these keys: each `fn() -> int` re-encrypts its rows with the first key and says how
# many, raising ValueError (naming the row) on one no key reads. An app adds its own in `AppConfig.ready` — the
# automations' webhook secrets — so one rotation moves every secret and none is left behind under a dropped key.
REENCRYPT: set = set()


def _derived(secret: str) -> bytes:
    return base64.urlsafe_b64encode(hashlib.sha256(f"zer0-cms/ai-credentials:{secret}".encode()).digest())


def _fernet() -> MultiFernet:
    secrets = [settings.SECRET_KEY, *getattr(settings, "SECRET_KEY_FALLBACKS", [])]
    return MultiFernet([Fernet(k) for k in [*settings.AI_CREDENTIAL_KEYS, *map(_derived, secrets)]])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode() if token else ""
