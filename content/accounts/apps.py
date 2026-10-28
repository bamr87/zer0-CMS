"""App config for `accounts`: how a person signs in outside the studio's
session — today a personal token (`UserToken`), which the VS Code extension
sends; PLAN G3 adds django-allauth and the rest of the account."""

from django.apps import AppConfig


class AccountsConfig(AppConfig):
    name = "accounts"
    verbose_name = "Accounts"
    default_auto_field = "django.db.models.BigAutoField"
