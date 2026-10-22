# The platform (Django + Wagtail): gunicorn on :8000.
#
# Build from the repository root, because the event schemas the outbox
# validates against live in ../schemas, outside this project:
#   docker build -f content/Dockerfile --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
# The root docker-compose.yml does exactly that (`--profile content`).
FROM python:3.13-slim AS base

# What /version reports and every log line carries (config/settings/base.py).
ARG GIT_SHA=unknown
ARG BUILT_AT=unknown
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production \
    GIT_SHA=${GIT_SHA} \
    BUILT_AT=${BUILT_AT}
LABEL org.opencontainers.image.source="https://github.com/bamr87/zer0-CMS" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.created="${BUILT_AT}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app/content
COPY content/requirements.txt content/requirements-providers.txt ./
RUN pip install -r requirements.txt
# The model providers' SDKs (ai/README.md): optional for the platform, which
# imports each only inside its adapter; build with AI_PROVIDERS=false to leave them out.
ARG AI_PROVIDERS=true
RUN if [ "$AI_PROVIDERS" = "true" ]; then pip install -r requirements-providers.txt; fi

COPY schemas /app/schemas
COPY content /app/content
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput -v0 \
    && mkdir -p /app/content/media \
    && chown -R app:app /app/content/media /app/content/static

USER app
EXPOSE 8000
# No HEALTHCHECK here: one image runs four roles (web, worker, beat, relay),
# and only the web role answers HTTP. Each compose service declares its own
# (the web role's is /readyz). The access log is the platform's own one line
# per request (ops/middleware.py), so gunicorn's is off.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
