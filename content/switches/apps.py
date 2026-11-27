"""App config for `switches` (switches/README.md): the content outlets' GitHub Actions switches, read against the
hub's switch map and flipped by a person who manages sites. Its job handler registers on import, and its credential
is under the AI layer's keys, so rotating those keys rotates it too."""

from django.apps import AppConfig


class SwitchesConfig(AppConfig):
    name = "switches"
    verbose_name = "Content switches"
    default_auto_field = "django.db.models.BigAutoField"

    def ready(self):
        from ai.crypto import credentials_rotated

        from . import services

        credentials_rotated.connect(services.rotate_credentials, dispatch_uid="switches.credential")
