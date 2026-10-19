"""App config for `agents`: discovers every app's `tools.py` into the one
registry, and provisions the standard agent users after each migrate."""

from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AgentsConfig(AppConfig):
    name = "agents"
    verbose_name = "Agents"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from django.utils.module_loading import autodiscover_modules

        from .principals import ensure_standard_principals

        autodiscover_modules("tools")
        post_migrate.connect(_provision, sender=self)
        self._provision = ensure_standard_principals


def _provision(sender, **kwargs):
    sender._provision()
