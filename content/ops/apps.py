"""App config: starts error reporting and registers the one system check that
guards a CORS misconfiguration no test request would reveal."""

from django.apps import AppConfig
from django.conf import settings
from django.core.checks import Error, Tags, register


def check_cors(app_configs, **kwargs):
    """`CORS_ALLOW_ALL_ORIGINS` with credentials lets any page act as a signed-in
    editor through the browser's cookies (UPS-BE-06)."""
    if getattr(settings, "CORS_ALLOW_ALL_ORIGINS", False) and getattr(settings, "CORS_ALLOW_CREDENTIALS", False):
        return [
            Error(
                "CORS_ALLOW_ALL_ORIGINS together with CORS_ALLOW_CREDENTIALS lets any origin act as a signed-in user.",
                hint="List the browser origins in CORS_ALLOWED_ORIGINS instead.",
                id="ops.E001",
            )
        ]
    return []


class OpsConfig(AppConfig):
    name = "ops"
    verbose_name = "Operations"

    def ready(self):
        from . import sentry

        sentry.init()
        register(check_cors, Tags.security)
