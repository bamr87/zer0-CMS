"""App config for `ai`: after every migrate, a `ProviderConfig` row for each
adapter in the registry and the bundled output schemas and assistant
(idempotent — what exists is left alone). Its tools (`ai/tools.py`) are found
by the agents app's tool discovery."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AiConfig(AppConfig):
    name = "ai"
    verbose_name = "AI content layer"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        post_migrate.connect(_seed, sender=self)


def _seed(sender, **kwargs):
    from .services import ensure_providers, import_bundled

    ensure_providers()
    import_bundled()
