"""App config for `outboxdesk`: the outbox harness (bamr87/outbox) operated from the studio — its belt read, sent on
and delivered, its arena trials and claim checks run in the worker (outboxdesk/README.md). Named so as not to be the
platform's own transactional outbox (`outbox/`), whose event stream it consumes (consumers.py)."""

from django.apps import AppConfig


class OutboxDeskConfig(AppConfig):
    name = "outboxdesk"
    verbose_name = "Outbox desk"
    default_auto_field = "django.db.models.BigAutoField"
