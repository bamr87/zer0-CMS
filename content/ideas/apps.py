"""App config for `ideas`: its bundled Brainstormer and Article writer (and the idea-list schema) seeded after every
migrate (ideas/data/bundled.yaml, through `ai.services.import_bundled`, with the migrated models); an idea's vector
refreshed by a worker after it is saved, and dropped when it is deleted."""

from pathlib import Path

from django.apps import AppConfig
from django.apps import apps as installed
from django.db import transaction
from django.db.models.signals import post_delete, post_migrate, post_save

BUNDLE = Path(__file__).resolve().parent / "data" / "bundled.yaml"


class IdeasConfig(AppConfig):
    name = "ideas"
    verbose_name = "Ideas"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from research.services import forget

        from .models import Idea

        post_migrate.connect(_seed, sender=self)
        post_save.connect(_embed_later, sender=Idea, dispatch_uid="ideas.embed")
        post_delete.connect(forget, sender=Idea, dispatch_uid="ideas.forget")


def _embed_later(sender, instance, **kwargs):
    from .tasks import embed_idea

    transaction.on_commit(lambda: embed_idea.delay(instance.pk))


def _seed(sender, apps=installed, **kwargs):
    from ai.services import import_bundled

    try:
        for name in ("OutputSchema", "Assistant"):
            apps.get_model("ai", name)
    except LookupError:
        return  # the migrate left the AI tables unapplied
    import_bundled(apps, BUNDLE)
