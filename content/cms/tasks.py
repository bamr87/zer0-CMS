"""Scheduled publishing on Celery beat (`CELERY_BEAT_SCHEDULE["publish-scheduled"]`).

A page scheduled in the studio (cms.services.schedule) is a revision Wagtail
holds with an approved go-live time, and a page with an expiry comes down once
it has passed. Every minute this does what Wagtail's `publish_scheduled`
command does — take down what has expired, then publish what has come due —
but one object at a time, each in its own transaction, so a page that goes
live and the outbox event its publish writes commit together, and one that
fails (a slug a sibling took since, an event the schema refuses, an agent
definition's eval gate) is logged and retried next minute instead of rolling
back the rest. A sweep still running when beat fires again is skipped: the
cache lock holds across processes because the deployed cache is shared.
"""

import logging

from celery import shared_task
from django.apps import apps
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone
from wagtail.models import DraftStateMixin, Page, Revision

log = logging.getLogger(__name__)
LOCK = "cms.publish_scheduled.running"


@shared_task
def publish_scheduled():
    if not cache.add(LOCK, True, timeout=600):
        log.info("scheduled publishing: the previous sweep is still running")
        return
    try:
        now = timezone.now()
        models = [Page, *(m for m in apps.get_models() if issubclass(m, DraftStateMixin) and not issubclass(m, Page))]
        for model in models:
            for obj in list(model.objects.filter(live=True, expire_at__lt=now).order_by("expire_at")):
                _each(obj, lambda o: o.unpublish(set_expired=True, log_action="wagtail.unpublish.scheduled"))
        for revision in list(Revision.objects.filter(approved_go_live_at__lt=now).order_by("approved_go_live_at")):
            _each(revision, lambda r: r.publish(log_action="wagtail.publish.scheduled"))
    finally:
        cache.delete(LOCK)


def _each(obj, act):
    try:
        with transaction.atomic():
            act(obj)
    except Exception:  # noqa: BLE001 — any one object's failure is logged and retried next sweep, never fatal to the rest
        log.exception("scheduled publishing failed for %r; it is retried on the next sweep", obj)
