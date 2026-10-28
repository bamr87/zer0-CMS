"""Local development: DEBUG on, SQLite unless DATABASE_URL says otherwise."""

from .base import *  # noqa: F403
from .base import env

DEBUG = True
ALLOWED_HOSTS = ["*"]
# Mail is printed here unless EMAIL_BACKEND names a backend to try (base.py).
EMAIL_BACKEND = env("EMAIL_BACKEND", default="django.core.mail.backends.console.EmailBackend")
# A passkey works on http://localhost (WebAuthn otherwise needs https).
MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN = env.bool("MFA_WEBAUTHN_ALLOW_INSECURE_ORIGIN", default=True)
