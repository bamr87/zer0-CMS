"""The content plane's Django project package. Importing it loads the Celery
app, so `@shared_task` functions bind to it in every process."""

from .celery import app as celery_app

__all__ = ("celery_app",)
