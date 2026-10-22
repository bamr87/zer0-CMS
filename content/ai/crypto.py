"""Provider credentials, encrypted at rest with `cryptography`'s MultiFernet.

The keys are `AI_CREDENTIAL_KEYS` (comma-separated Fernet keys; the first
encrypts, every one decrypts), or — when none is set — one key derived from
`SECRET_KEY`, so a credential is never stored in the clear. To rotate: put a
new key first, run `manage.py rotate_ai_credentials`, then drop the old key.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

__all__ = ["InvalidToken", "decrypt", "encrypt", "rotate"]


def _fernet() -> MultiFernet:
    keys = list(settings.AI_CREDENTIAL_KEYS) or [
        base64.urlsafe_b64encode(hashlib.sha256(f"zer0-cms/ai-credentials:{settings.SECRET_KEY}".encode()).digest())
    ]
    return MultiFernet([Fernet(k) for k in keys])


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode() if value else ""


def decrypt(token: str) -> str:
    return _fernet().decrypt(token.encode()).decode() if token else ""


def rotate(token: str) -> str:
    """The same secret, re-encrypted with the first key."""
    return _fernet().rotate(token.encode()).decode() if token else ""
