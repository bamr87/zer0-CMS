"""App config for `aieo`: its run kinds registered with the AI layer (aieo/handlers.py), the hook that fails an
audit or a citation check whose run ended without succeeding, and the one that drops a deleted audit's vector; after
every migrate, the pattern library and the bundled assistants and output schemas made from AIEO's prompt files where
they do not exist yet (aieo/prompts.py, with the migrated models, and not while the tables they need are
unapplied); and the connectors' credentials, kept under the AI layer's keys, join `manage.py rotate_ai_credentials`
(`ai.crypto.credentials_rotated`), so one rotation moves them too. Its tools (aieo/tools.py) are found by the agents
app's tool discovery."""

from django.apps import AppConfig
from django.apps import apps as installed
from django.db.models.signals import post_delete, post_migrate


class AieoConfig(AppConfig):
    name = "aieo"
    verbose_name = "AIEO"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from agents.runner import run_finished
        from ai.crypto import credentials_rotated
        from research.services import forget

        from .handlers import settle
        from .models import Audit
        from .services import rotate_credentials

        post_migrate.connect(_seed, sender=self)
        run_finished.connect(settle, dispatch_uid="aieo.settle")
        post_delete.connect(forget, sender=Audit, dispatch_uid="aieo.forget")  # an audit's vector goes with it
        credentials_rotated.connect(rotate_credentials, dispatch_uid="aieo.connectors")


def _seed(sender, apps=installed, **kwargs):
    from .prompts import seed

    try:
        for app, name in (
            ("ai", "OutputSchema"),
            ("ai", "Assistant"),
            ("importers", "ImportedRecord"),
            ("aieo", "Pattern"),
        ):
            apps.get_model(app, name)
    except LookupError:
        return  # the migrate left a table the seed needs unapplied
    seed(apps)
