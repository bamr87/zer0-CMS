# The platform (Django + Wagtail): gunicorn on :8000 (threaded workers), serving the studio at /studio/.
#
# Build from the repository root, because the event schemas the outbox
# validates against live in ../schemas and the studio in ../web, outside this
# project:
#   docker build -f content/Dockerfile --build-arg GIT_SHA=$(git rev-parse --short HEAD) .
# The root docker-compose.yml does exactly that (`--profile content`).

# The studio (web/), built with Node; only its dist/ reaches the platform image.
FROM node:24-slim AS studio
WORKDIR /app/web
COPY web/package.json web/package-lock.json ./
COPY web/packages/api/package.json packages/api/
COPY web/packages/tokens/package.json packages/tokens/
COPY web/packages/ui/package.json packages/ui/
COPY web/studio/package.json studio/
RUN npm ci --no-audit --no-fund
COPY web ./
RUN npm run build

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
COPY content/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY schemas /app/schemas
COPY content /app/content
# STUDIO_DIST's default (config/settings/base.py): collectstatic gathers the
# studio's assets under /static/studio/ and api/studio.py serves its index.
COPY --from=studio /app/web/studio/dist /app/web/studio/dist
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput -v0 \
    && mkdir -p /app/content/media \
    && chown -R app:app /app/content/media /app/content/static

USER app
EXPOSE 8000
# No HEALTHCHECK here: one image runs four roles (web, worker, beat, relay),
# and only the web role answers HTTP. Each compose service declares its own
# (the web role's is /readyz). The access log is the platform's own one line
# per request (ops/middleware.py), so gunicorn's is off. gunicorn reads its
# bind, workers and threaded worker class from content/gunicorn.conf.py.
CMD ["gunicorn", "config.wsgi:application"]
