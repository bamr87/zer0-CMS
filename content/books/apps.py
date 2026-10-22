"""App config for `books`: after every migrate, the bundled book assistants,
output schemas and pipeline (books/data/bundled.yaml) are created if they do not
exist, with the models as migrated and not at all while the AI tables are
unapplied.

A book's continuity ledger and character bible are not copied into the agents'
`Memory`: a book task reads them from the book's files in its request, and
`memory.recall` does not check page rights, so a copy would show unpublished
manuscript text to any person's assistant."""

from django.apps import AppConfig
from django.apps import apps as installed
from django.db.models.signals import post_migrate


class BooksConfig(AppConfig):
    name = "books"
    verbose_name = "Books"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        post_migrate.connect(_seed, sender=self)


def _seed(sender, apps=installed, **kwargs):
    from .services import import_bundled

    try:
        for name in ("OutputSchema", "Assistant", "Pipeline", "PipelineStep"):
            apps.get_model("ai", name)
    except LookupError:
        return  # the migrate left the AI tables unapplied
    import_bundled(apps)
