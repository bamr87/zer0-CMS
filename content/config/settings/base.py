"""Settings shared by every environment of the content plane.

The layout follows barodybroject's (base / development / production / testing),
and every value that differs between machines comes from the environment
through django-environ, so the same image runs in compose, CI and production.
Nothing here names a model provider or holds a key: the LLM and embedding
backends are chosen by `LLM_BACKEND` / `EMBEDDING_BACKEND`, and tests pin them
to offline backends (`config.settings.testing`).
"""

from pathlib import Path

import environ
from celery.schedules import crontab

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # content/
REPO_ROOT = BASE_DIR.parent  # the zer0-CMS checkout

env = environ.Env(
    DEBUG=(bool, False),
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY", default="insecure-development-key-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

INSTALLED_APPS = [
    # The content plane's own apps. `cms` first: it owns the image model the
    # rest of Wagtail is configured to use.
    "cms",
    "agents",
    "suggestions",
    "graph",
    "workflow",
    "outbox",
    "api",
    "mcp_server",
    "importers",
    "exporters",
    # Wagtail.
    "wagtail.contrib.forms",
    "wagtail.contrib.redirects",
    "wagtail.contrib.settings",
    "wagtail.embeds",
    "wagtail.sites",
    "wagtail.users",
    "wagtail.snippets",
    "wagtail.documents",
    "wagtail.images",
    "wagtail.search",
    "wagtail.admin",
    "wagtail.api.v2",
    "wagtail",
    "modelcluster",
    "taggit",
    # Headless APIs.
    "rest_framework",
    "graphene_django",
    "grapple",
    # Django.
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "wagtail.contrib.redirects.middleware.RedirectMiddleware",
    "agents.tracing.TraceMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

# SQLite by default (development, the fast test tier); compose and the CI
# Postgres job set DATABASE_URL to pgvector/pgvector:pg16.
DATABASES = {"default": env.db("DATABASE_URL", default=f"sqlite:///{BASE_DIR / 'db.sqlite3'}")}
# Every request is one transaction, so an admin publish and the outbox row its
# signal writes commit together or not at all (outbox/README.md).
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "UTC"
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = env("STATIC_ROOT", default=str(BASE_DIR / "static"))
MEDIA_URL = "/media/"
MEDIA_ROOT = env("MEDIA_ROOT", default=str(BASE_DIR / "media"))
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedStaticFilesStorage"},
}

CACHES = {"default": env.cache("CACHE_URL", default="locmemcache://")}

# ── Wagtail ─────────────────────────────────────────────────────────────────
WAGTAIL_SITE_NAME = "zer0-CMS"
WAGTAILADMIN_BASE_URL = env("WAGTAILADMIN_BASE_URL", default="http://localhost:8000")
WAGTAILIMAGES_IMAGE_MODEL = "cms.ContentImage"
WAGTAILSEARCH_BACKENDS = {"default": {"BACKEND": "wagtail.search.backends.database"}}
WAGTAILDOCS_EXTENSIONS = ["csv", "docx", "key", "odt", "pdf", "pptx", "rtf", "txt", "xlsx", "zip"]
WAGTAIL_I18N_ENABLED = False

# ── GraphQL (Grapple) ───────────────────────────────────────────────────────
GRAPHENE = {"SCHEMA": "grapple.schema.schema"}
GRAPPLE = {
    "APPS": ["cms"],
    "ADD_SEARCH_HIT": False,
    "EXPOSE_GRAPHIQL": True,
    "PAGE_SIZE": 20,
    "MAX_PAGE_SIZE": 100,
}

# ── REST ────────────────────────────────────────────────────────────────────
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "agents.auth.AgentTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
}

# ── Celery: the agent runner and the outbox relay ───────────────────────────
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_ACKS_LATE = True
# The outbox relay runs as its own process (`manage.py relay_outbox`, the
# compose `relay` service); beat schedules the nightly graph job.
CELERY_BEAT_SCHEDULE = {
    "viewed-together-nightly": {"task": "graph.tasks.build_viewed_together", "schedule": crontab(hour=3, minute=17)},
}

# ── The agent harness (agents/README.md) ────────────────────────────────────
# LLM_BACKEND: recorded (fixtures; the test default) | fake | litellm
LLM_BACKEND = env("LLM_BACKEND", default="recorded")
LLM_RECORDINGS_DIR = env("LLM_RECORDINGS_DIR", default=str(BASE_DIR / "agents" / "recordings"))
# With LLM_BACKEND=litellm, also write every completion as a recording.
LLM_RECORD = env.bool("ZER0_LLM_RECORD", default=False)
# Promotion from `suggest` to `draft`/`auto` needs this accept rate over at
# least this many decided suggestions, plus a passing eval suite.
AGENT_PROMOTION_ACCEPT_RATE = env.float("AGENT_PROMOTION_ACCEPT_RATE", default=0.8)
AGENT_PROMOTION_MIN_DECISIONS = env.int("AGENT_PROMOTION_MIN_DECISIONS", default=10)
AGENT_DEFINITIONS_DIR = BASE_DIR / "agents" / "definitions"

# ── The graph (graph/README.md) ─────────────────────────────────────────────
# EMBEDDING_BACKEND: hashing (offline, deterministic) | litellm
EMBEDDING_BACKEND = env("EMBEDDING_BACKEND", default="hashing")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="hashing-256")
EMBEDDING_DIMENSIONS = env.int("EMBEDDING_DIMENSIONS", default=256)
# An agent-proposed edge at or above this confidence is written; below, it
# becomes a Suggestion for an editor.
GRAPH_EDGE_AUTO_THRESHOLD = env.float("GRAPH_EDGE_AUTO_THRESHOLD", default=0.85)

# ── Events (outbox/README.md, schemas/events/) ──────────────────────────────
EVENTS_SCHEMA_DIR = REPO_ROOT / "schemas" / "events"
EVENTS_SCHEMA_BASE_URI = "https://github.com/bamr87/zer0-CMS/blob/main/schemas/events/"
EVENTS_SOURCE = "zer0-cms/content"
EVENTS_STREAM = env("EVENTS_STREAM", default="zer0:content")
# OUTBOX_RELAY: redis (Redis Streams, PLAN-D6) | memory (tests)
OUTBOX_RELAY = env("OUTBOX_RELAY", default="redis")

# ── MCP (mcp_server/README.md) ──────────────────────────────────────────────
# Origins a browser-based MCP client may call from; a request with any other
# Origin header is refused (MCP's DNS-rebinding rule). No Origin header —
# a CLI, an IDE, the Rails app — is allowed.
MCP_ALLOWED_ORIGINS = env.list("MCP_ALLOWED_ORIGINS", default=["http://localhost:8000", "http://127.0.0.1:8000"])

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    # Wagtail logs every page action and every background task at INFO; the
    # audit trail is in the database (log entries, agent runs), not stdout.
    "loggers": {
        name: {"level": env("WAGTAIL_LOG_LEVEL", default="WARNING")}
        for name in ("wagtail", "django_tasks", "modelsearch")
    },
}
