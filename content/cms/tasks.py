"""Scheduled publishing on Celery beat (`CELERY_BEAT_SCHEDULE["publish-scheduled"]`).

A page scheduled in the studio (cms.services.schedule) is a revision Wagtail
holds with an approved go-live time; Wagtail's own `publish_scheduled` command
publishes the ones that have come due and unpublishes the expired. Beat runs
it every minute, in one transaction, so a page that goes live and the outbox
event its publish writes commit together, as every publish does.
"""

from celery import shared_task
from django.core.management import call_command
from django.db import transaction


@shared_task
def publish_scheduled():
    with transaction.atomic():
        call_command("publish_scheduled", verbosity=0)
