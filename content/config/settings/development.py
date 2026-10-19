"""Local development: DEBUG on, SQLite unless DATABASE_URL says otherwise."""

from .base import *  # noqa: F403

DEBUG = True
ALLOWED_HOSTS = ["*"]
EMAIL_BACKEND = "django.core.mail.backends.console.EmailBackend"
