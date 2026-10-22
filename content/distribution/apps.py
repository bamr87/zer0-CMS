"""The distribution app (PLAN G5): channels, the publishing queue, the ledger
and statistics — distribution/README.md."""

from django.apps import AppConfig


class DistributionConfig(AppConfig):
    name = "distribution"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        # The registry's tools and the outbox consumer register themselves on import.
        from . import consumers, tools  # noqa: F401
