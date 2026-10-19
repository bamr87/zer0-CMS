# The content plane (Django + Wagtail): gunicorn on :8000.
#
# Build from the repository root, because the event schemas the outbox
# validates against live in ../schemas, outside this project:
#   docker build -f content/Dockerfile .
# The root docker-compose.yml does exactly that (`--profile content`).
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DJANGO_SETTINGS_MODULE=config.settings.production

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 app

WORKDIR /app/content
COPY content/requirements.txt ./requirements.txt
RUN pip install -r requirements.txt

COPY schemas /app/schemas
COPY content /app/content
RUN SECRET_KEY=build-only python manage.py collectstatic --noinput -v0 \
    && mkdir -p /app/content/media \
    && chown -R app:app /app/content/media /app/content/static

USER app
EXPOSE 8000
# No HEALTHCHECK here: one image runs four roles (web, worker, beat, relay),
# and only the web role answers HTTP. Each compose service declares its own.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3", "--access-logfile", "-"]
