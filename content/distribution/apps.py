"""The distribution app (PLAN G5): channels, the publishing queue, the ledger
and statistics — distribution/README.md."""

from django.apps import AppConfig


class DistributionConfig(AppConfig):
    name = "distribution"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from ai.crypto import credentials_rotated

        # The registry's tools and the outbox consumer register themselves on import.
        from . import consumers, services, tools  # noqa: F401

        # A channel's credential is under the AI layer's keys, so rotating those keys rotates it too.
        credentials_rotated.connect(services.rotate_credentials, dispatch_uid="distribution.channels")
