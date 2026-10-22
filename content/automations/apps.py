"""App config for `automations`: a research source that has just become ready fires the automations waiting for new
sources (`services.on_source`) — in a savepoint, so an automation's trouble never stops a source from being kept —
and the automations' webhook secrets, kept under the AI layer's credential keys, join `manage.py
rotate_ai_credentials` (`ai.crypto.REENCRYPT`), so one rotation moves them too. Its tool (`tools.py`) is found by the
agents app's tool discovery; its event consumer is registered by the process that reads the stream
(`consumers.register`, from `manage.py consume_events`)."""

import logging

from django.apps import AppConfig
from django.db import transaction
from django.db.models.signals import post_save

log = logging.getLogger(__name__)


class AutomationsConfig(AppConfig):
    name = "automations"
    verbose_name = "Automations"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from ai import crypto
        from research.models import Source

        from .services import reencrypt_secrets

        post_save.connect(_source_saved, sender=Source, dispatch_uid="automations.source")
        crypto.REENCRYPT.add(reencrypt_secrets)


def _source_saved(sender, instance, created=False, update_fields=None, raw=False, **kwargs):
    """A source is new to automations when it is first ready: made ready (a feed item, a note, a document), or a
    captured page whose fetch has just succeeded (`research.services._fetched` saves its status). A source fetched
    again fires nothing it fired before: each automation runs once per source."""
    if raw or instance.status != instance.READY or not (created or "status" in (update_fields or ())):
        return
    from .services import on_source

    try:
        with transaction.atomic():
            on_source(instance)
    except Exception:  # noqa: BLE001 — an automation's trouble never stops a source from being kept; it is logged
        log.exception("automations: firing for source %s failed", instance.pk)
