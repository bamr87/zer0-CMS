"""The Celery application: the agent runner (`agents.tasks.run_agent`) and the
outbox relay (`outbox.tasks.relay_outbox`) run here. Settings prefixed
`CELERY_` in Django settings configure it."""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.development")

app = Celery("zer0_content")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
