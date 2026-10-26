"""Tests: in-memory SQLite (or DATABASE_URL, which the CI Postgres job sets),
eager Celery, an in-memory outbox relay, and offline model backends — no test
reaches a network, a broker or a model provider (AGENTS.md)."""

from .base import *  # noqa: F403
from .base import BASE_DIR, MIDDLEWARE, REST_FRAMEWORK, env

# Static files are not collected in tests; whitenoise would warn on every request.
MIDDLEWARE = [m for m in MIDDLEWARE if m != "whitenoise.middleware.WhiteNoiseMiddleware"]

SECRET_KEY = "test-only"
DEBUG = False
ALLOWED_HOSTS = ["testserver", "localhost"]
# Rates are off (a test that needs one brings its own throttle), the API docs
# are on, one browser origin is allowed so CORS has something to assert, and
# nothing reports errors anywhere.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_RATES": {"anon": None, "principal": None, "research_fetch": None},
}
API_DOCS_ENABLED = True
CORS_ALLOWED_ORIGINS = ["https://allowed.example"]
SENTRY_DSN = ""
LOG_FORMAT = "text"
DATABASES = {"default": env.db("DATABASE_URL", default="sqlite://:memory:")}
DATABASES["default"]["ATOMIC_REQUESTS"] = True
PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
CELERY_BROKER_URL = "memory://"
OUTBOX_RELAY = "memory"
LLM_BACKEND = "recorded"
AI_DEFAULT_PROVIDER = "fake"
AI_CREDENTIAL_KEYS: list[str] = []
LLM_RECORDINGS_DIR = str(BASE_DIR / "agents" / "recordings")
EMBEDDING_BACKEND = "hashing"
EMBEDDING_MODEL = "hashing-256"
EMBEDDING_DIMENSIONS = 256
CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "tests"}}
MEDIA_ROOT = str(BASE_DIR / ".test-media")
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
}
