"""App config for `importers`."""

from django.apps import AppConfig


class ImportersConfig(AppConfig):
    name = "importers"
    verbose_name = "Importers"
    default_auto_field = "django.db.models.BigAutoField"
