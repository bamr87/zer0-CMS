"""App config for `accounts`: how a person signs in and what they sign in with
(accounts/README.md) — django-allauth configured for the platform (the
adapters, the IdPs from the environment, their groups), the Wagtail and
Django admins' sign-in routed to it, and a person's API token (`UserToken`)
for a client that is not a browser."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Accounts"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from . import groups  # noqa: F401 — connects the IdP groups' sync to allauth's sign-in signal
