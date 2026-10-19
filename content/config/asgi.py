"""ASGI entry point, for servers that prefer it; the content plane is
synchronous and runs the same under either."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.production")
application = get_asgi_application()
