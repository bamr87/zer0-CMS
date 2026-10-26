"""App config for `ai`: after every migrate, a `ProviderConfig` row for each
adapter in the registry and the bundled output schemas and assistant
(idempotent — what exists is left alone), written with the models as migrated
and skipped when the AI tables are not (`migrate ai zero`); and the hook that
settles a brief or reply whose run ended without succeeding
(`ai.handlers.settle` on `agents.runner.run_finished`). Its tools
(`ai/tools.py`) are found by the agents app's tool discovery."""

from django.apps import AppConfig
from django.apps import apps as installed
from django.db.models.signals import post_migrate


class AiConfig(AppConfig):
    name = "ai"
    verbose_name = "AI content layer"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from agents.runner import run_finished

        from .handlers import settle

        post_migrate.connect(_seed, sender=self)
        run_finished.connect(settle, dispatch_uid="ai.settle")


def _seed(sender, apps=installed, **kwargs):
    from .services import ensure_providers, import_bundled

    try:
        for name in ("ProviderConfig", "OutputSchema", "Assistant"):
            apps.get_model("ai", name)
    except LookupError:
        return  # the migrate left the AI tables unapplied
    ensure_providers(apps)
    import_bundled(apps)
