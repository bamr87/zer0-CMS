"""App config for `outbox`."""

from django.apps import AppConfig


class OutboxConfig(AppConfig):
    name = "outbox"
    verbose_name = "Outbox"
    default_auto_field = "django.db.models.BigAutoField"
