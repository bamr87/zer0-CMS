"""App config for `sites` (sites/README.md): loading the services registers
the sync, write-back and doctor job handlers."""

from django.apps import AppConfig


class SitesConfig(AppConfig):
    name = "sites"
    verbose_name = "Sites"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import services  # noqa: F401 — registers the job handlers
