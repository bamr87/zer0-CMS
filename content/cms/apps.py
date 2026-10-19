"""App config for `cms`; `ready()` connects the publish signal handlers."""

from django.apps import AppConfig


class CmsConfig(AppConfig):
    name = "cms"
    verbose_name = "Content"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import signals  # noqa: F401
