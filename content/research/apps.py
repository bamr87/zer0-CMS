"""App config for `research`: its run kinds registered with the AI layer
(research/handlers.py), its bundled assistants and output schemas seeded after
every migrate (research/data/bundled.yaml, through `ai.services.import_bundled`,
with the migrated models), a ready source's vector refreshed after it is saved
and dropped when it is deleted, and the sources a brief cites handed to the
brief's writer (`ai.handlers.brief_context`)."""

from pathlib import Path

from django.apps import AppConfig
from django.apps import apps as installed
from django.db import transaction
from django.db.models.signals import post_delete, post_migrate, post_save

BUNDLE = Path(__file__).resolve().parent / "data" / "bundled.yaml"


class ResearchConfig(AppConfig):
    name = "research"
    verbose_name = "Research"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from ai.handlers import brief_context

        from . import handlers  # noqa: F401 — registers the run kinds
        from .models import Source
        from .services import brief_sources, forget

        post_migrate.connect(_seed, sender=self)
        post_save.connect(_embed_later, sender=Source, dispatch_uid="research.embed")
        post_delete.connect(forget, sender=Source, dispatch_uid="research.forget")
        brief_context.connect(brief_sources, dispatch_uid="research.brief_sources")


def _embed_later(sender, instance, **kwargs):
    if instance.status == instance.READY:
        from .tasks import embed_source

        transaction.on_commit(lambda: embed_source.delay(instance.pk))


def _seed(sender, apps=installed, **kwargs):
    from ai.services import import_bundled

    try:
        for name in ("OutputSchema", "Assistant"):
            apps.get_model("ai", name)
    except LookupError:
        return  # the migrate left the AI tables unapplied
    import_bundled(apps, BUNDLE)
