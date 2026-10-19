"""App config for `graph`."""

from django.apps import AppConfig


class GraphConfig(AppConfig):
    name = "graph"
    verbose_name = "Graph"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import consumers  # noqa: F401 — registers the event handlers
