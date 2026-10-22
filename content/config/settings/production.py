"""Production: everything that varies comes from the environment, a missing
SECRET_KEY is a startup error rather than a silent default, logs are JSON
lines, the API docs UI is off, and HSTS is on for the secure requests the
proxy forwards (compose serves plain HTTP on loopback, where it never
applies)."""

from .base import *  # noqa: F403
from .base import LOGGING, env

DEBUG = False
SECRET_KEY = env("SECRET_KEY")
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SESSION_COOKIE_SECURE = env.bool("SESSION_COOKIE_SECURE", default=True)
CSRF_COOKIE_SECURE = env.bool("CSRF_COOKIE_SECURE", default=True)
SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=False)
SECURE_HSTS_SECONDS = env.int("SECURE_HSTS_SECONDS", default=31536000)
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = False

LOG_FORMAT = env("LOG_FORMAT", default="json")
if LOG_FORMAT not in ("json", "text"):
    LOG_FORMAT = "json"
LOGGING["handlers"]["console"]["formatter"] = LOG_FORMAT

SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", default="production")
API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=False)
