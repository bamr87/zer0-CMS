"""App config for `voice` (voice/README.md): a site's voice, composed from the stores that hold it (ADR 0010)."""

from django.apps import AppConfig


class VoiceConfig(AppConfig):
    name = "voice"
    verbose_name = "Voice"
    default_auto_field = "django.db.models.BigAutoField"
