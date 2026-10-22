"""App config for `books`: after every migrate, the bundled book assistants,
output schemas and pipeline (books/data/bundled.yaml) are created if they do not
exist, with the models as migrated and not at all while the AI tables are
unapplied; and every saved revision of a book refreshes the agents' memory of it
(its continuity ledger and character bible, `books.services.remember`)."""

from django.apps import AppConfig
from django.apps import apps as installed
from django.db.models.signals import post_migrate, post_save


class BooksConfig(AppConfig):
    name = "books"
    verbose_name = "Books"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from wagtail.models import Revision

        post_migrate.connect(_seed, sender=self)
        post_save.connect(_remember, sender=Revision, dispatch_uid="books.remember")


def _seed(sender, apps=installed, **kwargs):
    from .services import import_bundled

    try:
        for name in ("OutputSchema", "Assistant", "Pipeline", "PipelineStep"):
            apps.get_model("ai", name)
    except LookupError:
        return  # the migrate left the AI tables unapplied
    import_bundled(apps)


def _remember(sender, instance, **kwargs):
    from django.contrib.contenttypes.models import ContentType

    from cms.models import BookPage

    from .services import remember

    if instance.content_type_id == ContentType.objects.get_for_model(BookPage).pk:
        remember(instance.as_object())
