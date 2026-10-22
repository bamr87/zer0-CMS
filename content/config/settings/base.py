"""Settings shared by every environment of the content plane.

The layout follows parodynews's (base / development / production / testing),
and every value that differs between machines comes from the environment
through django-environ, so the same image runs in compose, CI and production.
Nothing here names a model provider or holds a key: the LLM and embedding
backends are chosen by `LLM_BACKEND` / `EMBEDDING_BACKEND`, and tests pin them
to offline backends (`config.settings.testing`).
"""

import tomllib
from pathlib import Path

import environ
from celery.schedules import crontab
from corsheaders.defaults import default_headers as cors_default_headers

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # content/
REPO_ROOT = BASE_DIR.parent  # the zer0-CMS checkout

env = environ.Env(
    DEBUG=(bool, False),
    # `.localhost`: each imported site is a Wagtail Site at <site>.localhost.
    ALLOWED_HOSTS=(list, ["localhost", "127.0.0.1", ".localhost"]),
    CSRF_TRUSTED_ORIGINS=(list, []),
)
if (BASE_DIR / ".env").exists():
    environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

SECRET_KEY = env("SECRET_KEY", default="insecure-development-key-change-me")
DEBUG = env("DEBUG")
ALLOWED_HOSTS = env("ALLOWED_HOSTS")
CSRF_TRUSTED_ORIGINS = env("CSRF_TRUSTED_ORIGINS")

# ── Identity (ops/README.md): what /version reports and every log line and
# response header carries. The version is the one release-please maintains in
# pyproject.toml; the commit and build time come from the image build.
APP_NAME = "zer0-content"
with (BASE_DIR / "pyproject.toml").open("rb") as _pyproject:
    APP_VERSION = tomllib.load(_pyproject)["project"]["version"]
GIT_SHA = env("GIT_SHA", default="unknown")
BUILT_AT = env("BUILT_AT", default="unknown")

INSTALLED_APPS = [
    # The content plane's own apps. `cms` first: it owns the image model the
    # rest of Wagtail is configured to use.
    "cms",
    "agents",
    "ai",
    "research",
    "ideas",
    "suggestions",
    "graph",
    "workflow",
    "outbox",
    "api",
    "mcp_server",
    "importers",
    "exporters",
    "ops",
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
    "django_filters",
    "drf_spectacular",
    "corsheaders",
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

# Outermost first. The request id is bound before anything else runs, so a
# static file, a security redirect or a crash deep inside all carry it; the
# access line is measured just inside it; CORS sits above WhiteNoise and
# CommonMiddleware because both can answer a request before it gets further.
MIDDLEWARE = [
    "ops.middleware.RequestIdMiddleware",
    "ops.middleware.AccessLogMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "ops.middleware.SecurityHeadersMiddleware",
    "corsheaders.middleware.CorsMiddleware",
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

# ── The studio (web/studio, api/studio.py) ──────────────────────────────────
# `npm run build` in web/ writes the studio here; its assets are static files
# under /static/studio/ and /studio/ answers with its index.html. The image
# builds it in a Node stage and points STUDIO_DIST at the copy.
STUDIO_DIST = Path(env("STUDIO_DIST", default=str(REPO_ROOT / "web" / "studio" / "dist")))
STATICFILES_DIRS = [("studio", str(STUDIO_DIST))] if STUDIO_DIST.is_dir() else []

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
# Every non-2xx is the envelope in ops/errors.py; rates are per anonymous
# address, per person and per agent token (ops/throttling.py), and an empty
# rate turns a scope off.
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "agents.auth.AgentTokenAuthentication",
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": ["rest_framework.permissions.IsAuthenticated"],
    "EXCEPTION_HANDLER": "ops.errors.drf_exception_handler",
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_THROTTLE_CLASSES": ["ops.throttling.AnonThrottle", "ops.throttling.PrincipalThrottle"],
    "DEFAULT_THROTTLE_RATES": {
        "anon": env("THROTTLE_ANON_RATE", default="120/min") or None,
        "principal": env("THROTTLE_PRINCIPAL_RATE", default="600/min") or None,
        # Per person, what makes the research library reach the web: a page captured or fetched again, a search,
        # a feed subscribed to or read now (research/views.py).
        "research_fetch": env("THROTTLE_RESEARCH_FETCH_RATE", default="30/min") or None,
    },
    # How many proxies sit in front, so the anonymous bucket keys on the client
    # address rather than the load balancer's.
    "NUM_PROXIES": env.int("NUM_PROXIES", default=None),
}

# ── OpenAPI (ops/openapi.py) ────────────────────────────────────────────────
# The document covers the platform's own REST endpoints (SERVE_URLCONF); the
# surface version is "2" as in the path, so a release bump never makes the
# committed schemas/openapi/openapi.json stale.
SPECTACULAR_SETTINGS = {
    "TITLE": "zer0-CMS platform API",
    "DESCRIPTION": "Agent runs, the content graph, suggestions and the tool registry; and for the studio and the "
    "extension, the session, sites, pages, revisions, publishing and the review inbox. "
    "Wagtail's pages, images and documents endpoints live beside these at /api/v2/ and are documented by Wagtail.",
    "VERSION": "2",
    "OAS_VERSION": "3.1.0",
    "SCHEMA_PATH_PREFIX": r"/api/v2",
    "SERVE_URLCONF": "ops.openapi",
    "SERVE_INCLUDE_SCHEMA": False,
    # A request body is its own component (`…Request`), without the read-only
    # fields a response carries, so the generated client asks only for what a
    # caller sends (G14: the studio's first create forms on owned rows).
    "COMPONENT_SPLIT_REQUEST": True,
    # Named enums, so the generated client's types read well (api/serializers.py).
    "ENUM_NAME_OVERRIDES": {
        "PageStatusEnum": "api.serializers.PAGE_STATUSES",
        "FieldKindEnum": "api.serializers.KINDS",
        "FieldGroupEnum": "api.serializers.GROUPS",
        "ChangeKindEnum": "api.serializers.CHANGE_KINDS",
        "TargetTypeEnum": "api.serializers.TARGET_TYPES",
        "IdeaStatusEnum": "ideas.models.Idea.STATUSES",
        "BrainstormKindEnum": "ideas.services.KINDS",
        "PromotionEnum": "ideas.serializers.PROMOTIONS",
        "SourceKindEnum": "research.models.Source.KINDS",
        "SourceStatusEnum": "research.models.Source.STATUSES",
        "CapturedKindEnum": "research.serializers.CAPTURED",
        "OutcomeEnum": "research.serializers.OUTCOMES",
        "VerdictEnum": "research.serializers.VERDICTS",
    },
    "SWAGGER_UI_DIST": "https://cdn.jsdelivr.net/npm/swagger-ui-dist@5",
    # A request body is its own component (`…Request`), without the read-only fields a response carries, so the
    # generated client (openapi-typescript) does not ask a request for an id or a timestamp the platform assigns.
    "COMPONENT_SPLIT_REQUEST": True,
}
API_DOCS_ENABLED = env.bool("API_DOCS_ENABLED", default=True)

# ── Browser origins (UPS-BE-06) ─────────────────────────────────────────────
# An allowlist, never `*` with credentials (the `ops.E001` check refuses it).
# Only the API paths answer cross-origin; the admin stays same-origin.
CORS_ALLOWED_ORIGINS = env.list("CORS_ALLOWED_ORIGINS", default=[])
CORS_ALLOW_CREDENTIALS = env.bool("CORS_ALLOW_CREDENTIALS", default=False)
CORS_URLS_REGEX = r"^/(api|graphql|mcp)/.*$"
CORS_ALLOW_HEADERS = [*cors_default_headers, "traceparent", "x-request-id", "mcp-protocol-version"]
CORS_EXPOSE_HEADERS = ["X-Request-Id", "X-App-Version", "traceparent", "Retry-After"]

# ── Security headers (UPS-OPS-23) ───────────────────────────────────────────
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "strict-origin-when-cross-origin"
PERMISSIONS_POLICY = env("PERMISSIONS_POLICY", default="camera=(), microphone=(), geolocation=(), payment=(), usb=()")
# Report-only to start: the Wagtail admin inlines scripts and styles, so an
# enforced policy is a later step, taken once the reports have been read.
CSP_REPORT_ONLY = env(
    "CSP_REPORT_ONLY",
    default="default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; base-uri 'self'; form-action 'self'",
)
CSP_REPORT_URI = env("CSP_REPORT_URI", default="")
CSRF_FAILURE_VIEW = "ops.errors.csrf_failure"

# ── Error reporting (UPS-OPS-13): on only when a DSN is set ─────────────────
SENTRY_DSN = env("SENTRY_DSN", default="")
SENTRY_ENVIRONMENT = env("SENTRY_ENVIRONMENT", default="development")
SENTRY_TRACES_SAMPLE_RATE = env.float("SENTRY_TRACES_SAMPLE_RATE", default=0.0)

# ── Celery: the agent runner and the outbox relay ───────────────────────────
REDIS_URL = env("REDIS_URL", default="redis://localhost:6379/0")
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default=REDIS_URL)
CELERY_RESULT_BACKEND = None
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_TASK_ALWAYS_EAGER", default=False)
CELERY_TASK_ACKS_LATE = True
# The worker, beat and relay log through LOGGING below, not Celery's own setup.
CELERY_WORKER_HIJACK_ROOT_LOGGER = False
# The outbox relay runs as its own process (`manage.py relay_outbox`, the
# compose `relay` service); beat schedules the nightly graph job and, every
# minute, the scheduled publishes that have come due (cms/tasks.py).
CELERY_BEAT_SCHEDULE = {
    "viewed-together-nightly": {"task": "graph.tasks.build_viewed_together", "schedule": crontab(hour=3, minute=17)},
    "publish-scheduled": {"task": "cms.tasks.publish_scheduled", "schedule": 60.0},
    # The research library's feed subscriptions that are due (research/tasks.py).
    "research-feeds": {"task": "research.tasks.refresh_feeds", "schedule": 300.0},
}
# A research fetch waits on someone else's server, so it runs on a queue of its own, which only the
# `research-worker` service consumes (docker-compose.yml): a slow site never holds the worker that runs agents and
# publishes pages.
CELERY_TASK_ROUTES = {f"research.tasks.{task}": {"queue": "research"} for task in ("fetch_source", "refresh_feed")}

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

# ── The AI content layer (ai/README.md) ─────────────────────────────────────
# AI_PROVIDERS: slug → dotted path of a provider adapter, merged over the six
# built in (ai/providers/__init__.py); "" disables one.
AI_PROVIDERS: dict[str, str] = {}
# The provider a request uses when no ProviderConfig row is flagged default.
AI_DEFAULT_PROVIDER = env("AI_DEFAULT_PROVIDER", default="claude_code")
# Fernet keys for provider credentials, the newest first; none derives one from
# SECRET_KEY (ai/crypto.py). Rotate with `manage.py rotate_ai_credentials`.
AI_CREDENTIAL_KEYS = env.list("AI_CREDENTIAL_KEYS", default=[])

# ── The graph (graph/README.md) ─────────────────────────────────────────────
# EMBEDDING_BACKEND: hashing (offline, deterministic) | litellm (or any provider that embeds)
EMBEDDING_BACKEND = env("EMBEDDING_BACKEND", default="hashing")
EMBEDDING_MODEL = env("EMBEDDING_MODEL", default="hashing-256")
EMBEDDING_DIMENSIONS = env.int("EMBEDDING_DIMENSIONS", default=256)
# An agent-proposed edge at or above this confidence is written; below, it
# becomes a Suggestion for an editor.
GRAPH_EDGE_AUTO_THRESHOLD = env.float("GRAPH_EDGE_AUTO_THRESHOLD", default=0.85)

# ── Ideas and research (ideas/README.md, research/README.md) ────────────────
# How alike two ideas' vectors must be to share a cluster, and to be offered as
# duplicates to merge (cosine; tune them to the embedding model).
IDEAS_CLUSTER_THRESHOLD = env.float("IDEAS_CLUSTER_THRESHOLD", default=0.5)
IDEAS_DUPLICATE_THRESHOLD = env.float("IDEAS_DUPLICATE_THRESHOLD", default=0.85)
# What the research fetcher sends and how much it takes (research/fetch.py).
RESEARCH_USER_AGENT = env("RESEARCH_USER_AGENT", default="zer0-cms-research/1.0 (+https://github.com/bamr87/zer0-CMS)")
RESEARCH_MAX_BYTES = env.int("RESEARCH_MAX_BYTES", default=5 * 1024 * 1024)
RESEARCH_FETCH_TIMEOUT = env.float("RESEARCH_FETCH_TIMEOUT", default=20.0)
RESEARCH_UPLOAD_MAX_BYTES = env.int("RESEARCH_UPLOAD_MAX_BYTES", default=10 * 1024 * 1024)
# How long one fetch task may run in all — robots.txt and the page, each within RESEARCH_FETCH_TIMEOUT, and the
# extraction — before Celery stops it (soft; the hard limit is 30 seconds later).
RESEARCH_TASK_TIME_LIMIT = env.int("RESEARCH_TASK_TIME_LIMIT", default=120)

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

# ── Logging (UPS-OPS-10..12; ops/logging.py) ────────────────────────────────
# LOG_FORMAT=json writes one object per line with ts/level/msg/logger/
# request_id/trace_id/app/version; text is the human format. Both redact
# tokens and Authorization values, and every record carries the request id.
LOG_LEVEL = env("LOG_LEVEL", default="INFO")
LOG_FORMAT = env("LOG_FORMAT", default="text")
if LOG_FORMAT not in ("json", "text"):
    LOG_FORMAT = "text"
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "context": {"()": "ops.logging.ContextFilter"},
        "redact": {"()": "ops.logging.RedactionFilter"},
    },
    "formatters": {
        "text": {
            "()": "ops.logging.TextFormatter",
            "fmt": "%(asctime)s %(levelname)s %(name)s [%(request_id)s] %(message)s",
        },
        "json": {"()": "ops.logging.JsonFormatter", "app": APP_NAME, "version": APP_VERSION},
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "filters": ["context", "redact"], "formatter": LOG_FORMAT}
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {
        # Wagtail logs every page action and every background task at INFO; the
        # audit trail is in the database (log entries, agent runs), not stdout.
        **{
            name: {"level": env("WAGTAIL_LOG_LEVEL", default="WARNING")}
            for name in ("wagtail", "django_tasks", "modelsearch")
        },
        # One line per request (ops.middleware.AccessLogMiddleware).
        "ops.access": {"level": "INFO"},
    },
}
